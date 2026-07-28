"""First-run bootstrap: the log line tools read, and the password an operator sets.

Two ways to get into a hub that has just been created, and both are load-bearing for
unattended setup — CI standing up an enforcing hub, or a scripted deployment.

The log prefix is asserted here because it is **a contract, not a log message**. Callers
scrape it to learn the password of a hub they have just built, and there is nothing else
for them to go on. Reword it in `service.py` and this test fails saying so — which is
the point, because the alternative is discovering it later as a failure to authenticate
somewhere unrelated, with the search starting in the wrong place.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from agent_mailbox.auth import secrets, totp
from agent_mailbox.auth.exceptions import BadCredentials
from agent_mailbox.auth.records import EnrolmentState
from agent_mailbox.auth.service import INITIAL_PASSWORD_LOG_PREFIX, AuthService
from agent_mailbox.auth.store import InMemoryAuthStore

KEY = secrets.generate_key()


def service() -> AuthService:
    return AuthService(
        InMemoryAuthStore(),
        secret_key=KEY,
        session_ttl=timedelta(hours=12),
        clock=lambda: datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC),
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
        anything scraping it, and `AGENT_MAILBOX_INITIAL_ADMIN_PASSWORD` is the
        supported alternative for those callers. Change it deliberately, and say so.
        """
        svc = service()
        with caplog.at_level(logging.WARNING, logger="agent_mailbox.auth"):
            password = await svc.bootstrap()

        assert password
        lines = [r.getMessage() for r in caplog.records]
        matching = [ln for ln in lines if ln.startswith(INITIAL_PASSWORD_LOG_PREFIX)]
        assert matching, (
            f"no log line began with {INITIAL_PASSWORD_LOG_PREFIX!r}; "
            f"saw {lines!r}. This prefix is a contract — see service.py."
        )
        # A scraper takes everything after the prefix up to the trailing advice.
        scraped = matching[0][len(INITIAL_PASSWORD_LOG_PREFIX) :].split(" ")[0]
        assert scraped == password, "the scraped value must be the usable password"

    async def test_the_scraped_password_actually_works(self) -> None:
        """The premise behind the contract: scraping is only useful if it logs in."""
        svc = service()
        password = await svc.bootstrap()
        assert password
        result = await svc.login("admin", password)
        assert result.enrolment_required, (
            "first-run login reaches enrolment and no more"
        )


class TestAnOperatorSuppliedPassword:
    async def test_a_supplied_password_is_used(self) -> None:
        svc = service()
        returned = await svc.bootstrap("correct horse battery staple")
        assert returned == "correct horse battery staple"
        result = await svc.login("admin", "correct horse battery staple")
        assert result.enrolment_required

    async def test_a_supplied_password_is_never_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It came from somewhere durable, so putting it in the log only spreads it."""
        svc = service()
        with caplog.at_level(logging.WARNING, logger="agent_mailbox.auth"):
            await svc.bootstrap("hunter2-but-longer")

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "hunter2-but-longer" not in logged
        assert INITIAL_PASSWORD_LOG_PREFIX not in logged

    async def test_blank_and_whitespace_fall_back_to_a_random_password(self) -> None:
        """An unset variable arrives as empty string; it must not be the password."""
        for blank in ("", "   "):
            svc = service()
            returned = await svc.bootstrap(blank)
            assert returned
            assert returned.strip() not in ("", *([blank] if blank.strip() else []))

    async def test_it_is_ignored_once_the_account_is_enrolled(self) -> None:
        """The safety property. Setup-time only, or it is a permanent backdoor.

        An operator who leaves the variable set in their deployment must not have their
        chosen password silently reinstated on the next restart — which would hand the
        hub back to anyone who ever saw that value.
        """
        svc = service()
        await svc.bootstrap("setup-time-password")
        await _enrol(svc, "the-real-password")

        assert await svc.bootstrap("setup-time-password") is None

        user = await svc._store.get_user("admin")
        assert user is not None
        assert user.enrolment_state is EnrolmentState.ACTIVE
        with pytest.raises(BadCredentials):
            await svc.login("admin", "setup-time-password")

    async def test_being_ignored_is_said_out_loud(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Silence would make a disarmed variable look like a backdoor that misfired."""
        svc = service()
        await svc.bootstrap("setup-time-password")
        await _enrol(svc, "the-real-password")

        with caplog.at_level(logging.WARNING, logger="agent_mailbox.auth"):
            await svc.bootstrap("setup-time-password")

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "INITIAL_ADMIN_PASSWORD" in logged and "ignored" in logged
        assert "setup-time-password" not in logged
