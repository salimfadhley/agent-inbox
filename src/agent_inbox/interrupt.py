"""Whether an arrival is allowed to interrupt this agent — decided on this side.

The hub says *"there is mail for you, from X, about Y"* and stops. Between that and
disturbing an agent mid-turn there is a decision, and it belongs to the recipient:

- **Default-deny.** No configuration means no interruption, ever. Every agent already
  running was promised that mail cannot reach it mid-turn, and a release that quietly
  starts interrupting has broken that promise.
- **Gated on identity, never on what a sender wrote.** If a subject line could make a
  message interrupting, every message would say URGENT within a week and senders would
  own the recipient's attention. That is ADR 0008 — *no actor has authority over the
  mailbox* — arriving at the last layer.
- **Rate-limited.** An agent that can be woken without bound has been handed to whoever
  sends most; twenty messages in a minute must not be twenty interruptions.
- **Recorded, with a reason.** "Not trusted", "rate limited" and "nothing to wake with"
  are indistinguishable from outside and need three different fixes.

The decision is a **pure function** (:func:`decide`) — event, policy, recent history in;
decision and reason out — with the state and the I/O in :class:`Gatekeeper` around it.
``wake.py`` has the same shape for the same reason: the rules can then be tested without
a session, a network, or a clock.

**Delivery is not here.** Reaching into a running session is a wake adapter's job, and
adapters differ per harness. This module decides *whether*, hands the answer to an
adapter seam, and reports honestly when no adapter is there to take it.
"""

import logging
import time
import tomllib
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent_inbox.client import find_config

logger = logging.getLogger(__name__)

#: The window the rate limit is measured over.
RATE_WINDOW_SECONDS = 60.0

#: How many interruptions a minute a recipient will take before the rest are capped.
#: Chosen to be survivable rather than generous: the point of the limit is that a burst
#: costs the agent a bounded amount of attention, not that it loses nothing.
DEFAULT_MAX_PER_MINUTE = 4

#: The table this reads, in the project's own ``agent-inbox.toml``.
CONFIG_SECTION = "interrupt"


class Reason(StrEnum):
    """Why an arrival did or did not interrupt. The whole point is telling these apart.

    ``NOT_CONFIGURED`` and ``SENDER_NOT_TRUSTED`` are deliberately separate: the first
    is the untouched default and needs configuration, the second is a configuration
    that does not name this sender and needs editing. Reporting both as "denied" would
    make the commonest question — *why did nothing happen?* — unanswerable.
    """

    WAKE = "wake"
    NOT_CONFIGURED = "not-configured"
    IDENTITY_UNVERIFIED = "identity-unverified"
    SENDER_NOT_TRUSTED = "sender-not-trusted"
    RATE_LIMITED = "rate-limited"
    NO_ADAPTER = "no-adapter"


@dataclass(frozen=True, slots=True)
class Policy:
    """The recipient's own rules. Empty means "interrupt me for nobody"."""

    #: Senders allowed to interrupt, matched **exactly** against what the hub attributed
    #: the message to. Not normalised, not shortened: a remote actor arrives as a full
    #: URI, and trimming it to its last path segment would let anyone who can run a
    #: federated hub name an actor after someone you trust and inherit that trust.
    wake_from: frozenset[str] = frozenset()

    #: The most interruptions accepted per :data:`RATE_WINDOW_SECONDS`.
    max_per_minute: int = DEFAULT_MAX_PER_MINUTE

    @property
    def wakes_for_nobody(self) -> bool:
        """True when this policy can never interrupt — the untouched default."""
        return not self.wake_from

    @classmethod
    def of(cls, data: Mapping[str, Any] | None) -> Policy:
        """Read a policy from a configuration table, forgivingly.

        Anything unreadable becomes the default, which denies. A policy is a permission,
        so a malformed one must fail towards silence rather than towards noise.
        """
        if not data:
            return cls()
        senders = data.get("wake_from") or []
        if isinstance(senders, str):
            senders = [senders]  # a single name written without brackets
        names = frozenset(str(s).strip() for s in senders if str(s).strip())
        try:
            cap = int(data.get("max_per_minute", DEFAULT_MAX_PER_MINUTE))
        except TypeError, ValueError:
            cap = DEFAULT_MAX_PER_MINUTE
        return cls(wake_from=names, max_per_minute=max(0, cap))


