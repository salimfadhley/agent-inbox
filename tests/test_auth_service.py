"""WP03 — the auth service, over the in-memory store with a controllable clock.

The subtle paths get the attention: the generic-failure that hides user-vs-password, the
enrolment gate that lets a first-run account do nothing but enrol, single-use recovery
codes, token resolution and revocation, and session expiry against an injected clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_mailbox.auth import secrets, totp
from agent_mailbox.auth.exceptions import BadCredentials, TokenRevoked
from agent_mailbox.auth.records import EnrolmentState
from agent_mailbox.auth.service import AuthService
from agent_mailbox.auth.store import InMemoryAuthStore

KEY = secrets.generate_key()


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t = self.t + timedelta(**kw)


def service(clock: Clock | None = None) -> AuthService:
    return AuthService(
        InMemoryAuthStore(),
        secret_key=KEY,
        session_ttl=timedelta(hours=12),
        clock=clock or Clock(),
    )


async def _enrol_admin(svc: AuthService, password: str = "realpassword") -> str:
    """Drive the bootstrap admin all the way to active; return its TOTP secret."""
    await svc.bootstrap()
    offer = await svc.begin_enrolment("admin")
    # recover the secret from the provisioning URI to compute a valid code
    secret = offer.provisioning_uri.split("secret=")[1].split("&")[0]
    await svc.complete_enrolment("admin", password, totp.current_code(secret))
    return secret


class TestBootstrap:
    async def test_seeds_once_and_logs_the_password(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        svc = service()
        with caplog.at_level("WARNING"):
            pw = await svc.bootstrap()
        assert pw is not None
        assert any("initial admin password" in r.message for r in caplog.records)
        # idempotent: a second call with a user present seeds nothing
        assert await svc.bootstrap() is None

    async def test_bootstrap_account_must_enrol(self) -> None:
        svc = service()
        pw = await svc.bootstrap()
        assert pw is not None
        result = await svc.login("admin", pw)
        assert result.enrolment_required is True
        assert result.session.limited is True


class TestLogin:
    async def test_wrong_user_and_wrong_password_are_indistinguishable(self) -> None:
        svc = service()
        await svc.bootstrap()
        with pytest.raises(BadCredentials) as a:
            await svc.login("admin", "wrong")
        with pytest.raises(BadCredentials) as b:
            await svc.login("nobody", "wrong")
        assert str(a.value) == str(b.value)

    async def test_enrolled_login_needs_the_second_factor(self) -> None:
        svc = service()
        secret = await _enrol_admin(svc)
        # right password, no OTP → refused
        with pytest.raises(BadCredentials):
            await svc.login("admin", "realpassword")
        # right password + valid OTP → full session
        result = await svc.login("admin", "realpassword", totp.current_code(secret))
        assert result.enrolment_required is False
        assert result.session.limited is False

    async def test_a_recovery_code_works_once(self) -> None:
        svc = service()
        await svc.bootstrap()
        offer = await svc.begin_enrolment("admin")
        secret = offer.provisioning_uri.split("secret=")[1].split("&")[0]
        await svc.complete_enrolment("admin", "realpassword", totp.current_code(secret))
        code = offer.recovery_codes[0]
        # a recovery code satisfies the second factor...
        assert (await svc.login("admin", "realpassword", code)).session.limited is False
        # ...but only once
        with pytest.raises(BadCredentials):
            await svc.login("admin", "realpassword", code)


class TestSessions:
    async def test_session_resolves_then_expires(self) -> None:
        clock = Clock()
        svc = service(clock)
        secret = await _enrol_admin(svc)
        result = await svc.login("admin", "realpassword", totp.current_code(secret))
        sid = result.session.id
        assert (await svc.resolve_session(sid)).username == "admin"
        clock.advance(hours=13)  # past the 12h TTL
        assert await svc.resolve_session(sid) is None

    async def test_logout_invalidates(self) -> None:
        svc = service()
        secret = await _enrol_admin(svc)
        sid = (
            await svc.login("admin", "realpassword", totp.current_code(secret))
        ).session.id
        await svc.logout(sid)
        assert await svc.resolve_session(sid) is None


class TestAccount:
    async def test_change_password_requires_the_current_one(self) -> None:
        svc = service()
        await _enrol_admin(svc, password="first")
        with pytest.raises(BadCredentials):
            await svc.change_password("admin", "wrong", "second")
        await svc.change_password("admin", "first", "second")
        secret = (await svc._store.get_user("admin")).totp_secret_enc
        assert secret is not None  # 2FA survives a password change

    async def test_completed_enrolment_is_active(self) -> None:
        svc = service()
        await _enrol_admin(svc)
        user = await svc._store.get_user("admin")
        assert user is not None and user.enrolment_state is EnrolmentState.ACTIVE


class TestDeviceTokens:
    async def test_mint_resolve_revoke(self) -> None:
        svc = service()
        minted = await svc.mint_token("jed_smith", label="workshop")
        assert minted.actor == "jed_smith"
        # the secret resolves to the actor
        assert await svc.resolve_token(minted.secret) == "jed_smith"
        # an unknown secret resolves to None
        assert await svc.resolve_token(secrets.generate_token()) is None
        # revoke → the same secret is now refused
        assert await svc.revoke_token(minted.id) is True
        with pytest.raises(TokenRevoked):
            await svc.resolve_token(minted.secret)

    async def test_list_shows_metadata_not_the_secret(self) -> None:
        svc = service()
        await svc.mint_token("jed_smith", label="a")
        await svc.mint_token("jed_smith", label="b")
        tokens = await svc.list_tokens("jed_smith")
        assert {t.label for t in tokens} == {"a", "b"}
        assert all(not hasattr(t, "secret") for t in tokens)
