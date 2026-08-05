"""One namespace: an operator account and a mailbox are the same identity.

Reverses an earlier decision (owner, 2026-08-05). Signing in as `admin` now gives you
the `admin` mailbox; that access is what the admin role means.

**The migration tests populate their store the old way and then migrate.** A migration
test that builds its store with the new code proves nothing — it exercises the
post-migration shape and calls it a pass, which is exactly the vacuous check this
project keeps meeting. So every fixture here creates operators through `AuthStore`
directly, as a hub deployed before this change would have them.
"""

from collections.abc import AsyncIterator

import pytest

from agent_inbox import merge
from agent_inbox.auth.exceptions import OperatorExists
from agent_inbox.auth.records import EnrolmentState, User
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore
from agent_inbox.exceptions import NameUnavailable
from agent_inbox.records import ActorRecord, ActorType
from agent_inbox.store import InMemoryStore

STAMP = "2026-08-05T00:00:00+00:00"


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


async def old_operator(auth: AuthService, username: str) -> None:
    """An operator as a hub deployed before this change would hold one.

    Straight into the store, bypassing every rule added since — which is the whole
    point. `add_operator` would refuse `sal.fadhley` today, so building the fixture
    through it could never produce the case the migration exists for.
    """
    await auth._store.add_user(  # noqa: SLF001 - deliberately behind the service
        User(
            username=username,
            password_hash="x",
            enrolment_state=EnrolmentState.ACTIVE,
            created=STAMP,
        )
    )


async def agent_joined(store: InMemoryStore, name: str) -> None:
    await store.claim_name(
        ActorRecord(
            name=name, actor_type=ActorType.SERVICE, created=STAMP, last_seen=STAMP
        )
    )