@dataclass(frozen=True, slots=True)
class Decision:
    """What was decided about one arrival, and why."""

    wake: bool
    reason: Reason
    sender: str
    message_id: str
    #: Free text for a human reading a log — never parsed, never a control signal.
    detail: str = ""

    def as_record(self) -> dict[str, Any]:
        """The decision in the shape a log line or a diagnostic wants."""
        record = {
            "id": self.message_id,
            "from": self.sender,
            "wake": self.wake,
            "reason": str(self.reason),
        }
        if self.detail:
            record["detail"] = self.detail
        return record


def policy_from_config(data: Mapping[str, Any], engine: str | None = None) -> Policy:
    """Pick this engine's policy out of a parsed ``agent-inbox.toml``.

    One repository is worked by several agents and they are different correspondents,
    so the engine's own table wins **outright** over the project-wide one — including
    when it is empty, which is how one engine opts out of a project-wide setting::

        [interrupt]
        wake_from = ["ludmila_coe"]

        [agents.codex.interrupt]
        wake_from = []
    """
    entries = data.get("agents") or {}
    mine = entries.get(engine) if engine else None
    if isinstance(mine, dict) and CONFIG_SECTION in mine:
        return Policy.of(mine.get(CONFIG_SECTION))
    return Policy.of(data.get(CONFIG_SECTION))


def load_policy(start: Path | None = None, engine: str | None = None) -> Policy:
    """Read the policy from the project's configuration. Any failure denies.

    The one piece of I/O in the rules, kept apart from :func:`decide` so the rules stay
    testable without a filesystem. A missing file, an unreadable one, or a malformed
    table all give the default, and the default interrupts nobody.
    """
    try:
        path = find_config(start)
        if path is None:
            return Policy()
        return policy_from_config(tomllib.loads(path.read_text()), engine)
    except Exception:  # noqa: BLE001 - an unreadable policy is no permission at all
        logger.exception("event=interrupt.policy.unreadable — nobody will be woken")
        return Policy()


def decide(
    arrival: Mapping[str, Any],
    policy: Policy,
    *,
    recent: Sequence[float] = (),
    now: float,
    identity_verified: bool = True,
    adapter_ready: bool = True,
) -> Decision:
    """Decide about one arrival. Pure: same inputs, same answer, no I/O and no clock.

    ``arrival`` is the hub's event — ``id``, ``from``, ``subject``, ``published``.
    **Only ``from`` and ``id`` are read.** The subject is never consulted, and that is
    the rule this module exists to enforce: ``from`` is the hub's own attribution of the
    sender, while the subject is text the sender typed. Reading the latter would hand
    every sender a lever on the recipient's attention.

    ``identity_verified`` is whether ``from`` is worth anything on the hub this arrived
    from. On a hub that does not authenticate, the sender's name is taken from a request
    header at face value, so anyone who can reach it can send as anybody — and a trust
    list read against a name like that is decoration. The caller establishes this; the
    default is ``True`` because that is the only shape in which the parameter can be
    forgotten safely by a *test*, and the one caller that matters passes it explicitly.

    ``recent`` is the monotonic time of each interruption already allowed; anything
    outside the window is ignored, so a caller may pass a longer history safely.
    """
    sender = str(arrival.get("from") or "").strip()
    message_id = str(arrival.get("id") or "")

    if policy.wakes_for_nobody:
        return Decision(
            False,
            Reason.NOT_CONFIGURED,
            sender,
            message_id,
            "no sender is configured to interrupt this agent",
        )

    if not identity_verified:
        # Before the trust list, because on such a hub the trust list cannot mean what
        # it says. Reported as its own reason rather than as "not trusted": the fix is
        # the hub's authentication, not the recipient's configuration, and conflating
        # them would send whoever is debugging this to edit the wrong file.
        return Decision(
            False,
            Reason.IDENTITY_UNVERIFIED,
            sender,
            message_id,
            "this hub does not authenticate senders, so any name can be claimed",
        )

    if sender not in policy.wake_from:
        return Decision(False, Reason.SENDER_NOT_TRUSTED, sender, message_id)

    within = [at for at in recent if now - at < RATE_WINDOW_SECONDS]
    if len(within) >= policy.max_per_minute:
        return Decision(
            False,
            Reason.RATE_LIMITED,
            sender,
            message_id,
            f"{len(within)} in the last {int(RATE_WINDOW_SECONDS)}s "
            f"is the cap of {policy.max_per_minute}",
        )

    if not adapter_ready:
        # Checked last on purpose. Reaching here means the recipient *did* want this
        # interruption, so the log says "nothing to wake you with" rather than a denial
        # — a different problem with a different fix, in a different work package.
        return Decision(
            False,
            Reason.NO_ADAPTER,
            sender,
            message_id,
            "allowed, but no wake adapter is installed",
        )

    return Decision(True, Reason.WAKE, sender, message_id)


