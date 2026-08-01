"""Retrying a delivery to a peer that is merely asleep.

Step 6 delivered once. A peer that was suspended, restarting or briefly offline turned
an ordinary message into a failure — reported honestly, and gone. That was shipped
knowing it: federation between two hubs that are both up is worth having on its own.

What changed is that we now run a peer that is asleep most of the time: the public
demo scales to zero, so the *ordinary* case for a message to it is a hub coming up.

**The distinction this module exists to draw** is between a peer that could not be
reached and a delivery we refused to make. They arrive as exceptions either way, and
treating them alike would mean the hub arguing with its own configuration for minutes
— and would make withdrawing trust from a peer take a retry window to bite instead of
applying at the very next attempt.

**The rule this module must not break:** authorization is re-derived on every attempt
and never carried from queue time. That is the finding from federation's first outside
review. It survives here for a structural reason rather than a remembered one — every
retry re-calls the wrapped collaborator's `deliver`, which reads settings and peers
itself, immediately before the request. Nothing in this module decides whether a send is
allowed, and nothing in it stores an answer to that question.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_inbox.delivery import RemoteDelivery
from agent_inbox.outbound import DeliveryRefused
from agent_inbox.peers import PeerUnreachable
from agent_inbox.records import ObjectRecord

logger = logging.getLogger(__name__)

#: Waits between attempts, after the inline one. Five retries, so six attempts in all.
#:
#: Totals 3m10s — comfortably under the five-minute ceiling, which is a bound the
#: schedule must fit under rather than a figure to round towards. A window longer than
#: the queue's own honest lifetime would be a promise we cannot keep: this queue is held
#: in memory and this hub is redeployed on every release.
BACKOFF: tuple[float, ...] = (2.0, 8.0, 30.0, 60.0, 90.0)


class Queued(Exception):
    """Not a failure: the message is accepted and will be tried again.

    Raised out of `deliver` so the caller can mint a `queued` receipt rather than a
    failed one. An exception only because `deliver` has no other way to say "neither
    delivered nor failed" — the Protocol returns `None` on success.
    """

    def __init__(self, recipient: str) -> None:
        super().__init__(f"queued for retry: {recipient}")
        self.recipient = recipient


def is_retryable(error: BaseException) -> bool:
    """Whether trying again could plausibly give a different answer.

    **An allow-list, deliberately.** Anything unrecognised is terminal: retrying
    something we do not understand, against somebody else's server, five more times, is
    the wrong default — and an exception we never thought about is likelier to be a bug
    in us than weather at the far end.

    - `DeliveryRefused` — *our* decision. Federation is off, or the peer is not trusted.
      Never retryable: the answer cannot change by asking ourselves again, and treating
      it as weather would delay a withdrawal of trust by a whole retry window.
    - `PeerUnreachable` with no status — nobody answered. Connection refused, DNS
      failure, timeout. **This is the case the queue exists for.**
    - `PeerUnreachable` with a 5xx — the peer is up but broken, which may pass.
    - `PeerUnreachable` with a 4xx — the peer considered the message and rejected it.
      Asking again for five minutes will not change its mind.
    """
    if isinstance(error, DeliveryRefused):
        return False
    if isinstance(error, PeerUnreachable):
        status = getattr(error, "status", None)
        if status is None:
            return True
        return 500 <= status < 600
    return False


@dataclass
class _Waiting:
    """One message still trying to reach one recipient."""

    resolved: object
    record: ObjectRecord
    recipient: str
    attempts: int = 1  # the inline attempt already happened


@dataclass
class RetryingDelivery:
    """A `RemoteDelivery` that keeps trying, wrapped around one that does not.

    Satisfies the same Protocol as what it wraps, so `House` needs no knowledge that
    retrying exists — the reason this is a wrapper rather than a change to
    `FederatedDelivery`.
    """

    inner: RemoteDelivery
    #: Injected so tests can assert the *schedule* without elapsing it. A bug that
    #: retried six times immediately would satisfy a count-only test while hammering a
    #: peer that is already struggling.
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    backoff: tuple[float, ...] = BACKOFF
    _waiting: dict[asyncio.Task[None], _Waiting] = field(default_factory=dict)

    async def resolve(self, address: str) -> object:
        return await self.inner.resolve(address)

    def actor_uri(self, resolved: object) -> str:
        return self.inner.actor_uri(resolved)

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        """One attempt, inline. Then either done, refused, or queued.

        The first attempt is inline so a caller waits for **one** attempt and never for
        the window — an agent blocked for minutes inside a single tool call would be a
        worse failure than the one being fixed.
        """
        recipient = self.actor_uri(resolved)
        try:
            await self.inner.deliver(resolved, record)
        except Exception as first:
            if not is_retryable(first):
                raise
            self._enqueue(_Waiting(resolved, record, recipient))
            raise Queued(recipient) from first

    def _enqueue(self, waiting: _Waiting) -> None:
        """One task per waiting message.

        Per-peer independence then costs nothing to arrange: two peers cannot block each
        other because they were never sharing anything.

        What it permits is worth naming — ten messages waiting on one sleeping peer make
        ten concurrent attempts. That was chosen deliberately over a per-peer worker;
        do not add a lock here without changing the requirement that allows it.
        """
        task = asyncio.create_task(self._keep_trying(waiting))
        self._waiting[task] = waiting
        task.add_done_callback(self._waiting.pop)

    async def _keep_trying(self, waiting: _Waiting) -> None:
        for wait in self.backoff:
            await self.sleep(wait)
            waiting.attempts += 1
            try:
                # Straight back through the collaborator, carrying no decision with us.
                # It re-reads settings and peers itself, so a peer that lost our trust
                # while this message waited is refused by code we never touch.
                await self.inner.deliver(waiting.resolved, waiting.record)
            except Exception as again:
                if not is_retryable(again):
                    self._gave_up(waiting, f"refused: {again}")
                    return
                continue
            logger.info(
                "delivered %s to %s on attempt %d",
                waiting.record.id,
                waiting.recipient,
                waiting.attempts,
            )
            return
        self._gave_up(waiting, "unreachable for the whole retry window")

    def _gave_up(self, waiting: _Waiting, why: str) -> None:
        """Retries stop, and say so.

        An unbounded queue is a slow leak that presents as working, and a sender told
        `queued` is owed an ending either way.
        """
        logger.warning(
            "gave up delivering %s to %s after %d attempt(s) — %s",
            waiting.record.id,
            waiting.recipient,
            waiting.attempts,
            why,
        )

    async def aclose(self) -> None:
        """Stop, and fail whatever is still waiting rather than letting it vanish.

        The queue is held in memory, which is acceptable **only** because the volatility
        is disclosed rather than discovered. A process that exits still holding messages
        it called `queued` has lied; this is where that is put right.
        """
        for task, waiting in list(self._waiting.items()):
            task.cancel()
            self._gave_up(waiting, "this hub stopped while the message was waiting")
        pending = list(self._waiting)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._waiting.clear()

    def __len__(self) -> int:
        """How many messages are waiting. For tests and for a future status surface."""
        return len(self._waiting)


def wrap(inner: RemoteDelivery | None, **kwargs: Any) -> RetryingDelivery | None:
    """Add retrying to a delivery collaborator, if there is one.

    `None` passes through: a house built without federation must keep refusing remote
    recipients exactly as it did. Retrying is not a reason to soften that — a send that
    succeeds and reaches nobody is still the worst failure shape available.
    """
    if inner is None:
        return None
    return RetryingDelivery(inner, **kwargs)
