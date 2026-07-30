"""A successful reply marks the original read — issue #33, mission
`reply-marks-the-original-read-01KYSRD1`.

Replying and reading used to be independent, so an agent answered a message and still
saw
it waiting until it separately read the thing it had just replied to. Found by using the
mailbox, not by reading it: `zakhar_shchukina` had to batch-call `read_message` on
messages
it had already answered, purely to clear its own manifest.

**The two that matter are the failure cases.** A test asserting "still unread after a
failed
send" passes trivially if the failure path never reaches the mark at all, so both are
proved
by removing the guard and watching them fail.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

ALICE = "alice_okonkwo"
BOB = "bob_hansson"
CAROL = "carol_ruzickova"


@pytest.fixture
async def house() -> AsyncIterator[House]:
    async with House(Mailbox(InMemoryStore())) as opened:
        for who in (ALICE, BOB, CAROL):
            await opened.join(who)
        yield opened


async def _waiting(house: House, who: str) -> list[str]:
    """What `check_inbox` would show — the manifest this feature exists to clear."""
    return [m.content for m in await house.peek(who)]


class TestReplyingIsHandling:
    async def test_a_reply_marks_the_original_read(self, house: House) -> None:
        opener = (await house.send(ALICE, BOB, "a question")).record
        assert await _waiting(house, BOB) == ["a question"]

        await house.reply(BOB, opener.id, "an answer")
        assert await _waiting(house, BOB) == [], "answered mail must leave the manifest"

    async def test_replying_twice_is_not_an_error(self, house: House) -> None:
        """An agent may legitimately follow up on something it has already read."""
        opener = (await house.send(ALICE, BOB, "a question")).record
        await house.reply(BOB, opener.id, "an answer")
        await house.reply(BOB, opener.id, "and one more thing")
        assert await _waiting(house, BOB) == []

    async def test_reading_first_then_replying_is_fine(self, house: House) -> None:
        opener = (await house.send(ALICE, BOB, "a question")).record
        await house.read(BOB, opener.id)
        await house.reply(BOB, opener.id, "an answer")
        assert await _waiting(house, BOB) == []


class TestOnlyTheReplier:
    async def test_a_broadcast_is_marked_for_the_replier_alone(
        self, house: House
    ) -> None:
        """Read state is per recipient, and answering must not speak for anybody
        else."""
        opener = (await house.send(ALICE, [BOB, CAROL], "everyone")).record

        await house.reply(BOB, opener.id, "bob answers")

        assert await _waiting(house, BOB) == []
        assert "everyone" in await _waiting(house, CAROL), (
            "carol has not dealt with it, and bob cannot decide that she has"
        )


class TestTheFailureDirection:
    """FR-003 and FR-006: the state that must never happen is *marked read without a
    durable send*. Ordering makes it unreachable rather than merely unlikely."""

    async def test_a_failed_send_leaves_the_original_unread(self, house: House) -> None:
        opener = (await house.send(ALICE, BOB, "a question")).record

        async def refuse(*args: object, **kwargs: object) -> None:
            raise RuntimeError("the send failed")

        house._mailbox.send = refuse  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            await house.reply(BOB, opener.id, "an answer that never left")

        assert "a question" in await _waiting(house, BOB), (
            "nothing was sent, so nothing was handled"
        )

    async def test_a_failed_mark_does_not_fail_the_reply(self, house: House) -> None:
        """The acceptable degraded state: reply delivered, original still unread.

        Raising here would report a failed reply that in fact succeeded — worse than the
        state it would be complaining about.
        """
        opener = (await house.send(ALICE, BOB, "a question")).record

        async def refuse(*args: object, **kwargs: object) -> None:
            raise RuntimeError("the store would not mark it")

        house._mailbox.mark_read_for = refuse  # type: ignore[method-assign]
        sent = await house.reply(BOB, opener.id, "an answer")

        assert sent.record.id, "the reply happened and the caller was told so"
        assert "a question" in await _waiting(house, BOB), (
            "and self-corrects with a read"
        )


class TestNonDestructiveReadsStayThatWay:
    async def test_peeking_still_consumes_nothing(self, house: House) -> None:
        opener = (await house.send(ALICE, BOB, "a question")).record
        await house.peek(BOB)
        await house.peek(BOB)
        assert "a question" in await _waiting(house, BOB)
        assert opener.id

    async def test_viewing_still_consumes_nothing(self, house: House) -> None:
        opener = (await house.send(ALICE, BOB, "a question")).record
        await house.view(BOB, opener.id)
        assert "a question" in await _waiting(house, BOB)


class TestTheVisibilityRuleIsNotBypassed:
    async def test_a_stranger_cannot_mark_somebody_elses_mail(
        self, house: House
    ) -> None:
        """`mark_read_for` carries the rule itself rather than trusting its caller — a
        guard that lives only in the current caller is one the next caller forgets."""
        from agent_inbox.exceptions import NoSuchMessage

        opener = (await house.send(ALICE, BOB, "private")).record
        with pytest.raises(NoSuchMessage):
            await house.mailbox.mark_read_for(CAROL, opener.id)

    async def test_and_a_stranger_cannot_reply_to_it_either(self, house: House) -> None:
        from agent_inbox.exceptions import NoSuchMessage

        opener = (await house.send(ALICE, BOB, "private")).record
        with pytest.raises(NoSuchMessage):
            await house.reply(CAROL, opener.id, "not mine to answer")
