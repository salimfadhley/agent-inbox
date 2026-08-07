"""A reply must not name a parent its reader cannot see (issue #45).

The refusals around threads were all written so that "real but not yours" and "no such
thing" clear identically — `may_attach_to` says so in its own docstring, and it was
*changed* to make it true. One place still told them apart, and it did so by accident:
a reply carried its parent's id to whoever received the reply, party to the parent or
not. **The id itself is proof the message exists.**

So the assertions here are absences, and each has a positive beside it. An absence
alone would be satisfied by a redaction that blanked every parent on the hub, which
would break threading for everybody and pass this file.
"""

from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

#: Handles, not people. The scenario is the one in the issue.
LUDMILA = "ludmila_coe"
PABLO = "pablo_fantomas"
JED = "jed_arkwright"


async def _hub() -> Mailbox:
    mailbox = Mailbox(InMemoryStore(), hub_name="testhub")
    for name in (LUDMILA, PABLO, JED):
        await mailbox.join(name)
    return mailbox


async def _private_thread_then_a_reply_to_an_outsider(
    mailbox: Mailbox,
) -> tuple[str, str]:
    """Ludmila opens to Pablo alone, then replies on that thread addressing Jed.

    Jed is properly party to the reply — it is addressed to him. He was never party to
    the opener, and has no way to become so.
    """
    opener = await mailbox.send(LUDMILA, PABLO, "the quiet part", subject="between us")
    reply = await mailbox.send(
        LUDMILA,
        JED,
        "a thing about it",
        subject="Re: between us",
        in_reply_to=opener.id,
    )
    return opener.id, reply.id


class TestTheOutsiderIsNotToldTheParentExists:
    async def test_peek_does_not_name_the_parent(self) -> None:
        mailbox = await _hub()
        opener_id, reply_id = await _private_thread_then_a_reply_to_an_outsider(mailbox)

        waiting = await mailbox.peek(JED)

        assert [m.id for m in waiting] == [reply_id], "the reply must still arrive"
        assert waiting[0].in_reply_to is None, f"leaked {opener_id}"

    async def test_read_does_not_name_the_parent(self) -> None:
        mailbox = await _hub()
        _, reply_id = await _private_thread_then_a_reply_to_an_outsider(mailbox)

        got = await mailbox.read(JED, reply_id)

        assert got.content, "the reply's own content is not what is being withheld"
        assert got.in_reply_to is None

    async def test_view_does_not_name_the_parent(self) -> None:
        mailbox = await _hub()
        _, reply_id = await _private_thread_then_a_reply_to_an_outsider(mailbox)

        assert (await mailbox.view(JED, reply_id)).in_reply_to is None

    async def test_thread_does_not_name_the_parent(self) -> None:
        """Asking for the thread of a reply returns the reply. It must not, in doing
        so, hand back the id of the turn deliberately kept out of that answer."""
        mailbox = await _hub()
        _, reply_id = await _private_thread_then_a_reply_to_an_outsider(mailbox)

        turns = await mailbox.thread(JED, reply_id)

        assert [t.id for t in turns] == [reply_id]
        assert turns[0].in_reply_to is None

    async def test_search_does_not_name_the_parent(self) -> None:
        mailbox = await _hub()
        _, reply_id = await _private_thread_then_a_reply_to_an_outsider(mailbox)

        hits, _more = await mailbox.search(JED, "thing")

        assert [h.record.id for h in hits] == [reply_id]
        assert hits[0].snippet, "the snippet is not what is being withheld"
        assert hits[0].record.in_reply_to is None


class TestAParticipantStillSeesTheThread:
    """The paired positives. Without these, blanking every parent on the hub would
    satisfy the class above — and break every client that renders a conversation."""

    async def test_the_author_still_sees_her_own_parent(self) -> None:
        mailbox = await _hub()
        opener_id, reply_id = await _private_thread_then_a_reply_to_an_outsider(mailbox)

        assert (await mailbox.view(LUDMILA, reply_id)).in_reply_to == opener_id

    async def test_a_party_to_both_still_sees_the_parent(self) -> None:
        """The ordinary case, which is nearly every case: a conversation between the
        same people throughout."""
        mailbox = await _hub()
        opener = await mailbox.send(LUDMILA, PABLO, "one", subject="ordinary")
        reply = await mailbox.reply(PABLO, opener.id, "two")

        waiting = await mailbox.peek(LUDMILA)
        assert [m.id for m in waiting] == [reply.id]
        assert waiting[0].in_reply_to == opener.id

    async def test_a_thread_keeps_its_shape_for_its_participants(self) -> None:
        mailbox = await _hub()
        opener = await mailbox.send(LUDMILA, PABLO, "one", subject="ordinary")
        reply = await mailbox.reply(PABLO, opener.id, "two")

        turns = await mailbox.thread(LUDMILA, reply.id)

        assert {t.id: t.in_reply_to for t in turns} == {
            opener.id: None,
            reply.id: opener.id,
        }
