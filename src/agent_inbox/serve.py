"""Running the hub.

Configuration is environment only — no config file, no flags. The hub is a container;
a container's contract is its environment, and anything else would need mounting.

Nothing here has a default that names a machine. `AGENT_MAILBOX_PUBLIC_URL` is how the
hub learns its own address, and it must be told (charter: no deployment-specific
hostnames in the repo). Everything else has a sensible default so a bare `docker run`
works.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timedelta

from litestar import Litestar

from agent_inbox.api import build_api
from agent_inbox.auth import secrets as auth_secrets
from agent_inbox.auth.service import INSECURE_ADMIN_WARNING, AuthService
from agent_inbox.auth.store import SqliteAuthStore
from agent_inbox.auth.throttle import LoginThrottle
from agent_inbox.delivery import FederatedDelivery
from agent_inbox.house import House
from agent_inbox.hub_settings import (
    env_with_source,
)
from agent_inbox.mailbox import Mailbox
from agent_inbox.sqlite_store import SqliteStore

logger = logging.getLogger(__name__)

#: The three ways the hub can treat identity. `off` trusts the header (the LAN default);
#: `warn` checks credentials and logs a missing one but serves; `enforce` refuses.
_AUTH_MODES = ("off", "warn", "enforce")


def _env(name: str, default: str) -> str:
    """A setting, by its current name or the one it used to have.

    The new name wins when both are set: an operator who has added `AGENT_INBOX_*` to a
    deployment that still carries the old variables is mid-migration, and the value they
    just wrote is the one they meant.
    """
    found = env_with_source(name, os.environ)
    return found[0].strip() if found else default.strip()


@dataclass(frozen=True, slots=True)
class Settings:
    """What the hub needs to know about where it is running."""

    db: str = "/data/agent-mailbox.db"
    host: str = "0.0.0.0"  # noqa: S104 - a container binds its own interface
    port: int = 8080
    #: How the hub refers to itself in the URIs it emits. If unset, callers still work
    #: — they just receive relative-looking identifiers, which is worse than being told.
    public_url: str = ""
    hub_name: str = "local"
    retention_days: int = 14
    #: How often the hub purges expired conversations, in minutes. 0 disables the
    #: schedule (retention_days = 0 disables expiry itself, whatever this says).
    purge_interval_minutes: int = 60
    log_level: str = "INFO"
    #: off | warn | enforce (see _AUTH_MODES). Default off keeps the LAN behaviour.
    auth_mode: str = "off"
    #: Fernet key for encrypting TOTP secrets at rest. Needed once 2FA is
    #: enrolled; never a default (charter: no secrets in the repo).
    secret_key: str = ""
    #: **Low-security mode.** When set, this value logs `admin` in directly — no second
    #: factor, whatever state the stored account is in — and that session can reset
    #: passwords and issue or revoke device tokens. It exists for manual testing and for
    #: getting back into a hub whose password or authenticator is lost.
    #:
    #: Anyone who can read the environment is then an administrator of this hub. It is
    #: never a default; the hub advertises it; the console shows a banner. Do not ship
    #: with it set.
    admin_password: str = ""
    #: Failed logins from one source before it is locked out for a while.
    login_max_failures: int = 5
    #: The lockout / sliding-window length, in minutes.
    login_lockout_minutes: int = 15
    #: Trust an upstream proxy's X-Forwarded-For for the client IP. Turn this on ONLY
    #: when the hub sits behind a proxy you control that sets the header — otherwise a
    #: client could spoof its source and dodge the throttle.
    trust_proxy: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        port = int(_env("PORT", "8080"))
        host = _env("HOST", "0.0.0.0")  # noqa: S104
        auth_mode = _env("AUTH_MODE", "off").lower()
        if auth_mode not in _AUTH_MODES:
            raise ValueError(
                "AGENT_MAILBOX_AUTH_MODE must be one of "
                f"{_AUTH_MODES}, not {auth_mode!r}"
            )
        return cls(
            db=_env("DB", "/data/agent-mailbox.db"),
            host=host,
            port=port,
            public_url=_env("PUBLIC_URL", "") or f"http://localhost:{port}",
            hub_name=_env("HUB_NAME", "local"),
            retention_days=int(_env("RETENTION_DAYS", "14")),
            purge_interval_minutes=int(_env("PURGE_INTERVAL_MINUTES", "60")),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            auth_mode=auth_mode,
            secret_key=_env("SECRET_KEY", ""),
            admin_password=_env("ADMIN_PASSWORD", ""),
            login_max_failures=int(_env("LOGIN_MAX_FAILURES", "5")),
            login_lockout_minutes=int(_env("LOGIN_LOCKOUT_MINUTES", "15")),
            trust_proxy=_env("TRUST_PROXY", "").lower() in ("1", "true", "yes"),
        )


def build_app(
    settings: Settings | None = None, *, reset_user_table: bool = False
) -> Litestar:
    """Build the hub, opening its store for the life of the application.

    The store is opened in a Litestar startup hook rather than here, so that building
    the app is cheap and testable and nothing touches the disk at import time.

    *reset_user_table* wipes the operator accounts on the way up — see
    :func:`main` for what that is for and why it is a one-shot.
    """
    config = settings or Settings.from_env()
    logging.basicConfig(level=config.log_level)

    store = SqliteStore(config.db)
    mailbox = Mailbox(
        store, hub_name=config.hub_name, retention_days=config.retention_days
    )
    # The delivery collaborator is what lets an agent address another hub. Injected
    # here, so a `House` built anywhere else refuses remote recipients rather than
    # dropping them.
    house = House(
        mailbox,
        deliver=FederatedDelivery(mailbox=mailbox, public_url=config.public_url),
    )

    # The auth service exists whenever a mode other than `off` is asked for. It
    # opens its own connection to the same SQLite file — WAL lets the two coexist,
    # and it keeps the auth tables cleanly separate from the messaging store.
    auth: AuthService | None = None
    auth_store: SqliteAuthStore | None = None
    if config.auth_mode != "off":
        key = config.secret_key or auth_secrets.generate_key()
        if not config.secret_key:
            logger.warning(
                "AGENT_MAILBOX_SECRET_KEY is unset — generated an ephemeral "
                "key. Set a stable key or 2FA enrolments will not survive a "
                "restart."
            )
        else:
            # Checked here, at startup, because the key is not used until someone
            # enrols — and a bad one then surfaces as a bare 500 on `GET /auth/enrol`,
            # at the worst possible moment: a new operator's first attempt to secure
            # the hub. Refusing to start says what is wrong while it can still be fixed.
            try:
                auth_secrets.encrypt_secret("startup check", key)
            except ValueError as exc:
                raise SystemExit(
                    f"{exc}\nThe hub will not start with an unusable key: 2FA "
                    "enrolment would fail later with an unexplained error."
                ) from exc
        auth_store = SqliteAuthStore(config.db)
        auth = AuthService(
            auth_store,
            secret_key=key,
            hub_name=config.hub_name,
            admin_password=config.admin_password,
        )
        if config.admin_password:
            # Said at startup as well as in the descriptor and the console, because
            # these are different audiences: whoever deploys the hub reads the log, and
            # may never open the console at all.
            logger.warning(
                "%s. AGENT_MAILBOX_ADMIN_PASSWORD is set: `admin` can sign in with it "
                "WITHOUT a second factor, and can then reset passwords and issue or "
                "revoke device tokens. Anyone who can read this hub's environment "
                "controls it. Intended for manual testing and for recovering a hub "
                "whose password or authenticator is lost — unset it afterwards.",
                INSECURE_ADMIN_WARNING,
            )

    throttle = LoginThrottle(
        max_failures=config.login_max_failures,
        window=timedelta(minutes=config.login_lockout_minutes),
        lockout=timedelta(minutes=config.login_lockout_minutes),
    )
    app = build_api(
        house,
        config.public_url,
        auth=auth,
        auth_mode=config.auth_mode,
        throttle=throttle,
        trust_proxy=config.trust_proxy,
        purge_interval_minutes=config.purge_interval_minutes,
    )

    async def open_store(_: Litestar) -> None:
        await store.__aenter__()
        if auth_store is not None:
            await auth_store.__aenter__()
        logger.info(
            "agent-inbox serving %s as %s, storing at %s (auth: %s)",
            config.public_url,
            config.hub_name,
            config.db,
            config.auth_mode,
        )

    async def bootstrap_admin(_: Litestar) -> None:
        if auth is None:
            return
        if reset_user_table:
            # Before bootstrap, so the seeding below is what refills the table. Said
            # loudly because leaving the flag on would empty it again on every restart
            # — an operator would enrol, restart for an unrelated reason, and be a
            # stranger to their own hub with no idea why.
            assert auth_store is not None
            await auth_store.reset_users()
            logger.warning(
                "--reset-user-table: deleted every operator account, recovery code "
                "and session. Device tokens and mail are untouched. REMOVE THE FLAG "
                "NOW — with it set, this happens on every start."
            )
        await auth.bootstrap()  # logs a password when the table is empty or unused

    async def close_store(_: Litestar) -> None:
        if auth_store is not None:
            await auth_store.__aexit__(None, None, None)
        await store.__aexit__(None, None, None)

    # Opening the store must come before the house opens, or the standing residents
    # would be created against a store that is not there yet.
    app.on_startup.insert(0, open_store)
    app.on_startup.append(bootstrap_admin)
    app.on_shutdown.append(close_store)
    return app


def main(*, reset_user_table: bool = False) -> None:
    """Entry point for the container and for `agent-inbox serve`.

    *reset_user_table* is the way back into a hub whose operator cannot log in: start
    once with it, read the fresh password out of the log, then **take it off**. It is a
    startup option rather than a route because the person entitled to do this is the
    one who can change how the hub is started — which is precisely the distinction
    authentication exists to draw.
    """
    import uvicorn

    config = Settings.from_env()
    uvicorn.run(
        build_app(config, reset_user_table=reset_user_table),
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
