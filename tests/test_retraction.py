"""Retraction — the only destructive act here, and the one that cannot be undone.

Every test in this file is about a way it could destroy the wrong thing, or destroy the
right thing and leave nothing to show for it.
"""

import logging

import pytest

from agent_inbox import retraction
from agent_inbox.exceptions import NoSuchMessage
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


async def a_message(
    store: InMemoryStore,
    oid: str = "m1",
    author: str = AGENT,
    parent: str | None = None,
) -> ObjectRecord:
    record = ObjectRecord(
        id=oid,
        attributed_to=author,
        to=(OTHER, HUMAN),
        in_reply_to=parent,
        summary="a subject",
        content="the body nobody else should be able to destroy",
        published=STAMP,
    )
    await store.add_object(record)
    return record


class TestWhoMayRetract:
    async def test_an_agent_may_retract_its_own(self, store: InMemoryStore) -> None:
        await a_message(store)

        gone = await retraction.retract(store, "m1", AGENT, now=clock)

        assert retraction.is_retracted(gone)

    async def test_an_agent_may_not_retract_another_agents(
        self, store: InMemoryStore
    ) -> None:
        """FR-014, and the refusal that matters most: this is somebody else's words."""
        await a_message(store)

        with pytest.raises(retraction.NotYoursToRetract):
            await retraction.retract(store, "m1", OTHER, now=clock)

    async def test_the_body_survives_a_refused_retraction(
        self, store: InMemoryStore
    ) -> None:
        """The paired assertion. A refusal that still destroyed the body would be the
        worst possible outcome, and 'it raised' does not prove it did not."""
        original = await a_message(store)

        with pytest.raises(retraction.NotYoursToRetract):
            await retraction.retract(store, "m1", OTHER, now=clock)

        still = await store.get_object("m1")
        assert still is not None
        assert still.content == original.content

    async def test_a_human_may_retract_anything(self, store: InMemoryStore) -> None:
        """FR-016. The other scope, and the one an operator has."""
        await a_message(store)

        gone = await retraction.retract(store, "m1", HUMAN, now=clock)

        assert retraction.is_retracted(gone)

    async def test_the_refusal_names_which_power_is_missing(
        self, store: InMemoryStore
    ) -> None:
        """ "Refused" tells an agent nothing it can act on. This is a refusal met while
        doing something reasonable, so it should explain rather than slap."""
        await a_message(store)

        with pytest.raises(retraction.NotYoursToRetract) as refused:
            await retraction.retract(store, "m1", OTHER, now=clock)

        said = str(refused.value)
        assert "only its own" in said
        assert "human" in said.lower(), "the power the caller lacks is not named"

    async def test_an_unknown_actor_is_treated_as_an_agent(
        self, store: InMemoryStore
    ) -> None:
        """The security-relevant default. A name the hub has never heard of must not be
        assumed human — failing towards refusal, never towards permission."""
        await a_message(store)

        with pytest.raises(retraction.NotYoursToRetract):
            await retraction.retract(store, "m1", "nobody_at_all", now=clock)


class TestWhatSurvives:
    async def test_the_body_goes_and_the_record_stays(
        self, store: InMemoryStore
    ) -> None:
        """FR-008. Position, sender and time are what make the thread readable after."""
        await a_message(store)

        gone = await retraction.retract(store, "m1", AGENT, now=clock)

        assert gone.content == retraction.TOMBSTONE
        assert "nobody else should be able to destroy" not in gone.content
        assert gone.attributed_to == AGENT
        assert gone.published == STAMP

    async def test_the_parent_link_survives(self, store: InMemoryStore) -> None:
        """FR-012 depends on this: a reply beneath a retraction still knows what it
        answered, so the conversation keeps its shape."""
        await a_message(store, oid="m2", parent="m1")

        gone = await retraction.retract(store, "m2", AGENT, now=clock)

        assert gone.in_reply_to == "m1"

    async def test_who_did_it_survives(self, store: InMemoryStore) -> None:
        """C-003: retraction destroys the body, never the record. An agent must not be
        able to send something and erase that it did."""
        await a_message(store)

        gone = await retraction.retract(store, "m1", HUMAN, now=clock)

        assert retraction.retracted_by(gone) == HUMAN

    async def test_the_subject_goes_too(self, store: InMemoryStore) -> None:
        """A subject line is content. Leaving it would withdraw the message and publish
        a summary of it, which is most of what the sender wanted gone."""
        await a_message(store)

        gone = await retraction.retract(store, "m1", AGENT, now=clock)

        assert gone.summary == retraction.TOMBSTONE


