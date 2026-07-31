"""Retrying a sleeping peer, and refusing to retry our own decisions — WP02 of mission
`retry-delivery-to-a-sleeping-peer-01KYWFWB` (federation step 7).

**Two tests here carry the mission's safety property, and both pass for the wrong reason
if the retry loop never runs at all.** Each is written so that a demonstrably *working*
retry is established first, and each was checked by removing the guard and watching it
fail. A test that asserts "the untrusted peer was not delivered to" is worthless when
nothing was ever delivered to anybody.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_inbox.outbound import DeliveryRefused
from agent_inbox.peers import PeerUnreachable
from agent_inbox.records import ObjectRecord
from agent_inbox.retry import Queued, RetryingDelivery, is_retryable, wrap

SLEEPY = "https://sleepy.example/actors/atlas"


def _record(ident: str = "urn:test:1") -> ObjectRecord:
    return ObjectRecord(
        id=ident,
        attributed_to="alice_okonkwo",
        to=(SLEEPY,),
        content="are you there",
        summary="a question",
    )


class FakeDelivery:
    """A `RemoteDelivery` whose every attempt is scripted.

    `outcomes` is consumed one per attempt: `None` succeeds, an exception is raised.
    Anything past the end succeeds, so "fails twice then works" is one short list.
    """

    def __init__(self, *outcomes: BaseException | None) -> None:
        self.outcomes = list(outcomes)
        self.attempts = 0
        #: Set by a test to change the answer part-way through — how withdrawal of trust
        #: is simulated without a live hub.
        self.always: BaseException | None = None

    async def resolve(self, address: str) -> object:
        return address

    def actor_uri(self, resolved: object) -> str:
        return str(resolved)

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        self.attempts += 1
        if self.always is not None:
            raise self.always
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if outcome is not None:
                raise outcome


def unreachable() -> PeerUnreachable:
    """Nobody answered — the case the queue exists for."""
    return PeerUnreachable("could not reach sleepy.example")


class Clock:
    """A sleep that records rather than elapses.

    The bound is minutes; the suite must not be. Recording the schedule also catches the
    bug a count-only assertion misses — six immediate retries would pass "it tried six
    times" while hammering a peer that is already struggling.
    """

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        await asyncio.sleep(0)


async def _settle() -> None:
    """Let the retry task run to completion."""
    for _ in range(50):
        await asyncio.sleep(0)


class TestClassification:
    """The distinction the whole module turns on."""

    def test_our_own_refusal_is_never_retryable(self) -> None:
        assert not is_retryable(DeliveryRefused("this hub does not federate"))

    def test_nobody_answered_is_retryable(self) -> None:
        assert is_retryable(unreachable())

    def test_a_peer_that_is_up_but_broken_is_retryable(self) -> None:
        assert is_retryable(PeerUnreachable("boom", status=503))

    def test_a_peer_that_said_no_is_not(self) -> None:
        """A 4xx is a considered rejection; five more minutes will not change it."""
        assert not is_retryable(PeerUnreachable("no thanks", status=422))

    def test_an_unrecognised_error_is_not_retryable(self) -> None:
        """Allow-list, not deny-list. An error we have not thought about is likelier to
        be a bug in us than weather at the far end."""
        assert not is_retryable(ValueError("something we never considered"))


class TestTheInlineAttempt:
    async def test_a_delivery_that_works_first_time_does_not_queue(self) -> None:
        inner = FakeDelivery()
        retrying = RetryingDelivery(inner, sleep=Clock())
        await retrying.deliver(SLEEPY, _record())
        assert inner.attempts == 1
        assert len(retrying) == 0

    async def test_an_unreachable_peer_queues_rather_than_fails(self) -> None:
        inner = FakeDelivery(unreachable())
        inner.outcomes.append(None)
        retrying = RetryingDelivery(inner, sleep=Clock())
        with pytest.raises(Queued) as queued:
            await retrying.deliver(SLEEPY, _record())
        assert queued.value.recipient == SLEEPY
        await _settle()

    async def test_a_refusal_propagates_and_does_not_queue(self) -> None:
        inner = FakeDelivery(DeliveryRefused("peer is not trusted"))
        retrying = RetryingDelivery(inner, sleep=Clock())
        with pytest.raises(DeliveryRefused):
            await retrying.deliver(SLEEPY, _record())
        assert len(retrying) == 0, "a refusal must never enter the queue"


class TestTheRetryLoop:
    async def test_a_peer_that_wakes_up_gets_the_message(self) -> None:
        inner = FakeDelivery(unreachable(), unreachable(), None)
        retrying = RetryingDelivery(inner, sleep=Clock())
        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())
        await _settle()
        assert inner.attempts == 3, "inline attempt, then two retries"
        assert len(retrying) == 0

    async def test_retries_stop_at_the_bound(self) -> None:
        inner = FakeDelivery()
        inner.always = unreachable()
        clock = Clock()
        retrying = RetryingDelivery(inner, sleep=clock)
        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())
        await _settle()
        assert inner.attempts == 6, (
            "one inline attempt plus five retries, then given up"
        )
        assert len(retrying) == 0

    async def test_the_backoff_schedule_increases(self) -> None:
        """Assert the schedule, not the count."""
        inner = FakeDelivery()
        inner.always = unreachable()
        clock = Clock()
        retrying = RetryingDelivery(inner, sleep=clock)
        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())
        await _settle()
        assert clock.waits == [2.0, 8.0, 30.0, 60.0, 90.0]
        assert clock.waits == sorted(clock.waits), "must be strictly increasing"
        assert sum(clock.waits) < 300, "must fit under the five-minute ceiling"


class TestAuthorizationIsReDerived:
    """**The most important test in the mission.**

    A queue that carried an authorization decision from queue time would let a stalled
    retry deliver to a peer we had since stopped trusting. Nothing about the happy path
    would look different, which is why this is proved by removal rather than by passing.
    """

    async def test_trust_withdrawn_while_waiting_stops_the_delivery(self) -> None:
        inner = FakeDelivery(unreachable())
        retrying = RetryingDelivery(inner, sleep=Clock())

        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())

        # The operator removes the peer while the message waits.
        inner.always = DeliveryRefused("sleepy.example is not a peer of this hub")
        await _settle()

        assert inner.attempts == 2, "it tried again — the loop demonstrably ran"
        assert len(retrying) == 0, "and stopped at once rather than trying five times"

    async def test_the_loop_really_runs_when_trust_is_intact(self) -> None:
        """The control for the test above.

        Without this, 'it did not deliver to the untrusted peer' would be satisfied by a
        retry loop that never fires at all.
        """
        inner = FakeDelivery(unreachable(), None)
        retrying = RetryingDelivery(inner, sleep=Clock())
        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())
        await _settle()
        assert inner.attempts == 2, "the same loop, delivering when it is allowed to"

    async def test_a_refusal_mid_queue_is_not_retried_five_more_times(self) -> None:
        """FR-004 seen from the queue: a withdrawal of trust bites at the next attempt,
        not after the whole window."""
        inner = FakeDelivery(unreachable())
        clock = Clock()
        retrying = RetryingDelivery(inner, sleep=clock)
        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())
        inner.always = DeliveryRefused("no longer trusted")
        await _settle()
        assert len(clock.waits) == 1, "one backoff, then it stopped arguing"


class TestShutdown:
    async def test_closing_stops_the_queue(self) -> None:
        inner = FakeDelivery()
        inner.always = unreachable()
        retrying = RetryingDelivery(inner, sleep=Clock())
        with pytest.raises(Queued):
            await retrying.deliver(SLEEPY, _record())

        await retrying.aclose()
        assert len(retrying) == 0

    async def test_closing_an_idle_queue_is_fine(self) -> None:
        await RetryingDelivery(FakeDelivery(), sleep=Clock()).aclose()


class TestWrap:
    def test_no_collaborator_stays_no_collaborator(self) -> None:
        """A house without federation must keep refusing remote recipients, not acquire
        a queue that would swallow them."""
        assert wrap(None) is None

    def test_a_collaborator_gains_retrying(self) -> None:
        assert isinstance(wrap(FakeDelivery()), RetryingDelivery)
