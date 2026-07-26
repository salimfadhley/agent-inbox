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

from agent_mailbox.api import build_api
from agent_mailbox.auth import secrets as auth_secrets
from agent_mailbox.auth.service import AuthService
from agent_mailbox.auth.store import SqliteAuthStore
from agent_mailbox.auth.throttle import LoginThrottle
from agent_mailbox.house import House
from agent_mailbox.mailbox import Mailbox
from agent_mailbox.sqlite_store import SqliteStore

logger = logging.getLogger(__name__)

#: The three ways the hub can treat identity. `off` trusts the header (the LAN default);
#: `warn` checks credentials and logs a missing one but serves; `enforce` refuses.
_AUTH_MODES = ("off", "warn", "enforce")

ENV_PREFIX = "AGENT_MAILBOX_"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default).strip()


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
    log_level: str = "INFO"
    #: off | warn | enforce (see _AUTH_MODES). Default off keeps the LAN behaviour.
    auth_mode: str = "off"
    #: Fernet key for encrypting TOTP secrets at rest. Needed once 2FA is
    #: enrolled; never a default (charter: no secrets in the repo).
    secret_key: str = ""
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
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            auth_mode=auth_mode,
            secret_key=_env("SECRET_KEY", ""),
            login_max_failures=int(_env("LOGIN_MAX_FAILURES", "5")),
            login_lockout_minutes=int(_env("LOGIN_LOCKOUT_MINUTES", "15")),
            trust_proxy=_env("TRUST_PROXY", "").lower() in ("1", "true", "yes"),
        )


def build_app(settings: Settings | None = None) -> Litestar:
    """Build the hub, opening its store for the life of the application.

    The store is opened in a Litestar startup hook rather than here, so that building
    the app is cheap and testable and nothing touches the disk at import time.
    """
    config = settings or Settings.from_env()
    logging.basicConfig(level=config.log_level)

    store = SqliteStore(config.db)
    mailbox = Mailbox(
        store, hub_name=config.hub_name, retention_days=config.retention_days
    )
    house = House(mailbox)

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
        auth = AuthService(auth_store, secret_key=key)

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
    )

    async def open_store(_: Litestar) -> None:
        await store.__aenter__()
        if auth_store is not None:
            await auth_store.__aenter__()
        logger.info(
            "agent-mailbox serving %s as %s, storing at %s (auth: %s)",
            config.public_url,
            config.hub_name,
            config.db,
            config.auth_mode,
        )

    async def bootstrap_admin(_: Litestar) -> None:
        if auth is not None:
            await auth.bootstrap()  # logs the initial password once, if it seeds

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


def main() -> None:
    """Entry point for `agent-mailbox-serve` and for the container."""
    import uvicorn

    config = Settings.from_env()
    uvicorn.run(
        build_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
