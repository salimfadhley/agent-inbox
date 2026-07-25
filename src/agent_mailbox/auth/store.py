"""Where auth state lives — a port and two adapters.

The ``AuthStore`` Protocol is the whole surface the service depends on; an
in-memory adapter backs the tests and a SQLite adapter backs the hub. The
SQLite tables live in the same file as the mailbox but in their own namespace
(``auth_*``), and neither store ever references the other's tables — the
decoupling the structural test enforces.

Two operations carry correctness and both are decided by SQLite atomically, not by a
read-then-write in Python a second connection could interleave with:

* **spending a recovery code** — an ``UPDATE … WHERE used=0`` whose ``rowcount``
  tells us whether *this* call consumed it, so it can never be used twice;
* **revoking a token** — the same shape, so a token is refused from the next request on.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, runtime_checkable

import aiosqlite

from agent_mailbox.auth.records import DeviceToken, EnrolmentState, Session, User

#: Bumped when the auth schema changes. Independent of the mailbox schema.
SCHEMA_VERSION = 1


@runtime_checkable
class AuthStore(Protocol):
    """The persistence port for authentication. Pure storage; makes no decisions."""

    async def any_users(self) -> bool: ...
    async def add_user(self, user: User) -> None: ...
    async def get_user(self, username: str) -> User | None: ...
    async def put_user(self, user: User) -> None: ...

    async def add_recovery_codes(
        self, username: str, code_hashes: list[str]
    ) -> None: ...
    async def spend_recovery_code(self, username: str, code_hash: str) -> bool:
        """Consume one matching unused code. True iff *this* call consumed it."""
        ...

    async def add_token(self, token: DeviceToken) -> None: ...
    async def get_token_by_hash(self, token_hash: str) -> DeviceToken | None: ...
    async def tokens_for(self, actor: str) -> tuple[DeviceToken, ...]: ...
    async def touch_token(self, token_id: str, when: str) -> None: ...
    async def revoke_token(self, token_id: str) -> bool: ...

    async def add_session(self, session: Session) -> None: ...
    async def get_session(self, session_id: str) -> Session | None: ...
    async def delete_session(self, session_id: str) -> None: ...


# -- in-memory -------------------------------------------------------------


class InMemoryAuthStore:
    """A dict-backed store for tests. Same contract as the SQLite adapter."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._recovery: list[tuple[str, str, bool]] = []  # (username, hash, used)
        self._tokens: dict[str, DeviceToken] = {}
        self._sessions: dict[str, Session] = {}

    async def any_users(self) -> bool:
        return bool(self._users)

    async def add_user(self, user: User) -> None:
        self._users[user.username] = user

    async def get_user(self, username: str) -> User | None:
        return self._users.get(username)

    async def put_user(self, user: User) -> None:
        self._users[user.username] = user

    async def add_recovery_codes(self, username: str, code_hashes: list[str]) -> None:
        # Replace any prior codes for this user (rotation issues a fresh set).
        self._recovery = [r for r in self._recovery if r[0] != username]
        self._recovery.extend((username, h, False) for h in code_hashes)

    async def spend_recovery_code(self, username: str, code_hash: str) -> bool:
        for i, (user, h, used) in enumerate(self._recovery):
            if user == username and h == code_hash and not used:
                self._recovery[i] = (user, h, True)
                return True
        return False

    async def add_token(self, token: DeviceToken) -> None:
        self._tokens[token.id] = token

    async def get_token_by_hash(self, token_hash: str) -> DeviceToken | None:
        for token in self._tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    async def tokens_for(self, actor: str) -> tuple[DeviceToken, ...]:
        return tuple(
            sorted(
                (t for t in self._tokens.values() if t.actor == actor),
                key=lambda t: t.created,
            )
        )

    async def touch_token(self, token_id: str, when: str) -> None:
        token = self._tokens.get(token_id)
        if token is not None:
            self._tokens[token_id] = DeviceToken(
                id=token.id,
                actor=token.actor,
                token_hash=token.token_hash,
                label=token.label,
                created=token.created,
                last_used=when,
                revoked=token.revoked,
            )

    async def revoke_token(self, token_id: str) -> bool:
        token = self._tokens.get(token_id)
        if token is None or token.revoked:
            return False
        self._tokens[token_id] = DeviceToken(
            id=token.id,
            actor=token.actor,
            token_hash=token.token_hash,
            label=token.label,
            created=token.created,
            last_used=token.last_used,
            revoked=True,
        )
        return True

    async def add_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    async def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# -- SQLite ----------------------------------------------------------------

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS auth_users (
        username        TEXT PRIMARY KEY,
        password_hash   TEXT NOT NULL,
        enrolment_state TEXT NOT NULL DEFAULT 'must_change_and_enrol',
        totp_secret_enc BLOB,
        created         TEXT NOT NULL DEFAULT '',
        last_login      TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_recovery_codes (
        username  TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        used      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_device_tokens (
        id         TEXT PRIMARY KEY,
        actor      TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        label      TEXT NOT NULL DEFAULT '',
        created    TEXT NOT NULL DEFAULT '',
        last_used  TEXT,
        revoked    INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        id       TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created  TEXT NOT NULL DEFAULT '',
        expires  TEXT NOT NULL DEFAULT '',
        limited  INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS auth_tokens_hash "
    "ON auth_device_tokens (token_hash)",
    "CREATE INDEX IF NOT EXISTS auth_tokens_actor ON auth_device_tokens (actor)",
    "CREATE INDEX IF NOT EXISTS auth_recovery_user ON auth_recovery_codes (username)",
)


def _to_user(row: aiosqlite.Row) -> User:
    return User(
        username=row["username"],
        password_hash=row["password_hash"],
        enrolment_state=EnrolmentState(row["enrolment_state"]),
        totp_secret_enc=row["totp_secret_enc"],
        created=row["created"],
        last_login=row["last_login"],
    )


def _to_token(row: aiosqlite.Row) -> DeviceToken:
    return DeviceToken(
        id=row["id"],
        actor=row["actor"],
        token_hash=row["token_hash"],
        label=row["label"],
        created=row["created"],
        last_used=row["last_used"],
        revoked=bool(row["revoked"]),
    )


class SqliteAuthStore:
    """The auth port, backed by SQLite. Async context manager, like the mailbox store.

    Accepts an already-open :class:`aiosqlite.Connection` (so it can share the
    hub's one connection to the single database file) *or* a path it opens itself
    (handy for tests).
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> None:
        self._path = str(path) if path is not None else None
        self._conn = conn
        self._owns = conn is None

    async def __aenter__(self) -> Self:
        if self._conn is None:
            if self._path is None:
                raise ValueError("SqliteAuthStore needs a path or an open connection")
            self._conn = await aiosqlite.connect(self._path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA busy_timeout=5000")
        await self.create_schema()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns and self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def create_schema(self) -> None:
        """Create the ``auth_*`` tables idempotently, even on a shared connection."""
        for statement in _SCHEMA:
            await self._db.execute(statement)
        await self._db.commit()

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteAuthStore is not open")
        return self._conn

    async def any_users(self) -> bool:
        cursor = await self._db.execute("SELECT 1 FROM auth_users LIMIT 1")
        return await cursor.fetchone() is not None

    async def add_user(self, user: User) -> None:
        await self._db.execute(
            "INSERT INTO auth_users "
            "(username, password_hash, enrolment_state, totp_secret_enc, created, "
            "last_login) VALUES (?, ?, ?, ?, ?, ?)",
            (
                user.username,
                user.password_hash,
                str(user.enrolment_state),
                user.totp_secret_enc,
                user.created,
                user.last_login,
            ),
        )
        await self._db.commit()

    async def get_user(self, username: str) -> User | None:
        cursor = await self._db.execute(
            "SELECT * FROM auth_users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return _to_user(row) if row else None

    async def put_user(self, user: User) -> None:
        await self._db.execute(
            "UPDATE auth_users SET password_hash=?, enrolment_state=?, "
            "totp_secret_enc=?, last_login=? WHERE username=?",
            (
                user.password_hash,
                str(user.enrolment_state),
                user.totp_secret_enc,
                user.last_login,
                user.username,
            ),
        )
        await self._db.commit()

    async def add_recovery_codes(self, username: str, code_hashes: list[str]) -> None:
        await self._db.execute(
            "DELETE FROM auth_recovery_codes WHERE username = ?", (username,)
        )
        await self._db.executemany(
            "INSERT INTO auth_recovery_codes (username, code_hash, used) "
            "VALUES (?, ?, 0)",
            [(username, h) for h in code_hashes],
        )
        await self._db.commit()

    async def spend_recovery_code(self, username: str, code_hash: str) -> bool:
        cursor = await self._db.execute(
            "UPDATE auth_recovery_codes SET used=1 "
            "WHERE username=? AND code_hash=? AND used=0",
            (username, code_hash),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def add_token(self, token: DeviceToken) -> None:
        await self._db.execute(
            "INSERT INTO auth_device_tokens "
            "(id, actor, token_hash, label, created, last_used, revoked) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token.id,
                token.actor,
                token.token_hash,
                token.label,
                token.created,
                token.last_used,
                int(token.revoked),
            ),
        )
        await self._db.commit()

    async def get_token_by_hash(self, token_hash: str) -> DeviceToken | None:
        cursor = await self._db.execute(
            "SELECT * FROM auth_device_tokens WHERE token_hash = ?", (token_hash,)
        )
        row = await cursor.fetchone()
        return _to_token(row) if row else None

    async def tokens_for(self, actor: str) -> tuple[DeviceToken, ...]:
        cursor = await self._db.execute(
            "SELECT * FROM auth_device_tokens WHERE actor = ? ORDER BY created",
            (actor,),
        )
        return tuple(_to_token(row) for row in await cursor.fetchall())

    async def touch_token(self, token_id: str, when: str) -> None:
        await self._db.execute(
            "UPDATE auth_device_tokens SET last_used=? WHERE id=?", (when, token_id)
        )
        await self._db.commit()

    async def revoke_token(self, token_id: str) -> bool:
        cursor = await self._db.execute(
            "UPDATE auth_device_tokens SET revoked=1 WHERE id=? AND revoked=0",
            (token_id,),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def add_session(self, session: Session) -> None:
        await self._db.execute(
            "INSERT INTO auth_sessions (id, username, created, expires, limited) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session.id,
                session.username,
                session.created,
                session.expires,
                int(session.limited),
            ),
        )
        await self._db.commit()

    async def get_session(self, session_id: str) -> Session | None:
        cursor = await self._db.execute(
            "SELECT * FROM auth_sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Session(
            id=row["id"],
            username=row["username"],
            created=row["created"],
            expires=row["expires"],
            limited=bool(row["limited"]),
        )

    async def delete_session(self, session_id: str) -> None:
        await self._db.execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))
        await self._db.commit()
