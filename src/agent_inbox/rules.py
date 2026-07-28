"""The messaging rules, as pure functions.

Every rule in ``doc/messaging-rules.md`` lives here, and every one of them is a
function from records to a decision. Nothing in this module touches storage, the clock,
the network or any global state — give it lists and it gives you answers.

That is not tidiness for its own sake. These rules are where the costly mistakes have
been: a thread-visibility bug leaked private mail in production, and expiry once deleted
live conversations. Rules that are pure can be tested exhaustively with literals, and
reviewed by reading, without a database in sight.

The scenario numbers refer to ``doc/messaging-rules.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NamedTuple

from agent_inbox.records import ActorRecord, ObjectRecord

#: Reserved audience meaning every actor on this mailbox (scenario 6).
EVERYONE = "everyone"


# ---------------------------------------------------------------- membership


def group_memberships(actors: Iterable[ActorRecord]) -> Mapping[str, frozenset[str]]:
    """Group name -> member names, derived from profiles.

    Membership is **computed from what actors say about themselves**, never parsed out
    of a name. That is what lets identity stay opaque (ADR 0003) while groups remain
    addressable: an actor's ``profile["groups"]`` lists the groups it belongs to.
    """
    members: dict[str, set[str]] = {}
    for actor in actors:
        if actor.is_group:
            members.setdefault(actor.name, set())
        for group in actor.profile.get("groups", ()) or ():
            members.setdefault(str(group), set()).add(actor.name)
    return {group: frozenset(names) for group, names in members.items()}


def resolve_audience(
    names: Iterable[str],
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    """Expand addressed names into the actors that actually receive a copy.

    Individuals resolve to themselves, groups to their members, and ``everyone`` to the
    whole mailbox. An unknown name resolves to nothing rather than raising: addressing
    is a *routing* question, and a message to nobody is simply delivered to nobody.
    """
    actors = frozenset(all_actors)
    resolved: set[str] = set()
    for name in names:
        if name == EVERYONE:
            resolved |= actors
        elif name in memberships:
            resolved |= memberships[name]
        elif name in actors:
            resolved.add(name)
    return frozenset(resolved)


# ------------------------------------------------------------------ delivery


def recipients_of(
    obj: ObjectRecord,
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    """Who receives a copy of ``obj`` — everyone addressed, **except its sender**.

    Self-exclusion is scenario 6: being handed back what you just said costs a turn and
    teaches nothing. It applies to fan-out and direct mail alike, so an agent that
    addresses a group it belongs to is not its own recipient.

    **Unless it named itself.** Writing your own name is a deliberate act, not the
    accident of being inside your own fan-out, and it has real uses — a note that
    survives the session, or the stimulus for a test that needs mail to actually
    arrive. So an explicit self-address delivers, while being swept into a group or
    ``everyone`` still does not. The distinction is the *typed* audience, which is why
    the unresolved names are kept (ADR 0006).
    """
    delivered = resolve_audience(obj.audience, all_actors, memberships) - {
        obj.attributed_to
    }
    if named_self(obj.audience, obj.attributed_to):
        delivered |= {obj.attributed_to}
    return delivered


def named_self(audience: Iterable[str], sender: str) -> bool:
    """Whether ``sender`` wrote its own name, rather than landing in its own fan-out."""
    return sender in frozenset(audience)


def delivers_to(
    obj: ObjectRecord,
    reader: str,
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> bool:
    """Whether ``obj`` was routed to ``reader``."""
    return reader in recipients_of(obj, all_actors, memberships)


def is_party_to(
    obj: ObjectRecord,
    actor: str,
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> bool:
    """Whether ``actor`` sent ``obj`` or received it.

    This is the unit of thread membership. It is deliberately about **one message**,
    never about a conversation — see :func:`visible_turns`.
    """
    return obj.attributed_to == actor or delivers_to(
        obj, actor, all_actors, memberships
    )


def unread(
    objects: Iterable[ObjectRecord],
    reader: str,
    read_object_ids: Iterable[str],
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> tuple[ObjectRecord, ...]:
    """What is waiting for ``reader`` (scenario 4).

    Peeking is a pure question about state; nothing here consumes anything.
    """
    already = frozenset(read_object_ids)
    return tuple(
        obj
        for obj in objects
        if obj.id not in already and delivers_to(obj, reader, all_actors, memberships)
    )


# ------------------------------------------------------------------ threading


def thread_roots(objects: Iterable[ObjectRecord]) -> dict[str, str]:
    """Every message's thread root, in one pass.

    :func:`thread_root` answers for one message and rebuilds its index each time it is
    asked, which is fine for one lookup and quadratic for a whole store: expiry called
    it twice per message, so a 10,000-message purge rebuilt a 10,000-entry index 20,000
    times and took 4.5 seconds against a 250 ms budget.

    The walk is the same walk — up ``inReplyTo``, stopping at a parent that is absent or
    outside this set — but each answer is remembered, so a chain is climbed once however
    many messages hang off it. Cycles terminate on the visited set, as before: they
    cannot arise from correct use, but a corrupt store could produce one and a purge
    that spins is worse than a purge that is wrong.
    """
    by_id = {obj.id: obj for obj in objects}
    roots: dict[str, str] = {}
    for obj in by_id.values():
        chain: list[str] = []
        seen: set[str] = set()
        current = obj.id
        while current not in roots and current not in seen:
            seen.add(current)
            chain.append(current)
            node = by_id.get(current)
            if (
                node is None
                or node.in_reply_to is None
                or node.in_reply_to not in by_id
            ):
                break
            current = node.in_reply_to
        root = roots.get(current, current)
        for member in chain:
            roots[member] = root
    return roots


def thread_root(objects: Iterable[ObjectRecord], object_id: str) -> str:
    """Follow ``inReplyTo`` up to the conversation's first message (scenario 5).

    Cycles cannot arise from correct use, but a corrupt store or a malicious peer could
    produce one, so the walk is bounded by what it has already seen rather than trusting
    the data to be acyclic.
    """
    by_id = {obj.id: obj for obj in objects}
    seen: set[str] = set()
    current = object_id
    while current not in seen:
        seen.add(current)
        obj = by_id.get(current)
        if obj is None or obj.in_reply_to is None or obj.in_reply_to not in by_id:
            return current
        current = obj.in_reply_to
    return current


def thread_members(
    objects: Iterable[ObjectRecord], root_id: str
) -> tuple[ObjectRecord, ...]:
    """Every message in the conversation rooted at ``root_id``, oldest first.

    The **whole** conversation, regardless of who may see it — this is the raw shape,
    used by expiry. Anything agent-facing must go through :func:`visible_turns`.
    """
    objects = tuple(objects)
    return tuple(obj for obj in objects if thread_root(objects, obj.id) == root_id)


def visible_turns(
    objects: Iterable[ObjectRecord],
    root_id: str,
    viewer: str,
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> tuple[ObjectRecord, ...]:
    """The turns of a thread that ``viewer`` is party to — never the whole thread.

    **Scenario 7, and the most important rule here.** Membership is per turn, not per
    thread: a bystander who received an opening broadcast sees that broadcast and
    nothing that followed privately.

    The previous implementation asked "am I party to *any* message in this thread?" and
    unlocked *all* of them. That leaked private replies to every recipient of the
    opening message, in production, with no malice required. Hence a filter rather than
    a gate.

    An empty result is returned for both "no such thread" and "none of it is yours",
    because distinguishing them tells an outsider which threads exist.
    """
    return tuple(
        obj
        for obj in thread_members(objects, root_id)
        if is_party_to(obj, viewer, all_actors, memberships)
    )


def may_attach_to(
    objects: Iterable[ObjectRecord],
    sender: str,
    parent_id: str | None,
    all_actors: Iterable[str],
    memberships: Mapping[str, frozenset[str]],
) -> bool:
    """Whether ``sender`` may reply to ``parent_id`` (scenario 8).

    Attaching to a conversation you cannot see is refused. It discloses nothing on its
    own — :func:`visible_turns` already filters — but it lets an outsider place a turn
    inside someone else's conversation, which reads as forgery to the participants.

    A caller that gets ``False`` should **start a new thread silently**, not raise: an
    error would confirm which thread ids exist, which is the thing being protected.

    A parent that does not exist is refused too, and that is the point. Allowing it
    made the answer an **existence oracle**: a forbidden parent came back cleared,
    while a nonexistent one was echoed, so a caller could tell "real but not yours"
    from "no such thing" by reading its own successful response. Both now clear, which
    is also plainly correct — you cannot reply to something that is not there.
    """
    if parent_id is None:
        return True
    parent = next((obj for obj in objects if obj.id == parent_id), None)
    if parent is None:
        return False
    return is_party_to(parent, sender, all_actors, memberships)


# -------------------------------------------------------------------- expiry


def expired_object_ids(objects: Iterable[ObjectRecord], cutoff: str) -> frozenset[str]:
    """Objects to delete: every message of every **fully idle** conversation.

    Scenario 9. Expiry is judged per *thread*, by its most recent activity, and removes
    the thread whole.

    Per-message expiry was a real bug (mission 0016): it deleted the opening message of
    a live conversation and left the replies, producing a fragment that reads as
    complete. A partial thread is worse than no thread, because nothing signals that
    anything is missing.

    ``cutoff`` is passed in rather than read from a clock, so this stays pure and
    testable at any date.
    """
    return frozenset(
        ident for doomed in expiring_threads(objects, cutoff) for ident in doomed.ids
    )


class ExpiringThread(NamedTuple):
    """One conversation that has gone quiet, described rather than deleted.

    What a dry run reports. Per thread and not per message, because the decision is per
    thread: nobody can look at forty message ids and say whether the verdict was right,
    but "this conversation, idle since 3 July, 14 messages" is something an operator can
    disagree with.
    """

    root: str
    subject: str
    last_published: str
    messages: int
    ids: tuple[str, ...]


def expiring_threads(
    objects: Iterable[ObjectRecord], cutoff: str
) -> tuple[ExpiringThread, ...]:
    """Every fully idle conversation, oldest last activity first.

    The single place that decides what expiry would remove. :func:`expired_object_ids`
    is this function with the descriptions thrown away, so a dry run and a real purge
    can never disagree about what dies — which they could, and eventually would, if each
    computed its own answer.
    """
    objects = tuple(objects)
    if not objects:
        return ()

    roots = thread_roots(objects)
    latest: dict[str, str] = {}
    for obj in objects:
        root = roots[obj.id]
        latest[root] = max(latest.get(root, ""), obj.published)

    # `<` and not `<=`: a thread whose last word landed exactly on the cutoff is kept.
    # Expiry errs towards keeping mail, here as everywhere.
    dead = {root for root, last in latest.items() if last < cutoff}
    if not dead:
        return ()

    members: dict[str, list[ObjectRecord]] = {}
    for obj in objects:
        if (root := roots[obj.id]) in dead:
            members.setdefault(root, []).append(obj)

    doomed = []
    for root, turns in members.items():
        ordered = sorted(turns, key=lambda o: o.published)
        opener = next((o for o in ordered if o.id == root), ordered[0])
        doomed.append(
            ExpiringThread(
                root=root,
                subject=opener.summary or "(no subject)",
                last_published=latest[root],
                messages=len(ordered),
                ids=tuple(o.id for o in ordered),
            )
        )
    return tuple(sorted(doomed, key=lambda t: t.last_published))


def traffic_by_day(
    objects: Iterable[ObjectRecord], *, since: str = ""
) -> tuple[tuple[str, int], ...]:
    """How many messages were sent on each day, oldest first.

    Days with no traffic are absent rather than zero: this counts what happened, and
    filling the gaps is a presentation decision that belongs to whatever draws the
    chart, not to the count.

    ``since`` is an ISO timestamp passed in rather than read from a clock, so this
    stays pure — the same objects always give the same answer.
    """
    tally: dict[str, int] = {}
    for obj in objects:
        if obj.published and obj.published >= since:
            tally[obj.published[:10]] = tally.get(obj.published[:10], 0) + 1
    return tuple(sorted(tally.items()))


def flow_edges(
    objects: Iterable[ObjectRecord], *, since: str = ""
) -> tuple[tuple[str, str, int], ...]:
    """Who wrote to whom, and how often — as ``(from, to, count)``, busiest first.

    Counted per *recipient*, so one message to three agents is three edges. That is
    the honest reading of a fan-out: the sender addressed three mailboxes, and a graph
    that drew one edge would hide two of them.

    ``cc`` counts the same as ``to``. From the point of view of who is talking to whom
    the distinction does not survive: both delivered.
    """
    tally: dict[tuple[str, str], int] = {}
    for obj in objects:
        if not obj.published or obj.published < since:
            continue
        for recipient in (*obj.to, *obj.cc):
            if recipient == obj.attributed_to:
                continue  # A copy of your own broadcast is not correspondence.
            key = (obj.attributed_to, recipient)
            tally[key] = tally.get(key, 0) + 1
    ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple((frm, to, count) for (frm, to), count in ordered)


def correspondents(
    objects: Iterable[ObjectRecord], name: str
) -> tuple[tuple[str, int], ...]:
    """Everyone who has exchanged messages with ``name``, busiest first.

    Both directions count as one relationship. "Who does this agent work with" is not
    a question about who spoke first.
    """
    tally: dict[str, int] = {}
    for frm, to, count in flow_edges(objects):
        if frm == name:
            tally[to] = tally.get(to, 0) + count
        elif to == name:
            tally[frm] = tally.get(frm, 0) + count
    return tuple(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))