class TestItIsRetractedForEveryone:
    async def test_not_for_one_recipient_only(self, store: InMemoryStore) -> None:
        """FR-011, and the trap: a message delivered to several mailboxes is one stored
        object, so this holds by construction — but only while it stays that way."""
        await a_message(store)

        await retraction.retract(store, "m1", HUMAN, now=clock)

        seen = await store.get_object("m1")
        assert seen is not None
        assert seen.content == retraction.TOMBSTONE
        assert set(seen.to) == {OTHER, HUMAN}, "the audience was rewritten"


class TestTheAuditComesFirst:
    async def test_the_audit_survives_a_write_that_fails(
        self, store: InMemoryStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """**The ordering test, and the first attempt at it was worthless.**

        The first version asserted only that a log line existed — which it does in
        either order, so a removal proof that moved the audit *after* the write passed
        all seventeen tests. Order is the requirement, not the presence.

        This is what actually distinguishes them: make the write fail, and the audit
        must already be there. That is the whole point of the ordering — a retraction
        interrupted between the two steps leaves an audited non-retraction, which
        somebody can see and repeat, rather than a destroyed body nobody can account
        for.
        """
        await a_message(store)

        async def refuse(obj: ObjectRecord) -> None:
            raise OSError("the disk went away mid-retraction")

        store.add_object = refuse  # type: ignore[method-assign]

        # A handler on the module's own logger rather than `caplog`: this assertion is
        # the point of the test, and it must not be able to fail for a reason to do
        # with propagation or capture level.
        said: list[str] = []

        class Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                said.append(record.getMessage())

        handler = Collect()
        retraction.logger.addHandler(handler)
        try:
            with pytest.raises(OSError):
                await retraction.retract(store, "m1", HUMAN, now=clock)
        finally:
            retraction.logger.removeHandler(handler)

        assert any("message.retracted" in line for line in said), (
            "the write failed and left no trace that anything was attempted"
        )

        # And the body is still there, which is what makes the audited non-retraction
        # recoverable rather than merely recorded.
        survived = await store.get_object("m1")
        assert survived is not None
        assert survived.content != retraction.TOMBSTONE

    async def test_the_audit_names_who_and_whose(
        self, store: InMemoryStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FR-010: who did it, when, and which message."""
        await a_message(store)

        with caplog.at_level(logging.WARNING, logger="agent_inbox.retraction"):
            await retraction.retract(store, "m1", HUMAN, now=clock)

        entry = next(r for r in caplog.records if "message.retracted" in r.message)
        rendered = entry.getMessage()
        assert HUMAN in rendered, "the audit does not say who"
        assert AGENT in rendered, "the audit does not say whose message"
        assert "m1" in rendered, "the audit does not say which message"

    async def test_nothing_is_logged_when_it_is_refused(
        self, store: InMemoryStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The paired negative: an audit trail claiming retractions that never happened
        is worse than none, because somebody will act on it."""
        await a_message(store)

        with (
            caplog.at_level(logging.WARNING, logger="agent_inbox.retraction"),
            pytest.raises(retraction.NotYoursToRetract),
        ):
            await retraction.retract(store, "m1", OTHER, now=clock)

        assert not [r for r in caplog.records if "message.retracted" in r.message]

    async def test_the_body_is_not_in_the_log(
        self, store: InMemoryStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A log that accumulates everyone's withdrawn mail is a disclosure wearing an
        audit's clothes — and it would preserve exactly what was asked to be gone."""
        await a_message(store)

        with caplog.at_level(logging.WARNING, logger="agent_inbox.retraction"):
            await retraction.retract(store, "m1", AGENT, now=clock)

        assert not any(
            "nobody else should be able to destroy" in r.getMessage()
            for r in caplog.records
        )


class TestEdges:
    async def test_retracting_twice_is_not_an_error(self, store: InMemoryStore) -> None:
        """Two operators tidying the same thread should not produce a failure neither
        can act on. The caller asked for a state, and the state holds."""
        await a_message(store)
        await retraction.retract(store, "m1", HUMAN, now=clock)

        again = await retraction.retract(store, "m1", HUMAN, now=clock)

        assert retraction.is_retracted(again)
        assert retraction.retracted_by(again) == HUMAN, (
            "the first record was overwritten"
        )

    async def test_a_message_that_is_not_there(self, store: InMemoryStore) -> None:
        with pytest.raises(NoSuchMessage):
            await retraction.retract(store, "never-existed", HUMAN, now=clock)

    async def test_a_body_that_says_deleted_is_not_mistaken_for_a_retraction(
        self, store: InMemoryStore
    ) -> None:
        """Why the mark lives on the document rather than being sniffed from the text.
        Somebody will eventually send `[deleted]` as a joke, and it must not read as a
        withdrawn message — nor should it be missing its `who` and `when`."""
        await store.add_object(
            ObjectRecord(
                id="m9",
                attributed_to=AGENT,
                content=retraction.TOMBSTONE,
                summary=retraction.TOMBSTONE,
                published=STAMP,
            )
        )

        record = await store.get_object("m9")
        assert record is not None
        assert not retraction.is_retracted(record)


class TestTheRouteReachesIt:
    """The wiring, proved apart from the question — four times today a route has
    existed and never been reached.

    A retraction nobody can invoke is a feature that does not exist; a retraction
    invoked by the wrong person is worse than one that does not exist.
    """

    @staticmethod
    def _hub() -> tuple[object, object]:
        from litestar.testing import TestClient

        from agent_inbox.api import build_api
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox

        made = InMemoryStore()
        house = House(Mailbox(made, hub_name="testhub"))
        return TestClient(app=build_api(house, "http://hub.invalid")), made

    async def test_an_agent_can_retract_its_own_over_http(self) -> None:
        from agent_inbox.api import IDENTITY_HEADER

        client, made = self._hub()
        with client as c:  # type: ignore[attr-defined]
            for name, kind in ((AGENT, ActorType.SERVICE), (OTHER, ActorType.SERVICE)):
                await made.claim_name(
                    ActorRecord(
                        name=name, actor_type=kind, created=STAMP, last_seen=STAMP
                    )
                )
            await a_message(made)

            answer = c.post("/objects/m1/retract", headers={IDENTITY_HEADER: AGENT})

        assert answer.status_code == 200, answer.text
        assert answer.json()["retracted"] is True
        gone = await made.get_object("m1")
        assert gone is not None and retraction.is_retracted(gone)

    async def test_another_agent_is_refused_over_http(self) -> None:
        """The paired negative, and the one that matters: the route must not be a way
        around the permission test."""
        from agent_inbox.api import IDENTITY_HEADER

        client, made = self._hub()
        with client as c:  # type: ignore[attr-defined]
            for name in (AGENT, OTHER):
                await made.claim_name(
                    ActorRecord(
                        name=name,
                        actor_type=ActorType.SERVICE,
                        created=STAMP,
                        last_seen=STAMP,
                    )
                )
            await a_message(made)

            answer = c.post("/objects/m1/retract", headers={IDENTITY_HEADER: OTHER})

        assert answer.status_code >= 400, "an agent retracted somebody else's message"
        survived = await made.get_object("m1")
        assert survived is not None and not retraction.is_retracted(survived)

    async def test_the_answer_does_not_claim_it_reached_other_hubs(self) -> None:
        """FR-015. A client that inferred a federated withdrawal from this would be
        promising its human something the hub cannot do."""
        from agent_inbox.api import IDENTITY_HEADER

        client, made = self._hub()
        with client as c:  # type: ignore[attr-defined]
            await made.claim_name(
                ActorRecord(
                    name=AGENT,
                    actor_type=ActorType.SERVICE,
                    created=STAMP,
                    last_seen=STAMP,
                )
            )
            await a_message(made)

            said = c.post(
                "/objects/m1/retract", headers={IDENTITY_HEADER: AGENT}
            ).json()

        assert "this hub only" in said["scope"]
