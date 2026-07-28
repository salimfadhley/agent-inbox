"""WP02 — the auth store contract, run against both adapters.

Parametrised so the in-memory and the SQLite adapter are held to exactly the same
behaviour. The two operations that carry correctness — spending a recovery code and
revoking a token — are each checked on their *negative* path (a second attempt
must fail),
because that atomicity is the whole reason they are single statements.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from agent_inbox.auth.records import DeviceToken, EnrolmentState, Session, User
from agent_inbox.auth.store import InMemoryAuthStore, SqliteAuthStore


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[object]:
    if request.param == "memory":
        yield InMemoryAuthStore()
    else:
        async with SqliteAuthStore(":memory:") as s:
            yield s


def _user(name: str = "admin") -> User:
    return User(username=name, password_hash="hash", created="2026-07-25T00:00:00Z")


def _token(tid: str, actor: str, token_hash: str) -> DeviceToken:
    return DeviceToken(
        id=tid,
        actor=actor,
        token_hash=token_hash,
        label="x",
        created="2026-07-25T00:00:00Z",
    )


class TestUsers:
    async def test_any_users_flips_when_the_first_is_added(self, store: object) -> None:
        assert await store.any_users() is False
        await store.add_user(_user())
        assert await store.any_users() is True

    async def test_round_trip_and_update(self, store: object) -> None:
        await store.add_user(_user())
        got = await store.get_user("admin")
        assert (
            got is not None
            and got.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL
        )
        await store.put_user(
            User(
                username="admin",
                password_hash="new",
                enrolment_state=EnrolmentState.ACTIVE,
                totp_secret_enc=b"cipher",
                created=got.created,
                last_login="2026-07-25T01:00:00Z",
            )
        )
        updated = await store.get_user("admin")
        assert updated is not None
        assert updated.enrolment_state is EnrolmentState.ACTIVE
        assert updated.totp_secret_enc == b"cipher"
        assert updated.last_login == "2026-07-25T01:00:00Z"

    async def test_unknown_user_is_none(self, store: object) -> None:
        assert await store.get_user("nobody") is None


class TestRecoveryCodes:
    async def test_a_code_is_spent_exactly_once(self, store: object) -> None:
        await store.add_user(_user())
        await store.add_recovery_codes("admin", ["h1", "h2", "h3"])
        assert await store.spend_recovery_code("admin", "h2") is True
        # second attempt on the same code fails — the atomicity that matters
        assert await store.spend_recovery_code("admin", "h2") is False
        # an unknown code fails
        assert await store.spend_recovery_code("admin", "nope") is False
        # a different code still works
        assert await store.spend_recovery_code("admin", "h1") is True

    async def test_rotation_replaces_the_set(self, store: object) -> None:
        await store.add_user(_user())
        await store.add_recovery_codes("admin", ["old"])
        await store.add_recovery_codes("admin", ["new"])
        assert await store.spend_recovery_code("admin", "old") is False
        assert await store.spend_recovery_code("admin", "new") is True


class TestDeviceTokens:
    async def test_mint_find_touch_revoke(self, store: object) -> None:
        await store.add_token(_token("t1", "jed_smith", "hashA"))
        found = await store.get_token_by_hash("hashA")
        assert found is not None and found.actor == "jed_smith"

        await store.touch_token("t1", "2026-07-25T02:00:00Z")
        assert (
            await store.get_token_by_hash("hashA")
        ).last_used == "2026-07-25T02:00:00Z"

        assert await store.revoke_token("t1") is True
        # revoking twice fails; the token now reads as revoked
        assert await store.revoke_token("t1") is False
        assert (await store.get_token_by_hash("hashA")).revoked is True

    async def test_tokens_for_lists_one_actors_tokens(self, store: object) -> None:
        await store.add_token(_token("t1", "jed_smith", "h1"))
        await store.add_token(_token("t2", "jed_smith", "h2"))
        await store.add_token(_token("t3", "trevor_mahmood", "h3"))
        jed = await store.tokens_for("jed_smith")
        assert {t.id for t in jed} == {"t1", "t2"}

    async def test_unknown_hash_is_none(self, store: object) -> None:
        assert await store.get_token_by_hash("missing") is None


class TestSessions:
    async def test_add_get_delete(self, store: object) -> None:
        await store.add_session(
            Session(
                id="s1", username="admin", created="c", expires="2099-01-01T00:00:00Z"
            )
        )
        got = await store.get_session("s1")
        assert got is not None and got.username == "admin"
        await store.delete_session("s1")
        assert await store.get_session("s1") is None

    async def test_expiry_is_data_not_enforced_here(self, store: object) -> None:
        # The store returns the row; deciding it is expired is the service's job.
        await store.add_session(
            Session(
                id="s2", username="admin", created="c", expires="2000-01-01T00:00:00Z"
            )
        )
        assert await store.get_session("s2") is not None


class TestResetUsers:
    """The escape hatch's storage half."""

    async def test_it_clears_operators_but_never_the_agents_tokens(
        self, store: Any
    ) -> None:
        """The distinction is the whole point of the name.

        "I cannot log in" must not become "every agent on the hub is locked out too" —
        device tokens belong to agents and have nothing to do with an operator who
        mistyped a password.
        """
        await store.add_user(User(username="admin", password_hash="h"))
        await store.add_recovery_codes("admin", ["a", "b"])
        await store.add_session(
            Session(
                id="s1", username="admin", created="", expires="2099-01-01T00:00:00"
            )
        )
        token = DeviceToken(
            id="t1", actor="rosemary_nasrin", token_hash="th", created="", label="x"
        )
        await store.add_token(token)

        await store.reset_users()

        assert await store.any_users() is False
        assert await store.get_session("s1") is None
        assert await store.spend_recovery_code("admin", "a") is False
        # the agent's credential survives
        assert await store.get_token_by_hash("th") is not None
