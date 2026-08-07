"""Tokens have a kind, and the kind governs capability (issue #53, first ship).

The owner's objection that started this: the console had no credential, so the stopgap
was a static shared secret in a Fly secret, and *"a hard-coded secret can be easily
found"*.

**The argument the issue makes, and the one this file holds:** an eight-hour token that
can still send mail as any agent can impersonate the whole roster for eight hours.
Shortening a credential's life reduces the window; it does not reduce what fits through
it. So a kind must govern **capability**, not merely expiry — a kind that only changed a
lifetime would be a naming exercise.

Two kinds already existed, deduced from a sentinel in `actor`. Naming them must not
change what they mean: requirement 6 is that no deployment breaks because we named a
thing, and that is asserted here more than anything else.

Not in this ship, and deliberately: nothing yet *mints* a `ui` token at login, the TTL
is not yet a hub setting, and the Tokens page does not yet show a kind. The kind exists
and is enforced, which is coherent on its own — an unenforced kind minted everywhere
would be the worse half to ship first.
"""

from collections.abc import AsyncIterator

import pytest
from litestar.testing import TestClient

from agent_inbox.auth.exceptions import TokenExpired, TokenRevoked
from agent_inbox.auth.records import SHARED_ACTOR, DeviceToken, TokenKind
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import SqliteAuthStore


class TestExistingTokensAreUnchanged:
    """Requirement 6. Every one of these describes a token already in a live store."""

    def test_a_shared_token_is_an_agent_token(self) -> None:
        token = DeviceToken(id="1", actor=SHARED_ACTOR, token_hash="h")

        assert token.kind is TokenKind.AGENT

    def test_a_named_token_is_a_bound_token(self) -> None:
        token = DeviceToken(id="1", actor="igor_laszlo", token_hash="h")

        assert token.kind is TokenKind.BOUND

    def test_neither_expires(self) -> None:
        for actor in (SHARED_ACTOR, "igor_laszlo"):
            token = DeviceToken(id="1", actor=actor, token_hash="h")

            assert token.expires == ""
            assert not token.has_expired("2099-01-01T00:00:00Z")

    def test_both_may_still_act(self) -> None:
        """The paired positive for the whole capability idea. A change that made every
        token observe-only would satisfy every negative test below and break the hub
        for everyone."""
        for actor in (SHARED_ACTOR, "igor_laszlo"):
            assert DeviceToken(id="1", actor=actor, token_hash="h").may_act


class TestAUiTokenMayNotAct:
    def test_it_says_so(self) -> None:
        token = DeviceToken(id="1", actor="console", token_hash="h", kind=TokenKind.UI)

        assert not token.may_act

    def test_the_kind_is_not_inferred_away(self) -> None:
        """`__post_init__` derives a kind when none was given. It must not overwrite one
        that was — a `ui` token whose actor happens to be a name would otherwise be
        silently promoted to `bound`, which is a credential upgrade by accident."""
        token = DeviceToken(
            id="1", actor="igor_laszlo", token_hash="h", kind=TokenKind.UI
        )

        assert token.kind is TokenKind.UI
        assert not token.may_act


class TestExpiry:
    def test_a_token_past_its_expiry_has_expired(self) -> None:
        token = DeviceToken(
            id="1", actor="x", token_hash="h", expires="2026-01-01T00:00:00Z"
        )

        assert token.has_expired("2026-06-01T00:00:00Z")

    def test_before_its_expiry_it_has_not(self) -> None:
        token = DeviceToken(
            id="1", actor="x", token_hash="h", expires="2026-06-01T00:00:00Z"
        )

        assert not token.has_expired("2026-01-01T00:00:00Z")

    async def test_resolving_an_expired_token_refuses_by_name(
        self, service: AuthService, store: SqliteAuthStore
    ) -> None:
        """Requirement 2. Expired, revoked and unknown lead to different actions —
        an expired credential can usually be replaced by signing in again, a revoked one
        means a conversation with an operator. Reporting both as "not allowed" sends
        half the callers to the wrong person."""
        await store.add_token(
            DeviceToken(
                id="1",
                actor="x",
                token_hash=_hash("sec"),
                expires="2020-01-01T00:00:00Z",
            )
        )

        with pytest.raises(TokenExpired):
            await service.resolve_token("sec")

    async def test_revoked_still_wins_over_expired(
        self, service: AuthService, store: SqliteAuthStore
    ) -> None:
        """Order matters and is asserted rather than assumed: a revoked credential that
        gets as far as being reported as merely stale has been softened."""
        await store.add_token(
            DeviceToken(
                id="1",
                actor="x",
                token_hash=_hash("sec"),
                revoked=True,
                expires="2020-01-01T00:00:00Z",
            )
        )

        with pytest.raises(TokenRevoked):
            await service.resolve_token("sec")

    async def test_a_live_token_still_resolves(
        self, service: AuthService, store: SqliteAuthStore
    ) -> None:
        """The paired positive. Without it, an expiry check that refused everything
        would pass both tests above."""
        await store.add_token(
            DeviceToken(id="1", actor=SHARED_ACTOR, token_hash=_hash("sec"))
        )

        assert (await service.resolve_token("sec")) is not None


