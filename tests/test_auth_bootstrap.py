"""First-run bootstrap, and the low-security admin override.

Two ways into a hub, with very different characters.

The log prefix is asserted because it is **a contract, not a log message**. Unattended
setup scrapes it to learn the password of a hub it has just built, and has nothing else
to go on. Reword it in `service.py` and this test fails saying so — which is the point,
because the alternative is discovering it later as a failure to authenticate somewhere
unrelated, with the search starting in the wrong place.

`AGENT_MAILBOX_ADMIN_PASSWORD` is the other way, and it is **deliberately insecure**.
The tests below pin the behaviour that makes it survivable: it is never on by default,
the hub advertises it, and it is announced in the log every time it is used. What they
do *not* do is pretend it is safe. It hands anyone who can read the environment an
administrator's session with no second factor — that is the feature, not a defect.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from agent_inbox.auth import secrets, totp
from agent_inbox.auth.exceptions import BadCredentials
from agent_inbox.auth.records import EnrolmentState
from agent_inbox.auth.service import (
    INITIAL_PASSWORD_LOG_PREFIX,
    INSECURE_ADMIN_WARNING,
    AuthService,
)
from agent_inbox.auth.store import InMemoryAuthStore

KEY = secrets.generate_key()
OVERRIDE = "let-me-in-please"


def service(admin_password: str = "") -> AuthService:
    return AuthService(
        InMemoryAuthStore(),
        secret_key=KEY,
        session_ttl=timedelta(hours=12),
        clock=lambda: datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC),
        admin_password=admin_password,
    )


async def _enrol(svc: AuthService, password: str) -> None:
    """Take the bootstrap admin all the way to ACTIVE."""
    offer = await svc.begin_enrolment("admin")
    secret = offer.provisioning_uri.split("secret=")[1].split("&")[0]
    await svc.complete_enrolment("admin", password, totp.current_code(secret))


class TestTheLoggedPassword:
    async def test_the_log_prefix_is_a_contract(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unattended setup reads the password back out of the container log.

        If you are here because you changed the wording: that is a breaking change for
        anything scraping it. Change it deliberately, and say so.
        """
        svc = service()
        with caplog.at_level(logging.WARNING, logger="agent_inbox.auth"):
            password = await svc.bootstrap()

        assert password
        lines = [r.getMessage() for r in caplog.records]
        matching = [ln for ln in lines if ln.startswith(INITIAL_PASSWORD_LOG_PREFIX)]
        assert matching, (
            f"no log line began with {INITIAL_PASSWORD_LOG_PREFIX!r}; "
            f"saw {lines!r}. This prefix is a contract — see service.py."
        )
        scraped = matching[0][len(INITIAL_PASSWORD_LOG_PREFIX) :].split(" ")[0]
        assert scraped == password, "the scraped value must be the usable password"

    async def test_the_scraped_password_actually_works(self) -> None:
        """The premise behind the contract: scraping is only useful if it logs in."""
        svc = service()
        password = await svc.bootstrap()
        assert password
        result = await svc.login("admin", password)
        assert result.enrolment_required, "first-run login reaches enrolment, no more"


class TestTheAdminOverrideIsOffUnlessAskedFor:
    async def test_off_by_default(self) -> None:
        svc = service()
        assert svc.admin_password_set is False
        await svc.bootstrap()
        with pytest.raises(BadCredentials):
            await svc.login("admin", OVERRIDE)

    async def test_whitespace_only_is_not_a_password(self) -> None:
        """An unset variable arrives as an empty string; it must not open the door."""
        for blank in ("", "   "):
            svc = service(blank)
            assert svc.admin_password_set is False
            await svc.bootstrap()
            with pytest.raises(BadCredentials):
                await svc.login("admin", blank)


class TestTheAdminOverrideWorks:
    async def test_it_signs_admin_in_with_no_second_factor(self) -> None:
        """The whole point: a way in that does not need the phone."""
        svc = service(OVERRIDE)
        await svc.bootstrap()
        await _enrol(svc, "the-real-password")

        result = await svc.login("admin", OVERRIDE)
        assert result.enrolment_required is False
        assert result.session is not None
        assert result.session.limited is False, "a full session, not an enrolment stub"

    async def test_it_works_even_before_anyone_enrols(self) -> None:
        """Recovering a hub nobody ever finished setting up is a real case."""
        svc = service(OVERRIDE)
        await svc.bootstrap()
        result = await svc.login("admin", OVERRIDE)
        assert result.enrolment_required is False

    async def test_the_stored_password_still_works_alongside_it(self) -> None:
        """The override is an extra door, not a replacement for the real one."""
        svc = service(OVERRIDE)
        await svc.bootstrap()
        await _enrol(svc, "the-real-password")
        offer_secret = await _secret_of(svc)

        result = await svc.login(
            "admin", "the-real-password", totp.current_code(offer_secret)
        )
        assert result.enrolment_required is False

    async def test_a_wrong_override_is_still_refused(self) -> None:
        svc = service(OVERRIDE)
        await svc.bootstrap()
        with pytest.raises(BadCredentials):
            await svc.login("admin", "not-the-override")

    async def test_it_does_not_apply_to_other_usernames(self) -> None:
        """It is a way back into `admin`, not a skeleton key for the hub."""
        svc = service(OVERRIDE)
        await svc.bootstrap()
        with pytest.raises(BadCredentials):
            await svc.login("someone_else", OVERRIDE)

    async def test_every_use_is_announced(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A sign-in that skipped 2FA must never be indistinguishable from one that did.

        This is the audit trail. Without it, the log of a hub running in low-security
        mode looks exactly like the log of a properly secured one.
        """
        svc = service(OVERRIDE)
        await svc.bootstrap()
        with caplog.at_level(logging.WARNING, logger="agent_inbox.auth"):
            await svc.login("admin", OVERRIDE)

        logged = " ".join(r.getMessage() for r in caplog.records)
        # `AGENT_INBOX_*` since 2026-08-09 (#63). The audit line names the variable an
        # operator would unset; naming the deprecated one sent them to a name that is
        # honoured but is not the one to be using.
        assert "AGENT_INBOX_ADMIN_PASSWORD" in logged
        assert "second factor" in logged
        assert OVERRIDE not in logged, "announce the use, never the value"


class TestItIsVisibleFromOutside:
    async def test_the_service_reports_it(self) -> None:
        assert service(OVERRIDE).admin_password_set is True
        assert service().admin_password_set is False

    def test_the_warning_wording_is_the_agreed_one(self) -> None:
        """One sentence, one wording — recognisable in a log and in a browser alike."""
        assert INSECURE_ADMIN_WARNING == (
            "Explicitly setting an admin password is insecure"
        )


async def _secret_of(svc: AuthService) -> str:
    """The enrolled TOTP secret, recovered the way the enrolment flow hands it over."""
    user = await svc._store.get_user("admin")
    assert user is not None and user.totp_secret_enc
    assert user.enrolment_state is EnrolmentState.ACTIVE
    return secrets.decrypt_secret(user.totp_secret_enc, KEY)
