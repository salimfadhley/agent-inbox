"""One inbound activity is delivered once, even when two attempts race (issue #41).

The receiving hub used to ask `seen_activity` and then deliver — check, act, record,
three steps and two commits with no atomicity between them. The retry queue produces
exactly the input that breaks it: **a client-side timeout does not cancel the peer's
in-flight request**, so when our queue retries, the receiver is still inside
`house.send` from the first attempt. Both POSTs pass the question before either writes
the answer, and `Mailbox.send` mints a fresh uuid per call, so nothing downstream can
catch the second.

The fix makes the marker the decision rather than a note taken afterwards. What it must
*not* do is trade a duplicate for a silent drop — the issue says so plainly, and for a
mailbox a lost message is the worse of the two. So half of this file is about the
failure paths: a claim that is abandoned, refused, or interrupted has to become
available again.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from agent_inbox.mailbox import CLAIM_LEASE_SECONDS, Mailbox
from agent_inbox.sqlite_store import SqliteStore
from agent_inbox.store import InMemoryStore, MessageStore

ACTIVITY = "https://peer.example/activities/1"


@pytest.fixture(params=["memory", "sqlite"])
async def store(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[MessageStore]:
    """Both stores, because the claim is only worth having if both honour it.

    The in-memory one is what the whole suite runs on, so a guarantee it does not
    implement is a guarantee the suite cannot see. SQLite is what actually ships.
    """
    if request.param == "memory":
        yield InMemoryStore()
        return
    path = tmp_path_factory.mktemp("claim") / "hub.db"
    async with SqliteStore(path) as opened:
        yield opened


class TestOnlyOneAttemptWins:
    async def test_a_second_claim_is_refused(self, store: MessageStore) -> None:
        """The bug, at its smallest. Both callers used to be told "not seen"."""
        assert await store.claim_activity(
            ACTIVITY, "2026-08-07T10:00:00+00:00", "2026-01-01"
        )

        assert not await store.claim_activity(
            ACTIVITY, "2026-08-07T10:00:00+00:00", "2026-01-01"
        )

    async def test_a_claim_survives_completion(self, store: MessageStore) -> None:
        """A delivered activity is refused for ever, whatever its age — which is what
        `stale_before` must never override."""
        await store.claim_activity(ACTIVITY, "2020-01-01T00:00:00+00:00", "2019-01-01")
        await store.complete_activity(ACTIVITY)

        assert not await store.claim_activity(
            ACTIVITY, "2026-08-07T10:00:00+00:00", "2026-08-07T09:00:00+00:00"
        ), "an old *delivered* activity was offered for redelivery"

    async def test_a_different_activity_is_unaffected(
        self, store: MessageStore
    ) -> None:
        """The paired positive. A claim that refused everything would satisfy every
        test above and stop the hub receiving mail at all."""
        assert await store.claim_activity(
            ACTIVITY, "2026-08-07T10:00:00+00:00", "2026-01-01"
        )

        assert await store.claim_activity(
            ACTIVITY + "-other", "2026-08-07T10:00:00+00:00", "2026-01-01"
        )


class TestAnAbandonedClaimIsNotALostMessage:
    """The trade the issue names: claim-before-act closes the duplicate window and
    opens a losing one, unless an incomplete claim can be taken over."""

    async def test_a_stale_incomplete_claim_can_be_taken_over(
        self, store: MessageStore
    ) -> None:
        """The crash case. Somebody claimed it, died before storing the message, and
        nothing else will ever complete it — so a later attempt must be allowed."""
        await store.claim_activity(ACTIVITY, "2026-08-07T10:00:00+00:00", "2026-01-01")

        taken = await store.claim_activity(
            ACTIVITY, "2026-08-07T12:00:00+00:00", "2026-08-07T11:00:00+00:00"
        )

        assert taken, "a message abandoned mid-delivery could never be delivered"

    async def test_a_fresh_incomplete_claim_may_not_be(
        self, store: MessageStore
    ) -> None:
        """And the other half: while somebody is genuinely still delivering, a second
        attempt is the duplicate. Without this the lease would make every race legal
        again, one window later."""
        await store.claim_activity(ACTIVITY, "2026-08-07T12:00:00+00:00", "2026-01-01")

        assert not await store.claim_activity(
            ACTIVITY, "2026-08-07T12:00:01+00:00", "2026-08-07T11:00:00+00:00"
        )

    async def test_releasing_gives_it_straight_back(self, store: MessageStore) -> None:
        """The fast path out of a failed delivery. Waiting for the lease would work,
        but a refusal that is known immediately should not cost the sender minutes."""
        await store.claim_activity(ACTIVITY, "2026-08-07T12:00:00+00:00", "2026-01-01")

        await store.release_activity(ACTIVITY)

        assert await store.claim_activity(
            ACTIVITY, "2026-08-07T12:00:01+00:00", "2026-01-01"
        )

    async def test_releasing_a_delivered_activity_does_nothing(
        self, store: MessageStore
    ) -> None:
        """The dangerous direction. Release is called from error paths, and an error
        path that re-opened a *completed* delivery would reintroduce the exact duplicate
        this closes — from the one place nobody is watching."""
        await store.claim_activity(ACTIVITY, "2026-08-07T12:00:00+00:00", "2026-01-01")
        await store.complete_activity(ACTIVITY)

        await store.release_activity(ACTIVITY)

        assert not await store.claim_activity(
            ACTIVITY, "2026-08-07T12:00:02+00:00", "2026-01-01"
        )


class TestTheMailboxComputesTheLease:
    async def test_a_fresh_claim_is_held(self) -> None:
        mailbox = Mailbox(InMemoryStore(), hub_name="testhub")

        assert await mailbox.claim_activity(ACTIVITY)
        assert not await mailbox.claim_activity(ACTIVITY)

    async def test_a_claim_older_than_the_lease_is_reclaimed(self) -> None:
        """Driven by the injected clock rather than by sleeping, so the lease can be a
        realistic five minutes without the suite taking five minutes."""
        moment = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
        store = InMemoryStore()
        mailbox = Mailbox(store, hub_name="testhub", clock=lambda: moment)
        assert await mailbox.claim_activity(ACTIVITY)

        later = moment + timedelta(seconds=CLAIM_LEASE_SECONDS + 1)
        reclaiming = Mailbox(store, hub_name="testhub", clock=lambda: later)

        assert await reclaiming.claim_activity(ACTIVITY)

    async def test_just_inside_the_lease_is_not_reclaimed(self) -> None:
        """The paired positive for the boundary — a lease of zero would pass the test
        above and protect nothing."""
        moment = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
        store = InMemoryStore()
        assert await Mailbox(
            store, hub_name="testhub", clock=lambda: moment
        ).claim_activity(ACTIVITY)

        later = moment + timedelta(seconds=CLAIM_LEASE_SECONDS - 1)

        assert not await Mailbox(
            store, hub_name="testhub", clock=lambda: later
        ).claim_activity(ACTIVITY)


class TestTheRaceItself:
    async def test_concurrent_claims_yield_exactly_one_winner(
        self, store: MessageStore
    ) -> None:
        """Window (a) from the issue, run rather than reasoned about.

        Twenty coroutines claim the same activity id at once. Exactly one may win —
        anything else is a duplicated message on a real hub.
        """
        won = await asyncio.gather(
            *(
                store.claim_activity(
                    ACTIVITY, "2026-08-07T12:00:00+00:00", "2026-01-01"
                )
                for _ in range(20)
            )
        )

        assert sum(1 for outcome in won if outcome) == 1, won
