"""The house: a mailbox, its standing residents, and its house rules.

:class:`~agent_inbox.mailbox.Mailbox` knows what a mailbox *can* do. A house knows
what this one *always* does — who lives here whether or not anyone is home, what gets
refused, what gets logged.

Everything above this line should talk to a house, not a bare mailbox. The API in M2
and the clients in M3 get their policies for free by doing so, and a deployment adds a
rule of its own without the engine changing at all.

The wrapping is deliberately thin and mechanical: **check, act, record.** A house makes
no messaging decisions — those belong to the rules — and it never silently alters an
action. It permits it, refuses it, or watches it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from types import TracebackType
from typing import Any, Self

from agent_inbox import addressing, rules
from agent_inbox.delivery import Receipt, RemoteDelivery, Sent
from agent_inbox.exceptions import RemoteMailbox
from agent_inbox.mailbox import Mailbox, _reply_subject
from agent_inbox.policy import Attempt, Outcome, Policy, default_policies
from agent_inbox.records import ActorRecord, ObjectRecord

logger = logging.getLogger(__name__)


class House:
    """A mailbox with its house rules applied.

    Use it as an async context manager, which is when standing invariants are
    established::

        async with House(mailbox) as house:
            await house.send("rosemary_nasrin", "admin", "something is broken")
    """

    def __init__(
        self,
        mailbox: Mailbox,
        policies: Sequence[Policy] | None = None,
        *,
        deliver: RemoteDelivery | None = None,
    ) -> None:
        self._mailbox = mailbox
        self._policies = tuple(policies if policies is not None else default_policies())
        # Injected, exactly as policies are. A house without one **refuses** remote
        # recipients rather than dropping them — see `send`.
        self._deliver = deliver

    @property
    def mailbox(self) -> Mailbox:
        """The mailbox underneath, for operations that carry no policy."""
        return self._mailbox

    @property
    def policies(self) -> tuple[Policy, ...]:
        return self._policies

    async def open(self) -> Self:
        """Establish standing invariants. Idempotent — reopening changes nothing."""
        for policy in self._policies:
            await policy.on_open(self._mailbox)
        return self

    async def __aenter__(self) -> Self:
        return await self.open()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    # -- the pipeline ------------------------------------------------------

    async def _check(self, attempt: Attempt) -> None:
        for policy in self._policies:
            await policy.check(attempt, self._mailbox)

    async def _record(self, outcome: Outcome) -> None:
        """Tell every observer, and never let one break the mailbox.

        An observer that raises has failed at its own job, not at the mailbox's. The
        alternative — letting a broken audit logger fail a message that was already
        delivered — would make the mailbox less reliable than having no logging.
        """
        for policy in self._policies:
            try:
                await policy.record(outcome, self._mailbox)
            except Exception:  # noqa: BLE001 - a process boundary for observers
                logger.exception(
                    "policy %r failed while observing; the mailbox is unaffected",
                    getattr(policy, "name", policy),
                )

    # -- policed operations ------------------------------------------------

    async def send(
        self,
        caller: str,
        to: str | Sequence[str],
        body: str,
        *,
        subject: str | None = None,
        cc: Sequence[str] = (),
        in_reply_to: str | None = None,
        document: dict[str, object] | None = None,
        remote_sender: str | None = None,
    ) -> Sent:
        """Send a message, to this hub and to others.

        **Both halves, one entry point.** The alternative — letting the API split and
        call this for the local half only — would make `send` mean *send locally*, so
        any caller not going through the API would silently drop remote recipients.
        That is the failure shape this project keeps finding, so it is closed by
        construction: a house with no delivery collaborator refuses a remote recipient.

        Order is resolve, store, deliver. Resolution comes first because a remote
        recipient is stored by its **actor URI** (ADR 0003) and that URI is what
        resolution produces. Storing comes before delivery because losing the sender's
        own message when somebody else's server is down is the worst available trade
        (FR-7).
        """
        recipients = (to,) if isinstance(to, str) else tuple(to)
        attempt = Attempt(
            action="send",
            actor=caller,
            recipients=recipients + tuple(cc),
            subject=subject,
            body=body,
        )
        await self._check(attempt)

        hub = self._mailbox.hub_name
        local_to, remote_to = addressing.split_recipients(recipients, hub)
        local_cc, remote_cc = addressing.split_recipients(tuple(cc), hub)
        remote = remote_to + remote_cc

        if remote and self._deliver is None:
            # Refused, not dropped. This house cannot reach another hub, and delivering
            # the local half while discarding the rest would look like success.
            # `RemoteMailbox`, not a new code. Its docstring has anticipated this
            # exact moment since before federation existed: "this deployment does not
            # federate, so there is nowhere to send it *yet*". A second code for the
            # same condition would be vocabulary churn for downstream callers.
            refusal = RemoteMailbox(
                "this hub cannot send to other hubs, so it will not pretend to: "
                + ", ".join(remote)
            )
            await self._record(Outcome(attempt, ok=False, error=refusal))
            raise refusal

        # Resolve first. A recipient we cannot resolve is not stored as having received
        # anything — it gets a failed receipt instead, and `audience` still records what
        # the sender actually typed.
        resolved: list[tuple[str, object]] = []
        receipts: list[Receipt] = []
        for address in remote:
            assert self._deliver is not None
            try:
                resolved.append((address, await self._deliver.resolve(address)))
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                receipts.append(Receipt(address, delivered=False, detail=str(exc)))

        try:
            record = await self._mailbox.send(
                caller,
                local_to if remote else to,
                body,
                subject=subject,
                cc=local_cc if remote else cc,
                in_reply_to=in_reply_to,
                document=document,
                remote_sender=remote_sender,
                remote_to=tuple(
                    self._deliver.actor_uri(who)
                    for _, who in resolved
                    if self._deliver is not None
                ),
                audience=recipients + tuple(cc) if remote else (),
            )
        except Exception as exc:
            await self._record(Outcome(attempt, ok=False, error=exc))
            raise

        # Stored. From here nothing can lose the sender's own copy.
        for address, who in resolved:
            assert self._deliver is not None
            try:
                await self._deliver.deliver(who, record)
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                receipts.append(Receipt(address, delivered=False, detail=str(exc)))
            else:
                receipts.append(Receipt(address, delivered=True))

        # What the *local* half reached, computed here rather than read back off
        # `record.to`, which since step 6 also holds remote actor URIs.
        remote_uris = {uri for uri in record.to if "://" in uri}
        sent = Sent(
            record=record,
            receipts=tuple(receipts),
            local_recipients=tuple(
                who for who in record.to + record.cc if who not in remote_uris
            ),
        )
        await self._record(
            Outcome(
                attempt,
                ok=not sent.reached_nobody,
                detail={
                    "id": record.id,
                    **(
                        {"remote": [(r.recipient, r.state) for r in sent.receipts]}
                        if sent.receipts
                        else {}
                    ),
                },
            )
        )
        return sent

    async def read(self, caller: str, object_id: str) -> ObjectRecord:
        attempt = Attempt(action="read", actor=caller, detail={"id": object_id})
        await self._check(attempt)
        try:
            got = await self._mailbox.read(caller, object_id)
        except Exception as exc:
            # The signal a probe detector wants: reaching for something not yours.
            await self._record(
                Outcome(attempt, ok=False, error=exc, detail={"not_yours": True})
            )
            raise
        await self._record(Outcome(attempt, ok=True))
        return got

    async def join(self, requested_name: str | None = None) -> ActorRecord:
        attempt = Attempt(action="join", actor=requested_name or "<unnamed>")
        await self._check(attempt)
        try:
            actor = await self._mailbox.join(requested_name)
        except Exception as exc:
            await self._record(Outcome(attempt, ok=False, error=exc))
            raise
        await self._record(Outcome(attempt, ok=True, detail={"name": actor.name}))
        return actor

    async def reply(
        self, caller: str, object_id: str, body: str, *, subject: str | None = None
    ) -> Sent:
        try:
            original = await self._mailbox.view(caller, object_id)
        except Exception as exc:
            # Replying to something not yours is a probe too, and failed here before
            # any observer saw it.
            await self._record(
                Outcome(
                    Attempt(action="reply", actor=caller, detail={"id": object_id}),
                    ok=False,
                    error=exc,
                    detail={"not_yours": True},
                )
            )
            raise
        return await self.send(
            caller,
            original.attributed_to,
            body,
            # Without this the `Re:` prefix was lost whenever a reply went through the
            # house rather than the mailbox directly.
            subject=subject or _reply_subject(original.summary),
            in_reply_to=original.id,
        )

    # -- unpoliced pass-through -------------------------------------------
    #
    # Reading state changes nothing and refuses nothing, so there is no policy moment
    # to insert. Passing these through keeps the house from becoming a second, partial
    # copy of the mailbox's surface.

    async def view(self, caller: str, object_id: str) -> ObjectRecord:
        """One message, without consuming it. Goes through the house like everything
        else — reading it changes nothing, but a deployment's observers should still
        see that it happened."""
        attempt = Attempt(action="view", actor=caller, detail={"id": object_id})
        try:
            got = await self._mailbox.view(caller, object_id)
        except Exception as exc:
            # A refused view is the same probe signal as a refused read, and was
            # invisible to observers because the exception escaped before recording.
            await self._record(
                Outcome(attempt, ok=False, error=exc, detail={"not_yours": True})
            )
            raise
        await self._record(Outcome(attempt, ok=True))
        return got

    async def peek(self, caller: str) -> tuple[ObjectRecord, ...]:
        return await self._mailbox.peek(caller)

    async def unread_count(self, caller: str) -> int:
        return await self._mailbox.unread_count(caller)

    async def thread(self, caller: str, root_id: str) -> tuple[ObjectRecord, ...]:
        return await self._mailbox.thread(caller, root_id)

    async def whois(self, name: str) -> ActorRecord | None:
        return await self._mailbox.whois(name)

    async def directory(self) -> tuple[ActorRecord, ...]:
        return await self._mailbox.directory()

    async def update_profile(
        self, caller: str, profile: dict[str, object]
    ) -> ActorRecord:
        return await self._mailbox.update_profile(caller, profile)

    async def expire(self) -> int:
        return await self._mailbox.expire()

    async def expire_preview(self) -> tuple[rules.ExpiringThread, ...]:
        """What a purge would remove. Reads only; deletes nothing."""
        return await self._mailbox.expire_preview()

    async def purge(self) -> tuple[rules.ExpiringThread, ...]:
        """Remove idle conversations, and report which ones went."""
        return await self._mailbox.purge()

    # -- observation -------------------------------------------------------
    #
    # The operator's view, passed through unfiltered on purpose. Policy does not get a
    # veto here: a rule that could hide traffic from whoever is running the hub would
    # make the audit log unauditable, and the first thing anyone would want to inspect
    # after a policy misfired is exactly what the policy touched.

    async def observe_mailbox(self, name: str) -> tuple[ObjectRecord, ...]:
        return await self._mailbox.observe_mailbox(name)

    async def observe_object(self, object_id: str) -> ObjectRecord | None:
        return await self._mailbox.observe_object(object_id)

    async def observe_thread(self, object_id: str) -> tuple[ObjectRecord, ...]:
        return await self._mailbox.observe_thread(object_id)

    async def observe_reads(self, object_id: str) -> tuple[str, ...]:
        return await self._mailbox.observe_reads(object_id)

    async def survey(self, *, since: str = "") -> dict[str, Any]:
        return await self._mailbox.survey(since=since)
