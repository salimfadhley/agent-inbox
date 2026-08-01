"""WP03 — the auth service, over the in-memory store with a controllable clock.

The subtle paths get the attention: the generic-failure that hides user-vs-password, the
enrolment gate that lets a first-run account do nothing but enrol, single-use recovery
codes, token resolution and revocation, and session expiry against an injected clock.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent_inbox.auth import secrets, totp
from agent_inbox.auth.exceptions import BadCredentials, TokenRevoked
from agent_inbox.auth.records import EnrolmentState
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore

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
        # It does NOT go quiet on the second call. That used to be the rule, and it
        # cost a real hub its only credential when the container holding the log was
        # replaced. It stays noisy until the account is genuinely set up — see
        # TestBootstrapKeepsPrinting for the whole of that behaviour.
        assert await svc.bootstrap() is not None

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


class TestBootstrapKeepsPrinting:
    """A password nobody can read is the same as no password at all."""

    async def test_it_issues_a_new_password_while_the_admin_is_unset_up(self) -> None:
        """The failure this exists for: the log was rotated away with the container.

        A hub seeded its admin in July, the container was later replaced, and the only
        credential to it went with the log. The hash is one-way, so nothing could get
        it back. While the account is still un-onboarded it has no powers worth
        stealing, so re-issuing beats being locked out.
        """
        store = InMemoryAuthStore()
        svc = AuthService(store, secret_key=KEY)
        first = await svc.bootstrap()
        assert first
        second = await svc.bootstrap()
        assert second and second != first, "a fresh password each boot until set up"
        # and the new one is the one that works
        await svc.login("admin", second)

    async def test_it_goes_quiet_once_the_admin_is_properly_set_up(self) -> None:
        """Once a real operator finishes enrolling, printing stops for good."""
        store = InMemoryAuthStore()
        svc = AuthService(store, secret_key=KEY)
        password = await svc.bootstrap()
        assert password
        user = await store.get_user("admin")
        assert user is not None
        await store.put_user(replace(user, enrolment_state=EnrolmentState.ACTIVE))
        assert await svc.bootstrap() is None


class TestResetUser:
    """The way back in for an operator locked out of their own hub."""

    async def test_it_restores_first_run_and_clears_the_authenticator(self) -> None:
        """A lost phone must not leave the account permanently unreachable.

        So the old TOTP secret goes: keeping it would mean the reset let you past the
        password and then stopped you at a device you no longer have.
        """
        svc = service()
        await _enrol_admin(svc, password="theirs")
        fresh = await svc.reset_user()
        user = await svc._store.get_user("admin")
        assert user is not None
        assert user.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL
        assert user.totp_secret_enc is None
        # the new password works, with no second factor, and asks for enrolment
        result = await svc.login("admin", fresh)
        assert result.enrolment_required is True

    async def test_the_old_password_stops_working(self) -> None:
        svc = service()
        await _enrol_admin(svc, password="theirs")
        await svc.reset_user()
        with pytest.raises(BadCredentials):
            await svc.login("admin", "theirs")


class TestLoginFailuresAreExplainedInTheLog:
    """The browser is told nothing; the operator is told which factor failed."""

    async def test_a_wrong_password_says_so_in_the_log_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        svc = service()
        await _enrol_admin(svc, password="right")
        with caplog.at_level("WARNING"), pytest.raises(BadCredentials) as exc:
            await svc.login("admin", "wrong", "000000")
        assert "incorrect username or password" in str(exc.value)
        assert any("wrong password" in r.getMessage() for r in caplog.records)

    async def test_a_missing_second_factor_is_distinguished_from_a_bad_one(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No code typed, and a code rejected, call for different fixes."""
        svc = service()
        await _enrol_admin(svc, password="right")
        with caplog.at_level("WARNING"), pytest.raises(BadCredentials):
            await svc.login("admin", "right")
        assert any("not supplied" in r.getMessage() for r in caplog.records)
        caplog.clear()
        with caplog.at_level("WARNING"), pytest.raises(BadCredentials):
            await svc.login("admin", "right", "000000")
        assert any("did not match" in r.getMessage() for r in caplog.records)


class TestEnrolmentProvesTheAuthenticatorWorks:
    """Enrolment must not complete on an unproven authenticator."""

    async def test_a_wrong_code_does_not_enrol(self) -> None:
        """Otherwise an operator locks themselves out at the moment they think they
        are securing the hub: password changed, 2FA required, and a phone that was
        never actually verified against the secret.
        """
        svc = service()
        await svc.bootstrap()
        await svc.begin_enrolment("admin")
        with pytest.raises(BadCredentials):
            await svc.complete_enrolment("admin", "newpassword", "000000")
        user = await svc._store.get_user("admin")
        assert user is not None
        # nothing moved: still first-run, and the new password was not adopted
        assert user.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL
        with pytest.raises(BadCredentials):
            await svc.login("admin", "newpassword")

    async def test_the_authenticator_entry_names_the_hub(self) -> None:
        """A phone accumulates these. `agent-inbox: admin` is ambiguous the moment
        someone runs a second hub; the hub's name is what tells them apart.
        """
        svc = AuthService(InMemoryAuthStore(), secret_key=KEY, hub_name="examplehub")
        await svc.bootstrap()
        offer = await svc.begin_enrolment("admin")
        assert "issuer=agent-inbox" in offer.provisioning_uri
        # pyotp leaves the slash literal (it double-encodes a pre-encoded
        # name), which is what authenticator apps display as the account.
        assert "agent-inbox:examplehub/admin" in offer.provisioning_uri
