"""Retracting a thread — the same primitive applied to a set, and nothing more.

The interesting case is the mixed thread, where a partial outcome is the *correct*
answer and both simpler answers are lies: "failed" hides what went, "done" hides what
stayed. The second is the dangerous one — an operator who believes a conversation is
gone when it is not.
"""

import pytest

from agent_inbox import retraction, threads
from agent_inbox.records import ActorRecord, ActorType, ObjectRecord
from agent_inbox.store import InMemoryStore

STAMP = "2026-08-05T00:00:00+00:00"
AGENT = "rosemary_nasrin"
OTHER = "trevor_bakshi"
HUMAN = "admin"


def clock() -> str:
    return STAMP


@pytest.fixture
async def store() -> InMemoryStore:
    made = InMemoryStore()
    for name, kind in (
        (AGENT, ActorType.SERVICE),
        (OTHER, ActorType.SERVICE),
        (HUMAN, ActorType.PERSON),
    ):
        await made.claim_name(
            ActorRecord(name=name, actor_type=kind, created=STAMP, last_seen=STAMP)
        )
    return made


async def conversation(store: InMemoryStore) -> list[str]:
    """Three turns: agent, other agent, agent — a reply chain."""
    turns = [("t1", AGENT, None), ("t2", OTHER, "t1"), ("t3", AGENT, "t2")]
    for oid, author, parent in turns:
        await store.add_object(
            ObjectRecord(
                id=oid,
                attributed_to=author,
                to=(OTHER, HUMAN),
                in_reply_to=parent,
                summary=f"subject {oid}",
                content=f"the body of {oid}",
                published=STAMP,
            )
        )
    return [oid for oid, _, _ in turns]


class TestAHumanRetractsTheWholeThread:
    async def test_every_message_goes(self, store: InMemoryStore) -> None:
        ids = await conversation(store)

        done = await threads.retract_thread(store, ids, HUMAN, now=clock)

        assert set(done.retracted) == set(ids)
        assert not done.refused
        for oid in ids:
            record = await store.get_object(oid)
            assert record is not None
            assert retraction.is_retracted(record)

    async def test_the_shape_of_the_conversation_survives(
        self, store: InMemoryStore
    ) -> None:
        """FR-012. Every turn keeps its place, its sender and what it answered, so a
        reader can still see that a conversation happened and who was in it."""
        ids = await conversation(store)

        await threads.retract_thread(store, ids, HUMAN, now=clock)

        second = await store.get_object("t2")
        assert second is not None
        assert second.in_reply_to == "t1"
        assert second.attributed_to == OTHER
        assert second.published == STAMP


class TestAnAgentRetractsOnlyItsOwn:
    async def test_a_mixed_thread_is_partial_and_says_so(
        self, store: InMemoryStore
    ) -> None:
        """The case both simpler answers get wrong."""
        ids = await conversation(store)

        done = await threads.retract_thread(store, ids, AGENT, now=clock)

        assert set(done.retracted) == {"t1", "t3"}
        assert [r.object_id for r in done.refused] == ["t2"]
        assert done.partial

    async def test_the_other_agents_message_is_untouched(
        self, store: InMemoryStore
    ) -> None:
        """The paired assertion, and the one that matters: a report saying 'refused' is
        not proof that nothing happened to it."""
        ids = await conversation(store)

        await threads.retract_thread(store, ids, AGENT, now=clock)

        theirs = await store.get_object("t2")
        assert theirs is not None
        assert theirs.content == "the body of t2"
        assert not retraction.is_retracted(theirs)

    async def test_one_refusal_does_not_stop_the_rest(
        self, store: InMemoryStore
    ) -> None:
        """The refused message is in the middle of the list, so an implementation that
        stopped at the first refusal would leave `t3` standing."""
        ids = await conversation(store)

        done = await threads.retract_thread(store, ids, AGENT, now=clock)

        assert "t3" in done.retracted

    async def test_the_refusal_carries_its_reason(self, store: InMemoryStore) -> None:
        """An operator reading a partial result needs to know *why* — and the reason is
        the one `retract` already gives, not a second wording invented here."""
        ids = await conversation(store)

        done = await threads.retract_thread(store, ids, AGENT, now=clock)

        assert "only its own" in done.refused[0].reason


class TestEachOneIsAuditedSeparately:
    async def test_there_is_one_entry_per_message(
        self, store: InMemoryStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FR-010. One entry saying "a thread" would lose which messages were
        destroyed, which is the thing an audit exists to record."""
        import logging

        ids = await conversation(store)

        with caplog.at_level(logging.WARNING):
            await threads.retract_thread(store, ids, HUMAN, now=clock)

        per_message = [
            r for r in caplog.records if "event=message.retracted" in r.getMessage()
        ]
        assert len(per_message) == 3
        for oid in ids:
            assert any(f"id={oid}" in r.getMessage() for r in per_message), oid


class TestItIsALoopAndNothingMore:
    def test_no_second_permission_test_was_written_here(self) -> None:
        """The constraint this module exists under. A decision made in two places will
        disagree, and here that means somebody's words destroyed by a caller who should
        not have been able to.

        Written against the source because the branch that would break it does not
        exist yet — the same guard as the human-authority test, and for the same reason.
        """
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src" / "agent_inbox" / "threads.py"
        ).read_text()

        forbidden = re.compile(r"ActorType\.|attributed_to\s*==|actor_type")
        assert not forbidden.search(source), (
            "threads.py decides who may retract — that belongs in retraction.py alone"
        )

    def test_the_search_would_find_one(self) -> None:
        """The premise. A pattern that matches nothing passes the test above for the
        wrong reason."""
        import re

        forbidden = re.compile(r"ActorType\.|attributed_to\s*==|actor_type")
        assert forbidden.search("    if actor.actor_type is ActorType.PERSON:")
        assert forbidden.search("    if record.attributed_to == by:")
        assert not forbidden.search("    retracted.append(object_id)")


class TestEdges:
    async def test_a_message_that_vanished_mid_thread_is_reported_not_fatal(
        self, store: InMemoryStore
    ) -> None:
        """Somebody else retracting concurrently is the ordinary way this happens, and
        it must not abort the rest of the operator's request."""
        ids = await conversation(store)

        done = await threads.retract_thread(
            store, [*ids, "never-existed"], HUMAN, now=clock
        )

        assert set(done.retracted) == set(ids)
        assert [r.object_id for r in done.refused] == ["never-existed"]

    async def test_an_empty_thread_is_not_an_error(self, store: InMemoryStore) -> None:
        done = await threads.retract_thread(store, [], HUMAN, now=clock)

        assert not done.retracted and not done.refused
        assert not done.partial
