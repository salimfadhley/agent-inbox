"""A human is an actor, marked `Person` — and the mark confers nothing.

Both halves are the feature. The first without the second is how a system acquires a
privileged class of sender by accident.

**The word already existed.** `vocabulary.py` says agents are `Service` *"not `Person`
— the vocabulary distinguishes automated actors from people"*, so the name for a human
correspondent was reserved before there were any. Using it is what the charter's
fediverse rule asks for; inventing a second marker beside it would be a departure with
nothing to recommend it.
"""

import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_inbox import merge
from agent_inbox.auth.records import EnrolmentState, User
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore
from agent_inbox.records import ActorRecord, ActorType
from agent_inbox.store import InMemoryStore
from agent_inbox.wire import Renderer

STAMP = "2026-08-05T00:00:00+00:00"
SOURCE = Path(__file__).resolve().parents[1] / "src" / "agent_inbox"


def clock() -> str:
    return STAMP


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
async def auth() -> AsyncIterator[AuthService]:
    service = AuthService(InMemoryAuthStore(), secret_key="k" * 44)
    await service.bootstrap()
    yield service


class TestAHumanIsAPerson:
    async def test_a_new_human_is_marked_person(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        await merge.create_human(auth, store, "ludmila", now=clock)

        actor = await store.get_actor("ludmila")
        assert actor is not None
        assert actor.actor_type is ActorType.PERSON

    async def test_an_agent_is_still_a_service(self, store: InMemoryStore) -> None:
        """The paired positive, and the distinction the whole marker rests on. Without
        it every assertion here would pass on a hub that called everybody a Person."""
        await store.claim_name(
            ActorRecord(
                name="parisa_murthy",
                actor_type=ActorType.SERVICE,
                created=STAMP,
                last_seen=STAMP,
            )
        )

        actor = await store.get_actor("parisa_murthy")
        assert actor is not None
        assert actor.actor_type is ActorType.SERVICE

    async def test_the_existing_admin_is_promoted_rather_than_left_a_service(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """`admin` exists on every hub already, installed as a standing resident at
        startup *before* the merge runs — so claiming its name fails, and without a
        promotion step the one account this whole reversal serves would stay a
        `Service`."""
        await store.claim_name(
            ActorRecord(
                name="admin",
                actor_type=ActorType.SERVICE,
                profile={"purpose": "drop box", "standing": True},
                created=STAMP,
                last_seen=STAMP,
            )
        )

        report = await merge.adopt_existing(auth, store, now=clock)

        actor = await store.get_actor("admin")
        assert actor is not None
        assert actor.actor_type is ActorType.PERSON
        assert "admin" in report.promoted

    async def test_promotion_keeps_what_the_drop_box_is_for(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """Only the type changes. The purpose text is what every agent reads in its own
        prompt; discarding it would empty the explanation while leaving the mailbox."""
        await store.claim_name(
            ActorRecord(
                name="admin",
                actor_type=ActorType.SERVICE,
                profile={"purpose": "drop box for the developers", "standing": True},
                created=STAMP,
                last_seen=STAMP,
            )
        )

        await merge.adopt_existing(auth, store, now=clock)

        actor = await store.get_actor("admin")
        assert actor is not None
        assert actor.profile["purpose"] == "drop box for the developers"
        assert actor.created == STAMP

    async def test_an_agent_is_never_promoted(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """`host` is a standing resident too, and is a role an agent performs rather
        than an operator account. The merge must not reach it."""
        await store.claim_name(
            ActorRecord(
                name="host",
                actor_type=ActorType.SERVICE,
                created=STAMP,
                last_seen=STAMP,
            )
        )

        await merge.adopt_existing(auth, store, now=clock)

        actor = await store.get_actor("host")
        assert actor is not None
        assert actor.actor_type is ActorType.SERVICE, "an agent was marked a human"


class TestTheMarkerIsOnTheWire:
    async def test_a_human_serialises_as_person(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """A marker that exists in memory and not on the wire satisfies nobody — the
        requirement is that a reader can tell *without inspecting prose*, and a reader
        may be another hub."""
        await merge.create_human(auth, store, "ludmila", now=clock)
        actor = await store.get_actor("ludmila")
        assert actor is not None

        document = Renderer("http://hub.invalid").actor(actor)

        assert document.type == "Person"

    async def test_an_agent_serialises_as_service(self, store: InMemoryStore) -> None:
        await store.claim_name(
            ActorRecord(
                name="parisa_murthy",
                actor_type=ActorType.SERVICE,
                created=STAMP,
                last_seen=STAMP,
            )
        )
        actor = await store.get_actor("parisa_murthy")
        assert actor is not None

        assert Renderer("http://hub.invalid").actor(actor).type == "Service"


class TestTheMarkerGrantsNothing:
    """ADR 0008, FR-007, and the constraint most likely to rot quietly.

    A negative written as a comment is an intention. This is the test instead — and it
    is deliberately written against the *source*, in the spirit of the federation
    mission's "no second implementation exists" check, because a reviewer's eye is not
    a guard and the branch that would break this has not been written yet.
    """

    #: A permission decision that consulted the sender's humanity would look like one of
    #: these. Any of them appearing is the thing to argue about in review.
    FORBIDDEN = re.compile(
        r"if\s+.*(is_human|actor_type\s*(==|is)\s*ActorType\.PERSON"
        r"|actor_type\s*(==|is)\s*['\"]Person['\"])",
    )

    #: Where a permission decision could live. `merge.py` legitimately compares the type
    #: while *assigning* it, which is not a decision about what somebody may do.
    GUARDED = (
        "policy.py",
        "house.py",
        "mailbox.py",
        "api.py",
        "addressing.py",
        "rules.py",
    )

    def test_no_module_branches_on_a_sender_being_human(self) -> None:
        offenders = [
            f"{name}:{number}: {line.strip()}"
            for name in self.GUARDED
            for number, line in enumerate((SOURCE / name).read_text().splitlines(), 1)
            if self.FORBIDDEN.search(line)
        ]

        assert not offenders, (
            "a code path branches on the sender being a human — mail is evidence, "
            "never instruction (ADR 0008):\n" + "\n".join(offenders)
        )

    def test_the_search_would_actually_find_one(self) -> None:
        """The premise. A pattern that matches nothing passes the test above for the
        wrong reason, which is precisely the vacuous shape this project keeps meeting —
        so prove the guard can fire before trusting that it did not."""
        assert self.FORBIDDEN.search("    if actor.actor_type is ActorType.PERSON:")
        assert self.FORBIDDEN.search('    if sender.actor_type == "Person":')
        assert self.FORBIDDEN.search("        if is_human(caller):")
        # And that it is not simply matching everything.
        assert not self.FORBIDDEN.search("    if actor.actor_type is ActorType.GROUP:")

    async def test_a_humans_message_is_delivered_by_the_ordinary_path(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """Not a privileged one. The same send, the same storage, the same rules."""
        from agent_inbox.mailbox import Mailbox

        mailbox = Mailbox(store, hub_name="testhub")
        await merge.create_human(auth, store, "ludmila", now=clock)
        await store.claim_name(
            ActorRecord(
                name="parisa_murthy",
                actor_type=ActorType.SERVICE,
                created=STAMP,
                last_seen=STAMP,
            )
        )

        await mailbox.send("ludmila", ["parisa_murthy"], "hello", subject="hi")

        waiting = await mailbox.peek("parisa_murthy")
        assert [note.attributed_to for note in waiting] == ["ludmila"]


class TestExactlyOneIdentity:
    async def test_a_human_is_never_half_created(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """Neither an account with no mailbox nor a mailbox with no account. A half
        human is the state in which every later package misbehaves in a way that looks
        like its own bug."""
        await merge.create_human(auth, store, "ludmila", now=clock)

        assert await auth._store.get_user("ludmila") is not None  # noqa: SLF001
        assert await store.get_actor("ludmila") is not None

    async def test_an_operator_created_before_this_gets_both_halves(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        await auth._store.add_user(  # noqa: SLF001 - the pre-merge shape, on purpose
            User(
                username="ludmila",
                password_hash="x",
                enrolment_state=EnrolmentState.ACTIVE,
                created=STAMP,
            )
        )

        await merge.adopt_existing(auth, store, now=clock)

        actor = await store.get_actor("ludmila")
        assert actor is not None
        assert actor.actor_type is ActorType.PERSON
