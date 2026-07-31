"""A hub that retries, and stops honestly when it exits — WP03 of mission
`retry-delivery-to-a-sleeping-peer-01KYWFWB` (federation step 7).

`tests/test_delivery_retry.py` proves the retry loop in isolation. This proves it is
actually *wired into a running house*, that closing one gives up rather than quietly
evaporating, and that the queue is not a second route around the `@local` guarantee.

**The shutdown case is the one that earns the design.** The queue is held in memory by
deliberate choice, and that is only acceptable because the volatility is disclosed
rather than discovered. We redeploy on every release, so a process exiting while
holding messages it called `queued` is not an edge case — it is a scheduled event.
"""

from __future__ import annotations

import pytest

from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.peers import PeerUnreachable
from agent_inbox.records import ObjectRecord
from agent_inbox.retry import RetryingDelivery
from agent_inbox.store import InMemoryStore

ROSEMARY = "rosemary_delacroix"
BOB = "bob_hansson"
ATLAS = "atlas@sleepy.example"


class SleepyPeer:
    """A peer that never answers — the case the queue exists for."""

    def __init__(self, wake_after: int | None = None) -> None:
        self.attempts = 0
        #: Attempt number on which the peer wakes up, or never.
        self.wake_after = wake_after
        self.delivered: list[str] = []

    async def resolve(self, address: str) -> object:
        name, _, host = address.partition("@")
        return f"https://{host}/actors/{name}"

    def actor_uri(self, resolved: object) -> str:
        return str(resolved)

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        self.attempts += 1
        if self.wake_after is not None and self.attempts >= self.wake_after:
            self.delivered.append(record.id)
            return
        # No status: nobody answered. This is what a suspended machine looks like.
        raise PeerUnreachable(f"could not reach {resolved}")


async def _never_sleep(seconds: float) -> None:
    """The bound is minutes; the suite must not be."""
    return None


def _house(peer: SleepyPeer) -> House:
    house = House(Mailbox(InMemoryStore()), deliver=peer)
    assert isinstance(house._deliver, RetryingDelivery)
    house._deliver.sleep = _never_sleep
    return house


class TestAHouseRetries:
    async def test_a_sleeping_peer_is_queued_not_failed(self) -> None:
        peer = SleepyPeer()
        async with _house(peer) as house:
            await house.join(ROSEMARY)
            sent = await house.send(ROSEMARY, ATLAS, "are you up")
            assert [r.state for r in sent.receipts] == ["queued"]

    async def test_a_queued_send_has_not_reached_nobody(self) -> None:
        """The regression WP01 exists to prevent, seen end to end: `api.py` refuses a
        201 when `reached_nobody`, and a message merely waiting must not trip it."""
        peer = SleepyPeer()
        async with _house(peer) as house:
            await house.join(ROSEMARY)
            sent = await house.send(ROSEMARY, ATLAS, "are you up")
            assert not sent.reached_nobody

    async def test_the_sender_is_told_the_wait_is_not_durable(self) -> None:
        peer = SleepyPeer()
        async with _house(peer) as house:
            await house.join(ROSEMARY)
            sent = await house.send(ROSEMARY, ATLAS, "are you up")
            assert "does not survive a restart" in (sent.receipts[0].detail or "")

    async def test_a_peer_that_wakes_gets_the_message(self) -> None:
        peer = SleepyPeer(wake_after=3)
        async with _house(peer) as house:
            await house.join(ROSEMARY)
            await house.send(ROSEMARY, ATLAS, "are you up")
            for _ in range(50):
                if peer.delivered:
                    break
                await _tick()
        assert peer.delivered, "it arrived without anyone doing anything"
        assert peer.attempts == 3


async def _tick() -> None:
    import asyncio

    await asyncio.sleep(0)


class TestClosingIsHonest:
    """FR-008(b). A promise the process stops keeping must be withdrawn, not dropped."""

    async def test_closing_gives_up_on_what_is_still_waiting(self) -> None:
        peer = SleepyPeer()
        house = _house(peer)
        await house.open()
        await house.join(ROSEMARY)
        await house.send(ROSEMARY, ATLAS, "still waiting")

        assert len(house._deliver) == 1  # type: ignore[arg-type]
        await house.aclose()
        assert len(house._deliver) == 0, (  # type: ignore[arg-type]
            "the queue must not outlive the house that promised it"
        )

    async def test_the_context_manager_closes_the_queue(self) -> None:
        peer = SleepyPeer()
        house = _house(peer)
        async with house:
            await house.join(ROSEMARY)
            await house.send(ROSEMARY, ATLAS, "still waiting")
        assert len(house._deliver) == 0  # type: ignore[arg-type]

    async def test_closing_a_house_with_nothing_waiting_is_fine(self) -> None:
        async with _house(SleepyPeer()) as house:
            await house.join(ROSEMARY)


class TestLocalNeverQueues:
    """FR-007. `@local` never leaves the machine, and the queue must not become a second
    route around a guarantee that holds by construction elsewhere."""

    async def test_a_local_recipient_is_delivered_not_queued(self) -> None:
        peer = SleepyPeer()
        async with _house(peer) as house:
            await house.join(ROSEMARY)
            await house.join(BOB)
            sent = await house.send(ROSEMARY, BOB, "just between us")

        assert sent.receipts == (), (
            "a local recipient produces no remote receipt at all"
        )
        assert peer.attempts == 0, "and nothing was attempted off-machine"
        assert len(house._deliver) == 0  # type: ignore[arg-type]

    async def test_a_mixed_send_queues_only_the_remote_half(self) -> None:
        """The control that stops the test above passing vacuously.

        If the queue were never reached in this test, 'the local one did not queue'
        would be true for the wrong reason. Here the remote recipient demonstrably
        *does* queue, in the very same send.
        """
        peer = SleepyPeer()
        house = _house(peer)
        await house.open()
        await house.join(ROSEMARY)
        await house.join(BOB)

        sent = await house.send(ROSEMARY, [BOB, ATLAS], "one each")

        assert [r.state for r in sent.receipts] == ["queued"], "the remote one queued"
        assert BOB in sent.local_recipients, "and the local one was simply delivered"
        assert len(house._deliver) == 1, "exactly one thing waiting, not two"  # type: ignore[arg-type]
        await house.aclose()


class TestNoCollaboratorStillRefuses:
    async def test_a_house_without_federation_refuses_a_remote_address(self) -> None:
        """Retrying is not a reason to soften this. A send that succeeds and reaches
        nobody is still the worst failure shape available."""
        from agent_inbox.exceptions import RemoteMailbox

        async with House(Mailbox(InMemoryStore())) as house:
            await house.join(ROSEMARY)
            with pytest.raises(RemoteMailbox):
                await house.send(ROSEMARY, ATLAS, "nowhere to go")