class TestMakingAHuman:
    async def test_a_human_gets_an_account_and_a_mailbox(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        await merge.create_human(auth, store, "ludmila", now=clock)

        assert await auth._store.get_user("ludmila") is not None  # noqa: SLF001
        assert await store.get_actor("ludmila") is not None

    async def test_the_one_time_password_works(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        password = await merge.create_human(auth, store, "ludmila", now=clock)

        result = await auth.login("ludmila", password)

        assert result.enrolment_required

    async def test_a_name_an_agent_holds_is_refused(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """One namespace. The whole point: a name an agent holds is not available."""
        await agent_joined(store, "parisa_murthy")

        with pytest.raises(OperatorExists):
            await merge.create_human(auth, store, "parisa_murthy", now=clock)

    async def test_a_refused_human_leaves_nothing_behind(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """The negative that matters. A half-created human — an account that can sign in
        with no mailbox — is the state in which everything downstream looks broken for
        the wrong reason."""
        await agent_joined(store, "parisa_murthy")

        with pytest.raises(OperatorExists):
            await merge.create_human(auth, store, "parisa_murthy", now=clock)

        assert await auth._store.get_user("parisa_murthy") is None  # noqa: SLF001

    async def test_an_unusable_username_is_still_refused(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """The 0.60.0 rule still applies through this path — it is not bypassed by
        going through the coordinator."""
        with pytest.raises(NameUnavailable):
            await merge.create_human(auth, store, "sal.fadhley", now=clock)


class TestAdoptingOperatorsThatAlreadyExist:
    async def test_an_existing_operator_gains_a_mailbox(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        await old_operator(auth, "ludmila")

        report = await merge.adopt_existing(auth, store, now=clock)

        assert await store.get_actor("ludmila") is not None
        assert "ludmila" in report.claimed

    async def test_the_seeded_admin_gains_its_mailbox(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """FR-013, and the account the whole reversal exists to serve."""
        report = await merge.adopt_existing(auth, store, now=clock)

        assert await store.get_actor("admin") is not None
        assert "admin" in report.claimed

    async def test_running_it_twice_changes_nothing(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """It runs at every startup. A second run that renamed or re-claimed would be a
        migration that damages a hub for staying up."""
        await old_operator(auth, "sal.fadhley")
        first = await merge.adopt_existing(auth, store, now=clock)

        second = await merge.adopt_existing(auth, store, now=clock)

        assert first.renamed and not second.renamed
        assert not second.claimed
        assert set(second.already) == {"admin", "sal_fadhley"}


class TestRenaming:
    async def test_a_username_no_actor_could_hold_is_renamed(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        await old_operator(auth, "sal.fadhley")

        report = await merge.adopt_existing(auth, store, now=clock)

        assert report.renamed == (merge.Renamed(was="sal.fadhley", now="sal_fadhley"),)
        assert await auth._store.get_user("sal_fadhley") is not None  # noqa: SLF001
        assert await auth._store.get_user("sal.fadhley") is None  # noqa: SLF001

    async def test_the_renamed_account_keeps_everything_about_the_person(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """A rename that silently reset somebody's password or enrolment would lock them
        out just as thoroughly as losing the account."""
        await old_operator(auth, "sal.fadhley")

        await merge.adopt_existing(auth, store, now=clock)

        moved = await auth._store.get_user("sal_fadhley")  # noqa: SLF001
        assert moved is not None
        assert moved.password_hash == "x"
        assert moved.enrolment_state is EnrolmentState.ACTIVE
        assert moved.created == STAMP

    async def test_an_already_valid_username_is_not_renamed(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """The paired positive. Without it every assertion above would pass on a
        migration that renamed everybody."""
        await old_operator(auth, "ludmila")

        report = await merge.adopt_existing(auth, store, now=clock)

        assert not report.renamed
        assert await auth._store.get_user("ludmila") is not None  # noqa: SLF001

    async def test_both_names_are_reported_together(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """The cost of the chosen option is that a login changes and somebody finds
        out when it stops working. The report pays that down, so it names the old
        spelling as well as the new — old alone is a puzzle, new alone is a shrug."""
        await old_operator(auth, "sal.fadhley")

        report = await merge.adopt_existing(auth, store, now=clock)
        said = " ".join(report.lines())

        assert "sal.fadhley" in said
        assert "sal_fadhley" in said


class TestCollisions:
    async def test_a_collision_is_refused_rather_than_merged(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """Merging joins two people's mail, and nothing afterwards can tell them apart
        again. Both accounts are left exactly as they were."""
        await old_operator(auth, "sal_fadhley")
        await old_operator(auth, "sal.fadhley")

        report = await merge.adopt_existing(auth, store, now=clock)

        assert not report.renamed
        assert [c.was for c in report.collisions] == ["sal.fadhley"]
        assert await auth._store.get_user("sal.fadhley") is not None  # noqa: SLF001
        assert await auth._store.get_user("sal_fadhley") is not None  # noqa: SLF001

    async def test_a_collision_with_an_agent_is_refused_too(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """NFR-003: no existing agent loses its name. A rename onto an agent's name
        would take it — which is the one thing this mission promised not to do."""
        await agent_joined(store, "sal_fadhley")
        await old_operator(auth, "sal.fadhley")

        report = await merge.adopt_existing(auth, store, now=clock)

        assert [c.was for c in report.collisions] == ["sal.fadhley"]
        agent = await store.get_actor("sal_fadhley")
        assert agent is not None
        assert agent.created == STAMP, "the agent's own record was overwritten"

    async def test_one_collision_does_not_block_the_rest(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """One bad account must not stop a hub migrating; everyone else goes through."""
        await old_operator(auth, "sal_fadhley")
        await old_operator(auth, "sal.fadhley")
        await old_operator(auth, "ludmila")

        report = await merge.adopt_existing(auth, store, now=clock)

        assert report.collisions
        assert await store.get_actor("ludmila") is not None
        assert report.needs_a_human

    async def test_the_refusal_names_both_accounts(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        await old_operator(auth, "sal_fadhley")
        await old_operator(auth, "sal.fadhley")

        said = " ".join((await merge.adopt_existing(auth, store, now=clock)).lines())

        assert "sal.fadhley" in said
        assert "sal_fadhley" in said
        assert "NOT migrated" in said


class TestNoAgentLosesAnything:
    async def test_agents_keep_their_names_through_a_migration(
        self, auth: AuthService, store: InMemoryStore
    ) -> None:
        """NFR-003, against a store populated before the change."""
        for name in ("parisa_murthy", "igor_laszlo", "mariana_taphrale"):
            await agent_joined(store, name)
        await old_operator(auth, "sal.fadhley")

        await merge.adopt_existing(auth, store, now=clock)

        for name in ("parisa_murthy", "igor_laszlo", "mariana_taphrale"):
            actor = await store.get_actor(name)
            assert actor is not None, f"{name} lost its name to the migration"
            assert actor.actor_type is ActorType.SERVICE


class TestTheHubActuallyRunsIt:
    """The wiring, proved separately from the question.

    Everything above proves `adopt_existing` answers correctly. This proves the hub
    *calls* it — a different failure, and the one that leaves a working migration nobody
    ever benefits from. The same split caught a real gap in `doctor` earlier today:
    with the call deleted the module tests all stayed green.
    """

    async def test_starting_the_hub_gives_existing_operators_their_mailboxes(
        self,
    ) -> None:
        from litestar.testing import TestClient

        from agent_inbox.api import build_api
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox

        store = InMemoryStore()
        auth = AuthService(InMemoryAuthStore(), secret_key="k" * 44)
        await auth.bootstrap()
        await old_operator(auth, "sal.fadhley")
        house = House(Mailbox(store, hub_name="testhub"))
        app = build_api(house, "http://hub.invalid", auth=auth, auth_mode="enforce")

        with TestClient(app=app):
            pass  # startup is the whole exercise

        assert await store.get_actor("sal_fadhley") is not None, (
            "the hub started without adopting its existing operators"
        )
        assert await store.get_actor("admin") is not None
        # The paired positive: the migration ran, rather than the store having simply
        # acquired actors by some other route.
        assert await auth._store.get_user("sal.fadhley") is None  # noqa: SLF001
