"""`read_thread` accepts any turn, not only a thread's opener — issue #24.

Reported from live use: an agent read a message, called `read_thread` on that message's
id, and got `no such thread` about a thread it was in and had just read. From inside the
code the behaviour looked correct, because the parameter was named `root_id` and was
passed straight to a filter that matches on thread root.

The rejected alternative is worth knowing, because it is the one that looks simpler.
Resolving the root first and filtering afterwards also fixes the report — but it lets a
caller distinguish "this id belongs to a thread I am in" from "this id means nothing",
for a turn they cannot see. Refusing first costs nothing: any thread you can see can be
named by a turn you can see.
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


async def _three_turns(house: House) -> tuple[str, str, str]:
    """A conversation of three turns between two people."""
    opener = (await house.send(ALICE, BOB, "first", subject="a thread")).record
    middle = (await house.send(BOB, ALICE, "second", in_reply_to=opener.id)).record
    last = (await house.send(ALICE, BOB, "third", in_reply_to=middle.id)).record
    return opener.id, middle.id, last.id


class TestAnyTurnNamesItsThread:
    async def test_every_turn_gives_the_same_conversation(self, house: House) -> None:
        """Stated as an invariant rather than three expected values — the framing
        `ludmila_coe` proposed, and better than asserting each in turn."""
        opener, middle, last = await _three_turns(house)

        views = [
            {m.id for m in await house.thread(ALICE, probe)}
            for probe in (opener, middle, last)
        ]
        assert views[0] == views[1] == views[2]
        assert views[0] == {opener, middle, last}

    async def test_the_opener_still_works(self, house: House) -> None:
        """It always did. The fix must not trade one accepted id for another."""
        opener, _, _ = await _three_turns(house)
        assert len(await house.thread(ALICE, opener)) == 3

    async def test_a_reply_no_longer_says_no_such_thread(self, house: House) -> None:
        """The reported symptom, exactly: read a message, ask for its thread."""
        _, middle, _ = await _three_turns(house)
        assert await house.thread(BOB, middle) != ()


class TestTheOracleStaysClosed:
    """The property the chosen fix preserves, and the looser one would have lost."""

    async def test_a_turn_you_cannot_see_is_indistinguishable_from_a_made_up_id(
        self, house: House
    ) -> None:
        """Carol opens to alice and bob; alice replies privately to carol.

        Bob is party to the thread but **not** to that reply. Naming it must tell him
        exactly what naming a fictional id tells him: nothing.
        """
        opener = (await house.send(CAROL, [ALICE, BOB], "everyone here")).record
        private = (
            await house.send(ALICE, CAROL, "just between us", in_reply_to=opener.id)
        ).record

        assert await house.thread(BOB, private.id) == ()
        assert await house.thread(BOB, "an id that never existed") == ()

    async def test_and_he_still_sees_the_thread_by_a_turn_he_can_see(
        self, house: House
    ) -> None:
        """No capability is lost. This is what makes refusing first free."""
        opener = (await house.send(CAROL, [ALICE, BOB], "everyone here")).record
        await house.send(ALICE, CAROL, "just between us", in_reply_to=opener.id)

        seen = await house.thread(BOB, opener.id)
        assert [m.content for m in seen] == ["everyone here"]

    async def test_the_private_reply_is_never_disclosed(self, house: House) -> None:
        """Membership is per turn. Scenario 7, across the fix rather than around it."""
        opener = (await house.send(CAROL, [ALICE, BOB], "everyone here")).record
        await house.send(ALICE, CAROL, "just between us", in_reply_to=opener.id)

        for probe in (opener.id,):
            bodies = [m.content for m in await house.thread(BOB, probe)]
            assert "just between us" not in bodies


class TestThingsThatWereAlreadyRight:
    """Pinned, not newly required — so nobody specifies work that already exists."""

    async def test_a_message_whose_parent_is_not_ours_is_its_own_thread(
        self, house: House
    ) -> None:
        """Ordinary since step 5: a remote `inReplyTo` is stored and never fetched. The
        walk stops rather than erroring."""
        orphan = (
            await house.send(
                ALICE,
                BOB,
                "replying to something abroad",
                in_reply_to="https://beta.example/objects/9",
            )
        ).record
        assert [m.id for m in await house.thread(ALICE, orphan.id)] == [orphan.id]

    async def test_a_stranger_learns_nothing(self, house: House) -> None:
        opener, _, _ = await _three_turns(house)
        assert await house.thread(CAROL, opener) == ()