#: What actually interrupts a session. Owned elsewhere; here it is only a seam.
Adapter = Callable[[Mapping[str, Any]], None]


class Gatekeeper:
    """The state and the I/O around :func:`decide`: history, records, the adapter.

    One per process. Holds the times of the interruptions it has allowed, so the rate
    limit means something across arrivals, and writes a record for **every** decision —
    including the ones that did nothing, which are the ones somebody will be debugging.
    """

    def __init__(
        self,
        policy: Policy,
        *,
        adapter: Adapter | None = None,
        identity_verified: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._adapter = adapter
        # `False` by default here, where :func:`decide` defaults it to `True`, and the
        # difference is deliberate. `decide` is a function with every input in front of
        # it; this is the object a caller builds and forgets about, so a forgotten
        # argument must fail towards not interrupting anybody.
        self._identity_verified = identity_verified
        self._clock = clock
        # Never more than the cap: once that many sit inside the window every further
        # arrival is denied, so an older timestamp could not change an answer.
        self._recent: deque[float] = deque(maxlen=max(1, policy.max_per_minute))

    @property
    def policy(self) -> Policy:
        return self._policy

    @property
    def identity_verified(self) -> bool:
        return self._identity_verified

    @identity_verified.setter
    def identity_verified(self, verified: bool) -> None:
        """Settled again on every connection, because a hub's posture can change.

        A hub is restarted to change how it authenticates, and a restart drops every
        stream — so the client reconnects to what may be a differently-configured hub.
        Deciding this once at startup would leave a client that connected to a hub with
        authentication on still trusting names on the same hub with it off, until
        somebody happened to restart the agent.

        Written rather than rebuilt so the rate-limit history survives: a hub that
        restarts in a loop must not hand back a fresh allowance of interruptions each
        time it comes up.
        """
        if verified != self._identity_verified:
            logger.info(
                "event=interrupt.identity verified=%s — this hub %s authenticate "
                "senders, so a trust list %s be honoured",
                verified,
                "does" if verified else "does not",
                "can" if verified else "cannot",
            )
        self._identity_verified = verified

    def consider(self, arrival: Mapping[str, Any]) -> Decision:
        """Decide about an arrival, record it, and interrupt if that is the answer."""
        now = self._clock()
        decision = decide(
            arrival,
            self._policy,
            recent=self._recent,
            now=now,
            identity_verified=self._identity_verified,
            adapter_ready=self._adapter is not None,
        )
        logger.info("event=interrupt.decision %s", decision.as_record())
        if decision.wake:
            # Counted before the adapter runs, not after. An adapter that fails has
            # still spent the agent's attention as far as we can tell from here, and
            # over-counting caps interruptions where under-counting would uncap them.
            self._recent.append(now)
            self._interrupt(arrival)
        return decision

    def _interrupt(self, arrival: Mapping[str, Any]) -> None:
        adapter = self._adapter
        if adapter is None:  # pragma: no cover - decide() has already excluded this
            return
        try:
            adapter(arrival)
        except Exception:  # noqa: BLE001 - a failed wake must not end the stream
            logger.exception(
                "event=interrupt.adapter.failed id=%s — the mail is stored and "
                "unaffected; only the interruption was lost",
                arrival.get("id"),
            )
