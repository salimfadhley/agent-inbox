"""A peer blocked *while a message waits* is refused on the next attempt.

The intersection of two missions, and the case neither tested on its own.
`retry-delivery-to-a-sleeping-peer` proved that trust withdrawn mid-queue prevents
delivery; `federated-identity-and-trust` added a blocklist that overrides trust. Nobody
had asserted the blocklist survives the same journey.

It matters more than the peering case, not less. Removing a peering is an operator
tidying up; **blocking is an operator saying "do not talk to them"**, and the message
most likely to be in flight when they say it is the one that provoked them.

FR-050 in its strongest form: authorization is re-derived on every attempt and never
carried from queue time.
"""

import asyncio

import pytest

from agent_inbox import retry
from agent_inbox.delivery import Receipt
from agent_inbox.federation import may_exchange
from agent_inbox.outbound import DeliveryRefused
from agent_inbox.peers import PeerUnreachable
from agent_inbox.records import ObjectRecord
from agent_inbox.store import InMemoryStore

PEER = "https://peer.example"
STAMP = "2026-08-06"


class Collaborator:
    """A delivery that consults the real decision, and records every attempt.

    Modelled on `FederatedDelivery`: it asks `may_exchange` on *every* call and carries
    nothing between them, which is the behaviour under test.
    """

    def __init__(self, store: InMemoryStore) -> None:
        self.store = store
        self.attempts: list[str] = []
        self.reachable = False
        self.refusals: list[str] = []

    async def resolve(self, recipient: str) -> object:
        return object()

    def actor_uri(self, resolved: object) -> str:
        return f"{PEER}/actors/them"

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        verdict = await may_exchange(self.store, PEER)
        if not verdict:
            self.refusals.append(record.id)
            # `DeliveryRefused` is terminal by `is_retryable` — our own decision cannot
            # change by asking ourselves again, which is exactly right for a block.
            raise DeliveryRefused(verdict.reason)
        if not self.reachable:
            raise PeerUnreachable("asleep")
        self.attempts.append(record.id)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


async def _queued(
    store: InMemoryStore, inner: Collaborator
) -> tuple[retry.RetryingDelivery, list[float]]:
    """A message whose inline attempt failed, now waiting on the queue."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        await asyncio.sleep(0)

    courier = retry.RetryingDelivery(inner=inner, backoff=(0.0, 0.0, 0.0), sleep=sleep)
    record = ObjectRecord(id="m-1", attributed_to="us", content="x", published=STAMP)
    resolved = await courier.resolve("them@peer.example")
    with pytest.raises(retry.Queued):
        await courier.deliver(resolved, record)
    return courier, slept


async def _settle() -> None:
    """Let the background retry task run to completion."""
    for _ in range(20):
        await asyncio.sleep(0)


class TestABlockAppliedWhileWaiting:
    async def test_the_next_attempt_is_refused(self, store: InMemoryStore) -> None:
        inner = Collaborator(store)
        await _queued(store, inner)

        # The operator blocks them *now*, with the message already waiting — and the
        # peer comes back up, so the only reason not to send is the block.
        await store.add_block(PEER, STAMP, "they sent phishing")
        inner.reachable = True
        await _settle()

        assert inner.attempts == [], (
            "a message was delivered to a hub blocked after it was queued — "
            "authorization was carried from queue time (FR-050)"
        )
        assert inner.refusals, "the block was never consulted on a retry at all"

    async def test_without_the_block_it_does_arrive(self, store: InMemoryStore) -> None:
        """The paired positive, and the one that makes the test above mean something: a
        queue that never delivered anything would satisfy it trivially."""
        inner = Collaborator(store)
        await _queued(store, inner)

        inner.reachable = True
        await _settle()

        assert inner.attempts == ["m-1"], "nothing was retried at all"


class TestTheQueueCarriesNoDecision:
    def test_a_waiting_item_holds_no_authorization_state(self) -> None:
        """Asserted on the dataclass rather than by reading the loop: the failure this
        prevents is somebody adding a `peers` or `settings` field for speed, and that
        change would look harmless in review."""
        fields = set(retry._Waiting.__dataclass_fields__)  # noqa: SLF001

        assert fields == {"resolved", "record", "recipient", "attempts"}, (
            f"the queue gained a field that could carry a stale decision: {fields}"
        )

    def test_a_receipt_for_a_queued_message_is_not_delivered(self) -> None:
        """`queued` is a third state, not a kind of success — the distinction that stops
        a sender believing a suspended peer has their mail."""
        waiting = Receipt.waiting("them@peer.example")

        assert waiting.state == "queued"
        assert waiting.delivered is False
