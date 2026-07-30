"""The mailbox: the primitives everything else is built on.

This is the application layer. It holds no rules of its own — every decision is made by
a pure function in :mod:`agent_inbox.rules` — and it holds no storage knowledge; it
talks to a :class:`~agent_inbox.store.MessageStore`. What it does is *orchestrate*:
fetch, decide, persist.

**These method names are a public contract.** They become HTTP routes, and then MCP tool
names that agents learn from a prompt. Renaming one later is a migration, so they are
chosen to read the way the messaging rules read.

**Identity is always an argument** (ADR 0007). Every method that acts as somebody takes
``caller`` explicitly — never from configuration, a global, or ambient state. This
engine cannot ask who is really calling and does not try: proving identity is the edge's
job. Today nothing proves it at all, so **this deployment is unauthenticated** and any
caller may claim any name. Authorisation is a different matter and is already enforced,
by the pure rules, below wherever authentication will eventually sit.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_inbox import addressing, naming, rules
from agent_inbox.addressing import LOCAL
from agent_inbox.exceptions import (
    DeliversToNobody,
    NameUnavailable,
    NoSuchMessage,
    UnknownActor,
    UnknownRecipient,
)
from agent_inbox.records import ActorRecord, ObjectRecord, ReadRecord
from agent_inbox.store import MessageStore
from agent_inbox.vocabulary import ActorType

#: How many attempts to find a free generated name before giving up. The pool is around
#: 340,000 combinations, so this only matters for absurdly full mailboxes.
_NAME_ATTEMPTS = 24


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Mailbox:
    """Send, receive and read mail, over any :class:`MessageStore`.

    The clock is injected so that expiry can be tested at any date; the rules
    themselves never read it (they take a cutoff).
    """

    def __init__(
        self,
        store: MessageStore,
        *,
        hub_name: str = LOCAL,
        retention_days: int = 14,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._hub_name = hub_name
        self._retention_days = retention_days
        self._clock = clock

    async def hub_settings(self) -> dict[str, str]:
        """What the operator configured about this hub. Often empty, legitimately.

        Reaches the store so the API need not. The store stays private: the hub's own
        settings are hub state, and this is the object that owns hub state.
        """
        return await self._store.hub_settings()

    async def set_hub_setting(self, key: str, value: str | None) -> None:
        """Store one setting, or clear it when ``value`` is None."""
        await self._store.set_hub_setting(key, value)

    async def peers(self) -> dict[str, str]:
        """Origins this hub trusts. Empty until an operator adds one."""
        return await self._store.peers()

    async def add_peer(self, origin: str, added: str, note: str = "") -> None:
        await self._store.add_peer(origin, added, note)

    async def remove_peer(self, origin: str) -> None:
        await self._store.remove_peer(origin)

    async def seen_activity(self, activity_id: str) -> bool:
        return await self._store.seen_activity(activity_id)

    async def remember_activity(self, activity_id: str) -> None:
        await self._store.remember_activity(activity_id, self._now())

    @property
    def hub_name(self) -> str:
        """What this mailbox calls itself. It also always answers to ``local``."""
        return self._hub_name

    def address_of(self, name: str) -> str:
        """The address an actor is reachable at, from outside this module."""
        return str(addressing.Address(name, LOCAL))

    def _local(self, text: str) -> str:
        """Resolve an address to a local actor name, refusing what we cannot reach.

        Everything above this line speaks addresses; everything below speaks names.
        Keeping the translation in one place is what lets the rules stay hub-agnostic.
        """
        return addressing.local_name(text, self._hub_name)

    def _now(self) -> str:
        return self._clock().isoformat()

    def now(self) -> str:
        """This hub's clock, in the same form a message's ``published`` takes.

        Public because a cursor for an empty inbox has no message to anchor to and must
        still be comparable with the ones that do. Reading a different clock would let a
        bookmark drift past mail that had not arrived yet.
        """
        return self._now()

    async def _context(self) -> tuple[tuple[str, ...], dict[str, frozenset[str]]]:
        """Who exists and which groups they are in — the inputs every rule needs."""
        actors = tuple(await self._store.actors())
        return (
            tuple(a.name for a in actors),
            dict(rules.group_memberships(actors)),
        )

    # -- identity ----------------------------------------------------------

    async def join(self, requested_name: str | None = None) -> ActorRecord:
        """Join the mailbox, with a chosen name or an issued one.

        A name is *requested*, and the mailbox decides. Uniqueness is settled by the
        store's atomic claim, never by looking first and inserting after — that
        check-then-insert is exactly how two agents came to share one inbox.
        """
        now = self._now()
        if requested_name is not None:
            # naming.validate raises NameUnavailable directly — no translation layer,
            # because a rewrap that only changes the type is a place errors get lost.
            name = naming.validate(requested_name)
            actor = ActorRecord(
                name=name.value,
                actor_type=ActorType.SERVICE,
                created=now,
                last_seen=now,
            )
            if not await self._store.claim_name(actor):
                raise NameUnavailable(
                    f"{name.value!r} is taken — choose another, or join without a name "
                    "and one will be issued to you"
                )
            return actor

        for _attempt in range(_NAME_ATTEMPTS):
            candidate = naming.generate()
            actor = ActorRecord(
                name=candidate, actor_type=ActorType.SERVICE, created=now, last_seen=now
            )
            if await self._store.claim_name(actor):
                return actor
        raise NameUnavailable(  # pragma: no cover - needs a near-exhausted pool
            f"could not find a free name in {_NAME_ATTEMPTS} attempts"
        )

    async def whois(self, name: str) -> ActorRecord | None:
        """One actor's entry, or ``None``. Public — a directory is for lookups."""
        return await self._store.get_actor(name)

    async def directory(self) -> tuple[ActorRecord, ...]:
        """Everyone on the mailbox."""
        return tuple(await self._store.actors())

    async def update_profile(
        self, caller: str, profile: dict[str, object]
    ) -> ActorRecord:
        """Replace the caller's profile — the mutable half of identity (ADR 0003)."""
        actor = await self._require_actor(caller)
        updated = ActorRecord(
            name=actor.name,
            actor_type=actor.actor_type,
            profile=profile,
            created=actor.created,
            last_seen=self._now(),
        )
        await self._store.put_actor(updated)
        return updated

    async def _require_actor(self, name: str) -> ActorRecord:
        resolved = self._local(name)
        actor = await self._store.get_actor(resolved)
        if actor is None:
            raise UnknownActor(f"{name!r} has not joined this mailbox")
        return actor

    # -- sending -----------------------------------------------------------

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
        remote_to: Sequence[str] = (),
        audience: Sequence[str] = (),
    ) -> ObjectRecord:
        """Send a message. Every actor addressed receives their own copy.

        If ``in_reply_to`` names a conversation the caller cannot see, the message
        **silently starts its own thread** instead of joining. The silence is the point:
        an error would confirm which threads exist, which is what the refusal protects.
        """
        # `remote_sender` is a sender **already authorised elsewhere** and identified by
        # its actor URI — a peer whose signature verified and whose origin we trust.
        #
        # `_require_actor` does two jobs, and only one applies to such a sender.
        # *Authorisation* — is this a real actor entitled to send — was answered
        # cryptographically at the federation boundary, and asking again against a local
        # table is asking the wrong hub. *Resolution* turns an address into a local
        # name, which a remote sender has not got and must not be given (ADR 0003: the
        # identifier is a URI, and minting one here would imply a continuity we cannot
        # observe).
        #
        # Everything after this line is unchanged and must stay so: audience
        # resolution, the disclosure protections from mission 0020, and per-reader read
        # tracking all still run. That is what makes this a widened contract rather
        # than a second delivery path.
        sender = remote_sender or (await self._require_actor(caller)).name
        raw = (to,) if isinstance(to, str) else tuple(to)
        recipients = tuple(self._local(one) for one in raw)
        copies = tuple(self._local(one) for one in cc)
        all_actors, memberships = await self._context()
        self._reject_unknown_recipients(recipients + copies, all_actors, memberships)

        parent = in_reply_to
        if parent is not None:
            objects = tuple(await self._store.objects())
            if not rules.may_attach_to(
                objects, sender, parent, all_actors, memberships
            ):
                parent = None

        # Resolve the audience **now**, and store who it actually reached.
        #
        # ActivityStreams puts resolved recipients in `to`; storing the *unresolved*
        # audience was our deviation, and it was a disclosure. Membership is
        # self-declared, so an agent that added itself to a group later became
        # retroactively party to everything that group was ever sent — able to read the
        # history and to attach turns to threads rooted in it. Resolving at send time
        # means a message reaches who was there when it was sent, which is also what
        # every mail system does.
        # The sender comes out here too: `to` now means *who received this*, and you
        # never receive your own message. Read-time exclusion still happens and is
        # harmless — but a stored `to` that listed the sender would be a lie.
        # An explicit self-address delivers; being caught in your own fan-out does not.
        # See `rules.recipients_of`, which must agree with this or mail would be stored
        # as delivered and then be invisible to the only person it was for.
        reached = rules.resolve_audience(recipients, all_actors, memberships) - {sender}
        if rules.named_self(recipients, sender):
            reached |= {sender}
        also = (
            rules.resolve_audience(copies, all_actors, memberships) - {sender} - reached
        )
        if rules.named_self(copies, sender) and sender not in reached:
            also |= {sender}
        # `remote_to` is the mirror of `remote_sender`: recipients **already resolved**
        # at the federation boundary and identified by actor URI (ADR 0003). They do not
        # go through `_local`, because they have no local name and must not be given
        # one, and they are not resolved against the roster, because they are not on it.
        #
        # They are appended rather than sorted in, so the local half of `to` keeps the
        # exact ordering it has always had and nothing downstream that assumed sorted
        # local names is disturbed.
        resolved_to = tuple(sorted(reached)) + tuple(remote_to)
        resolved_cc = tuple(sorted(also))
        self._reject_undeliverable(
            recipients + copies, resolved_to + resolved_cc, memberships
        )

        obj = ObjectRecord(
            id=uuid.uuid4().hex,
            attributed_to=sender,
            to=resolved_to,
            cc=resolved_cc,
            in_reply_to=parent,
            summary=subject,
            content=body,
            published=self._now(),
            # What was typed, kept for display and provenance. AS2 has `audience` for
            # exactly this: `to` is who it went to, `audience` is who it was aimed at.
            # `audience` is what was typed; anything else is a property we do not
            # model and are required to preserve (ADR 0006).
            # `audience` is what was *typed*, and when a send has remote recipients the
            # caller passes the original addresses — otherwise the record would show
            # only the local half and the sender's own copy would misreport who they
            # addressed it to.
            document={
                "audience": list(audience or recipients + copies),
                **(document or {}),
            },
        )
        await self._store.add_object(obj)
        return obj

    @staticmethod
    def _reject_unknown_recipients(
        names: Sequence[str],
        all_actors: Sequence[str],
        memberships: dict[str, frozenset[str]],
    ) -> None:
        """Refuse a specific name nobody holds, before anything is stored.

        A message that reports success and reaches nobody is the worst outcome for an
        agent: it cannot notice the silence, and will wait for a reply that is never
        coming. So a mistyped name is an error.

        Groups are exempt. An empty group is legitimately empty — everyone may have
        left, or nobody may have joined yet — and that is not the sender's mistake.
        """
        known = set(all_actors) | set(memberships) | {rules.EVERYONE}
        missing = [name for name in names if name not in known]
        if missing:
            raise UnknownRecipient(
                f"nobody here is called {', '.join(repr(m) for m in missing)} — "
                "check the name, or call `directory` to see who has joined"
            )

    @staticmethod
    def _reject_undeliverable(
        addressed: Sequence[str],
        delivered: Sequence[str],
        memberships: dict[str, frozenset[str]],
    ) -> None:
        """Refuse a well-formed audience that reaches nobody, and say which kind it is.

        Every name here is real — a typo raised earlier. What is left is an audience
        that resolves to no one: a group everyone has left, or ``everyone`` on a mailbox
        of one. The hub used to store these and return success, which hands the caller
        an object id indistinguishable from a real delivery.

        The message names the cause, because the remedies are different: wait for
        somebody to join, versus address a group that still has members.
        """
        if delivered or not addressed:
            return
        groups = sorted({name for name in addressed if name in memberships})
        if rules.EVERYONE in addressed:
            detail = "you are the only one here, so `everyone` reaches nobody"
        elif groups:
            named = ", ".join(repr(group) for group in groups)
            detail = f"{named} has no members besides you"
        else:
            detail = "every name addressed resolves to nobody"
        raise DeliversToNobody(
            f"this would reach nobody — {detail}. Nothing was sent; "
            "call `agents` to see who has joined"
        )

    async def reply(
        self, caller: str, object_id: str, body: str, *, subject: str | None = None
    ) -> ObjectRecord:
        """Reply to a message, to its sender, on its thread.

        Replying does not require having read it first: reading is the natural
        precondition, so demanding it would make the obvious order the one that fails.
        """
        original = await self._visible_object(caller, object_id)
        return await self.send(
            caller,
            original.attributed_to,
            body,
            subject=subject or _reply_subject(original.summary),
            in_reply_to=original.id,
        )

    # -- receiving ---------------------------------------------------------

    async def peek(self, caller: str) -> tuple[ObjectRecord, ...]:
        """What is waiting, without consuming any of it."""
        me = (await self._require_actor(caller)).name
        all_actors, memberships = await self._context()
        objects = tuple(await self._store.objects())
        read_ids = await self._read_by(me, objects)
        return rules.unread(objects, me, read_ids, all_actors, memberships)

    async def unread_count(self, caller: str) -> int:
        """How much is waiting. Cheap enough for an agent to ask every turn."""
        return len(await self.peek(caller))

    async def read(self, caller: str, object_id: str) -> ObjectRecord:
        """Consume one message.

        The only call that acknowledges mail, and it acknowledges it **for this reader
        only** — another recipient's copy is untouched.
        """
        me = (await self._require_actor(caller)).name
        obj = await self._visible_object(caller, object_id)
        await self._store.mark_read(ReadRecord(obj.id, me, self._now()))
        return obj

    async def mark_read_for(self, caller: str, object_id: str) -> None:
        """Record that *caller* has dealt with a message, without consuming it.

        The marking half of :meth:`read`, separated because replying to a message is
        also dealing with it — and a reply must not re-fetch or re-consume the thing it
        is answering.

        The visibility rule is applied here too, not only by whoever calls this. A
        second caller arriving later must not find a route that marks a message the
        caller cannot see; a guard that lives only in the current caller is a guard that
        the next caller forgets.
        """
        me = (await self._require_actor(caller)).name
        obj = await self._visible_object(caller, object_id)
        await self._store.mark_read(ReadRecord(obj.id, me, self._now()))

    async def thread(self, caller: str, object_id: str) -> tuple[ObjectRecord, ...]:
        """The turns of a conversation **the caller is party to** — never all of it.

        Membership is per turn. A bystander who received an opening broadcast sees that
        broadcast and nothing that followed privately. An empty result means either "no
        such thread" or "none of it is yours", and the two are indistinguishable on
        purpose.

        **Any turn names its thread, not only the opener.** This took a thread *root*
        until 2026-07-30, and passed it straight to the filter — so asking about a reply
        matched nothing and reported `no such thread` about a thread the caller was in
        and had just read. Reported from live use by an agent that did exactly
        that; from inside the code it looked correct, and the indistinguishability
        rule made a genuine bug read as a permission boundary.

        The caller must be party to the turn they **name**, which is the same rule
        :meth:`view` already applies — one answer to "which object ids may I mention",
        used by both. Resolving the root first and filtering afterwards would have let a
        caller learn that an id they cannot see belongs to a thread they are in;
        refusing first costs nothing, because any thread you can see can be named by
        a turn you can see.
        """
        me = (await self._require_actor(caller)).name
        all_actors, memberships = await self._context()
        objects = tuple(await self._store.objects())

        named = next((obj for obj in objects if obj.id == object_id), None)
        if named is None or not rules.is_party_to(named, me, all_actors, memberships):
            return ()
        root_id = rules.thread_root(objects, object_id)
        return rules.visible_turns(objects, root_id, me, all_actors, memberships)

    async def view(self, caller: str, object_id: str) -> ObjectRecord:
        """One message the caller is party to, **without consuming it**.

        The single-message counterpart of :meth:`peek`. Useful when you need a
        message's details in order to act on it — replying, say — and consuming it as a
        side effect of looking would be a trap.
        """
        return await self._visible_object(caller, object_id)

    async def install_resident(
        self, name: str, *, profile: dict[str, object] | None = None
    ) -> ActorRecord:
        """Create a standing mailbox the hub itself owns, bypassing name reservation.

        ``admin`` and ``host`` are reserved precisely so no agent can claim them, which
        also means the ordinary :meth:`join` path cannot create them. This is the
        deliberate exception, used by policy at startup and nowhere else.

        Idempotent: if the name is already held, the existing actor is returned
        untouched, so reopening a mailbox never disturbs a resident's profile.
        """
        now = self._now()
        actor = ActorRecord(
            name=name,
            actor_type=ActorType.SERVICE,
            profile=profile or {},
            created=now,
            last_seen=now,
        )
        if await self._store.claim_name(actor):
            return actor
        existing = await self._store.get_actor(name)
        return existing if existing is not None else actor

    async def _visible_object(self, caller: str, object_id: str) -> ObjectRecord:
        """Fetch a message the caller is party to, or refuse indistinguishably."""
        me = (await self._require_actor(caller)).name
        obj = await self._store.get_object(object_id)
        if obj is None:
            raise NoSuchMessage(f"no message {object_id!r} available to you")
        all_actors, memberships = await self._context()
        if not rules.is_party_to(obj, me, all_actors, memberships):
            raise NoSuchMessage(f"no message {object_id!r} available to you")
        return obj

    async def _read_by(
        self, caller: str, objects: Iterable[ObjectRecord]
    ) -> frozenset[str]:
        reads = await self._store.reads_of([o.id for o in objects])
        return frozenset(
            object_id
            for object_id, entries in reads.items()
            if any(entry.reader == caller for entry in entries)
        )

    # -- housekeeping ------------------------------------------------------

    # -- observation ------------------------------------------------------------
    #
    # These deliberately do **not** take a caller, and deliberately do not apply the
    # party rule. They are the operator's view: someone running the hub can see what is
    # on it, which is not a loophole in the messaging model but a different question
    # being asked of the same data.
    #
    # Keeping them as separate verbs rather than a flag on `peek` is the point. An
    # operator's authority is visible in the method name and in the route, so it can be
    # authorised in one place when authentication arrives — rather than being smuggled
    # in by a console that impersonates whoever it wants to look at, which is what this
    # replaces (M2 FR-010).
    #
    # **None of them consumes.** Watching an agent's mail must never mark it read, or
    # the operator steals what they were only trying to look at.

    async def observe_mailbox(self, name: str) -> tuple[ObjectRecord, ...]:
        """Everything addressed to one agent, read or not, newest last."""
        all_actors, memberships = await self._context()
        objects = tuple(await self._store.objects())
        return tuple(
            sorted(
                (
                    obj
                    for obj in objects
                    if name in rules.recipients_of(obj, all_actors, memberships)
                ),
                key=lambda obj: obj.published,
            )
        )

    async def observe_object(self, object_id: str) -> ObjectRecord | None:
        """One message, whoever it belongs to."""
        return await self._store.get_object(object_id)

    async def observe_thread(self, object_id: str) -> tuple[ObjectRecord, ...]:
        """A whole conversation, including turns no single participant can see.

        This is the one that most obviously is not an agent's view: `thread` shows a
        caller their own turns, and side conversations between others stay private.
        The operator sees the conversation entire.
        """
        objects = tuple(await self._store.objects())
        root = rules.thread_root(objects, object_id)
        members = rules.thread_members(objects, root)
        return tuple(sorted(members, key=lambda obj: obj.published))

    async def observe_reads(self, object_id: str) -> tuple[str, ...]:
        """Who has consumed a given message. Useful for "did they get it?"."""
        reads = await self._store.reads_of([object_id])
        return tuple(sorted(record.reader for record in reads.get(object_id, ())))

    async def survey(self, *, since: str = "") -> dict[str, Any]:
        """Traffic, in aggregate. One pass over the store, several answers.

        Gathered together rather than as four routes because a dashboard wants all of
        it at once, and four round trips over the same data would be four chances for
        the numbers to disagree with each other.
        """
        actors = tuple(await self._store.actors())
        objects = tuple(await self._store.objects())
        recent = tuple(obj for obj in objects if obj.published >= since)
        return {
            "actors": len(actors),
            "messages": len(objects),
            "messages_since": len(recent),
            "threads": len({rules.thread_root(objects, obj.id) for obj in objects}),
            "per_day": rules.traffic_by_day(objects, since=since),
            "flow": rules.flow_edges(objects, since=since),
            "busiest": tuple(
                sorted(
                    (
                        (a.name, sum(1 for o in objects if o.attributed_to == a.name))
                        for a in actors
                    ),
                    key=lambda pair: (-pair[1], pair[0]),
                )
            ),
        }

    @property
    def retention_days(self) -> int:
        """How long a conversation may stay quiet before it expires. 0 disables it."""
        return self._retention_days

    async def expire(self) -> int:
        """Remove conversations that have gone quiet. Returns messages removed.

        Judged per thread by its most recent activity, and removed whole. Expiring
        message by message once deleted the opening of a live conversation and left the
        replies — a fragment that reads as complete is worse than no fragment at all.
        """
        return sum(thread.messages for thread in await self.purge())

    async def purge(self) -> tuple[rules.ExpiringThread, ...]:
        """Remove idle conversations and say which ones went.

        One pass, not two: an earlier version previewed and then expired, which decided
        what to delete twice and could — on a busy hub — decide differently the second
        time. Reporting what was actually removed is also the only honest thing to log.
        """
        doomed = await self.expire_preview()
        ids = frozenset(ident for thread in doomed for ident in thread.ids)
        if ids:
            await self._store.remove_objects(ids)
        return doomed

    async def expire_preview(self) -> tuple[rules.ExpiringThread, ...]:
        """What :meth:`expire` would remove, without removing it.

        The same computation the real purge uses — `expire` is this plus the deletion —
        so a dry run and a purge cannot disagree about what dies. Two functions each
        working out their own answer would agree right up until they did not, and the
        moment they disagreed would be the moment someone had trusted the preview.

        There are no tombstones: expiry is real removal, and afterwards a purged thread
        is indistinguishable from one that never existed. This is the only chance
        anybody gets to look first.
        """
        if self._retention_days <= 0:
            return ()
        cutoff = (self._clock() - timedelta(days=self._retention_days)).isoformat()
        objects = tuple(await self._store.objects())
        return rules.expiring_threads(objects, cutoff)


def _reply_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"