class TestTheStoreKeepsTheKind:
    async def test_it_round_trips(self, store: SqliteAuthStore) -> None:
        await store.add_token(
            DeviceToken(
                id="1",
                actor="console",
                token_hash="h",
                kind=TokenKind.UI,
                expires="2026-06-01T00:00:00Z",
            )
        )

        (stored,) = await store.all_tokens()

        assert stored.kind is TokenKind.UI
        assert stored.expires == "2026-06-01T00:00:00Z"

    async def test_a_row_written_before_these_columns_reads_back_unchanged(
        self, store: SqliteAuthStore
    ) -> None:
        """The migration case, and the one requirement 6 actually turns on. Simulated by
        writing the row the old code would have written — empty kind, empty expires —
        and asserting it comes back as the token it has always been."""
        await store._execute(  # noqa: SLF001 - reproducing a pre-migration row exactly
            "INSERT INTO auth_device_tokens "
            "(id, actor, token_hash, label, created, last_used, revoked) "
            "VALUES ('old', '*', 'h', '', '', NULL, 0)"
        )

        (stored,) = await store.all_tokens()

        assert stored.kind is TokenKind.AGENT
        assert stored.expires == ""
        assert stored.may_act


def _hash(secret: str) -> str:
    from agent_inbox.auth import secrets

    return secrets.hash_token(secret)


@pytest.fixture
async def store() -> AsyncIterator[SqliteAuthStore]:
    """A real SQLite auth store, in memory — the schema is what is under test."""
    async with SqliteAuthStore(":memory:") as opened:
        yield opened


@pytest.fixture
def service(store: SqliteAuthStore) -> AuthService:
    return AuthService(store, secret_key="k" * 32)


class TestAUiTokenIsRefusedByTheRoutesThatAct:
    """Requirement 5, asserted per route class rather than claimed in a docstring.

    The structural argument that makes this cheap: **every route that acts depends on a
    caller or an operator, and the observe routes depend on neither.** So there are
    exactly two places to enforce it, and a new sending route cannot forget — it cannot
    exist without asking for one of them.
    """

    def _hub(self) -> tuple[TestClient, AuthService]:
        from agent_inbox.api import build_api
        from agent_inbox.auth import secrets as auth_secrets
        from agent_inbox.auth.store import InMemoryAuthStore
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox
        from agent_inbox.store import InMemoryStore

        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        auth = AuthService(InMemoryAuthStore(), secret_key=auth_secrets.generate_key())
        app = build_api(house, "http://hub.invalid", auth=auth, auth_mode="enforce")
        return TestClient(app=app), auth

    async def _ui_token(self, auth: AuthService) -> str:
        secret = "a-console-secret"
        await auth._store.add_token(  # noqa: SLF001 - nothing mints these yet (ship 2)
            DeviceToken(
                id="ui-1",
                actor="console",
                token_hash=_hash(secret),
                kind=TokenKind.UI,
            )
        )
        return secret

    async def test_it_may_not_send(self) -> None:
        """The whole reason the kind governs capability. A credential that could still
        post a Note would impersonate the roster for as long as it lived, and shortening
        its life would not change that by one message."""
        from agent_inbox.api import IDENTITY_HEADER

        client, auth = self._hub()
        secret = await self._ui_token(auth)

        with client as c:
            answer = c.post(
                "/actors/somebody/outbox",
                json={"type": "Note", "to": ["somebody"], "content": "hello"},
                headers={
                    "Authorization": f"Bearer {secret}",
                    IDENTITY_HEADER: "somebody",
                },
            )

        assert answer.status_code == 401, answer.text

    async def test_it_may_not_administer(self) -> None:
        """Already true before this ship — `provide_operator` requires a *session*, and
        a token of any kind is not one. Asserted anyway, because "safe by construction"
        is a property of today's construction and this is the test that notices when
        somebody makes an admin route depend on a caller instead."""
        client, auth = self._hub()
        secret = await self._ui_token(auth)

        with client as c:
            answer = c.get("/operators", headers={"Authorization": f"Bearer {secret}"})

        assert answer.status_code == 401, answer.text

    async def test_an_agent_token_still_sends(self) -> None:
        """The paired positive, and the one that matters most: this must refuse a `ui`
        token without refusing the credential every agent on the hub is holding."""
        from agent_inbox.api import IDENTITY_HEADER

        client, auth = self._hub()
        secret = "an-agent-secret"
        await auth._store.add_token(  # noqa: SLF001 - matching the fixture above
            DeviceToken(id="ag-1", actor=SHARED_ACTOR, token_hash=_hash(secret))
        )

        with client as c:
            c.post(
                "/actors",
                json={"preferredUsername": "somebody_here"},
                headers={
                    "Authorization": f"Bearer {secret}",
                    IDENTITY_HEADER: "somebody_here",
                },
            )
            answer = c.post(
                "/actors/somebody_here/outbox",
                json={"type": "Note", "to": ["somebody_here"], "content": "hello"},
                headers={
                    "Authorization": f"Bearer {secret}",
                    IDENTITY_HEADER: "somebody_here",
                },
            )

        assert answer.status_code < 400, answer.text
