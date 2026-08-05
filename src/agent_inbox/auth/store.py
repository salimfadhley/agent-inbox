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

from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable

import aiosqlite

from agent_inbox.auth.records import (
    ADMIN_GROUP,
    DeviceToken,
    EnrolmentState,
    Session,
    TokenUse,
    User,
)

#: Bumped when the auth schema changes. Independent of the mailbox schema.
SCHEMA_VERSION = 1


@runtime_checkable
class AuthStore(Protocol):
    """The persistence port for authentication. Pure storage; makes no decisions."""

    async def any_users(self) -> bool: ...
    async def reset_users(self) -> None:
        """Delete every operator account, their recovery codes and sessions.

        Device tokens are deliberately untouched: they belong to agents, not to
        operators, and taking them out would turn "I cannot log in" into "every
        agent on the hub is locked out too".
        """
        ...

    async def add_user(self, user: User) -> None: ...
    async def get_user(self, username: str) -> User | None: ...
    async def put_user(self, user: User) -> None: ...
    async def users(self) -> tuple[User, ...]:
        """Every operator. There is no role column — each one is an admin."""
        ...

    async def remove_user(self, username: str) -> bool:
        """Delete one operator. True iff this call removed them.

        Their sessions and recovery codes go with them, because an account that
        no longer exists must not leave a way in behind it.
        """
        ...

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
    async def all_tokens(self) -> tuple[DeviceToken, ...]: ...
    async def record_use(
        self, token_id: str, actor: str, when: str, client: str = ""
    ) -> None:
        """Note that ``token_id`` admitted ``actor``, setting first-seen only once.

        ``client`` is the version the caller reported on *this* request, so it is the
        hub's own observation rather than a claim recorded once at join. Blank leaves
        whatever was last seen alone: an older client that sends no header must not
        erase a version we already know.
        """
        ...

    async def uses_for(self, token_id: str) -> tuple[TokenUse, ...]: ...

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
        #: Keyed by (token, actor), so it is bounded by the number of agents rather
        #: than by traffic — the same shape the SQLite table's primary key gives.
        self._uses: dict[tuple[str, str], TokenUse] = {}
        self._sessions: dict[str, Session] = {}

    async def any_users(self) -> bool:
        return bool(self._users)

    async def reset_users(self) -> None:
        self._users.clear()
        self._recovery.clear()
        self._sessions.clear()

    async def users(self) -> tuple[User, ...]:
        return tuple(self._users[name] for name in sorted(self._users))

    async def remove_user(self, username: str) -> bool:
        if username not in self._users:
            return False
        del self._users[username]
        self._recovery = [row for row in self._recovery if row[0] != username]
        self._sessions = {
            sid: session
            for sid, session in self._sessions.items()
            if session.username != username
        }
        return True

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

    async def all_tokens(self) -> tuple[DeviceToken, ...]:
        return tuple(sorted(self._tokens.values(), key=lambda t: t.created))

    async def record_use(
        self, token_id: str, actor: str, when: str, client: str = ""
    ) -> None:
        seen = self._uses.get((token_id, actor))
        self._uses[(token_id, actor)] = TokenUse(
            token_id=token_id,
            actor=actor,
            # Blank leaves the last known version alone. A client too old to send the
            # header must not erase what a newer one told us — "we stopped hearing"
            # and "it downgraded" are different facts and only one of them is true.
            client=client or (seen.client if seen else ""),
            # Set once and never moved. "First seen" is the fact an operator uses to
            # tell a credential that has always been shared from one that started
            # leaking last week, and an upsert that rewrote it would erase exactly that.
            first_seen=seen.first_seen if seen else when,
            last_seen=when,
            uses=(seen.uses if seen else 0) + 1,
        )

    async def uses_for(self, token_id: str) -> tuple[TokenUse, ...]:
        rows = [u for (tid, _), u in self._uses.items() if tid == token_id]
        return tuple(sorted(rows, key=lambda u: u.last_seen, reverse=True))

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
        last_login      TEXT,
        email           TEXT NOT NULL DEFAULT '',
        user_group      TEXT NOT NULL DEFAULT 'admin'
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
    CREATE TABLE IF NOT EXISTS auth_token_use (
        token_id   TEXT NOT NULL,
        actor      TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen  TEXT NOT NULL,
        -- Buckets, not requests: recording is coarse, so this counts the minutes in
        -- which the token was used rather than the calls it served.
        uses       INTEGER NOT NULL DEFAULT 0,
        -- The client version last observed on a request from this actor. Observed,
        -- never claimed: it is read from a request header the hub itself received.
        client     TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (token_id, actor)
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
        email=row["email"] if "email" in row.keys() else "",
        group=row["user_group"] if "user_group" in row.keys() else ADMIN_GROUP,
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
        """Create the ``auth_*`` tables idempotently, even on a shared connection.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so a
        column added later needs its own step — a hub deployed before `email` existed
        has the old shape and would fail on the first read. Checked rather than
        attempted-and-caught, because swallowing an error here would also swallow a
        real one.
        """
        for statement in _SCHEMA:
            await self._execute(statement)
        cursor = await self._execute("PRAGMA table_info(auth_users)")
        columns = {row["name"] for row in await cursor.fetchall()}
        for column, ddl in (
            ("email", "email TEXT NOT NULL DEFAULT ''"),
            ("user_group", "user_group TEXT NOT NULL DEFAULT 'admin'"),
        ):
            if column not in columns:
                await self._execute(f"ALTER TABLE auth_users ADD COLUMN {ddl}")
        # Same additive pattern for a store that predates the client column. An
        # existing deployment keeps its rows and starts recording versions on the next
        # request each agent makes.
        cursor = await self._execute("PRAGMA table_info(auth_token_use)")
        used = {row["name"] for row in await cursor.fetchall()}
        if "client" not in used:
            await self._execute(
                "ALTER TABLE auth_token_use ADD COLUMN client TEXT NOT NULL DEFAULT ''"
            )
        await self._db.commit()

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteAuthStore is not open")
        return self._conn

    async def _execute(self, sql: str, parameters: Any = ()) -> aiosqlite.Cursor:
        """Run one statement, and undo the open transaction if it fails.

        Without this, a single failed write wedges the hub until someone restarts it.
        sqlite3 opens a transaction on the first DML and holds it until commit; if a
        statement raises anywhere before that commit, the transaction stays open, the
        connection keeps the write lock, and every later write from the other
        connection to this file fails with "database is locked" — indefinitely, not for
        the five seconds `busy_timeout` covers.

        Not hypothetical: this took the deployed hub's mail down completely on
        2026-07-26, and what agents saw was a bare 500 on every send, for eleven
        minutes, until the container was restarted.
        """
        try:
            return await self._db.execute(sql, parameters)
        except BaseException:
            # Hand back the write lock before the exception leaves the store. Rolling
            # back with no transaction open is harmless, so this is safe after a failed
            # read too.
            await self._db.rollback()
            raise

    async def _execute_many(self, sql: str, parameters: Any) -> aiosqlite.Cursor:
        try:
            return await self._db.executemany(sql, parameters)
        except BaseException:
            await self._db.rollback()
            raise

    async def any_users(self) -> bool:
        cursor = await self._execute("SELECT 1 FROM auth_users LIMIT 1")
        return await cursor.fetchone() is not None

    async def reset_users(self) -> None:
        for table in ("auth_users", "auth_recovery_codes", "auth_sessions"):
            await self._execute(f"DELETE FROM {table}")  # noqa: S608
        await self._db.commit()

    async def users(self) -> tuple[User, ...]:
        cursor = await self._execute("SELECT * FROM auth_users ORDER BY username")
        return tuple(_to_user(row) for row in await cursor.fetchall())

    async def remove_user(self, username: str) -> bool:
        cursor = await self._execute(
            "DELETE FROM auth_users WHERE username = ?", (username,)
        )
        removed = bool(cursor.rowcount)
        for table in ("auth_recovery_codes", "auth_sessions"):
            await self._execute(
                f"DELETE FROM {table} WHERE username = ?",  # noqa: S608
                (username,),
            )
        await self._db.commit()
        return removed

    async def add_user(self, user: User) -> None:
        await self._execute(
            "INSERT INTO auth_users "
            "(username, password_hash, enrolment_state, totp_secret_enc, created, "
            "last_login, email, user_group) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user.username,
                user.password_hash,
                str(user.enrolment_state),
                user.totp_secret_enc,
                user.created,
                user.last_login,
                user.email,
                user.group,
            ),
        )
        await self._db.commit()

    async def get_user(self, username: str) -> User | None:
        cursor = await self._execute(
            "SELECT * FROM auth_users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return _to_user(row) if row else None

    async def put_user(self, user: User) -> None:
        await self._execute(
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
        await self._execute(
            "DELETE FROM auth_recovery_codes WHERE username = ?", (username,)
        )
        await self._execute_many(
            "INSERT INTO auth_recovery_codes (username, code_hash, used) "
            "VALUES (?, ?, 0)",
            [(username, h) for h in code_hashes],
        )
        await self._db.commit()

    async def spend_recovery_code(self, username: str, code_hash: str) -> bool:
        cursor = await self._execute(
            "UPDATE auth_recovery_codes SET used=1 "
            "WHERE username=? AND code_hash=? AND used=0",
            (username, code_hash),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def add_token(self, token: DeviceToken) -> None:
        await self._execute(
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
        cursor = await self._execute(
            "SELECT * FROM auth_device_tokens WHERE token_hash = ?", (token_hash,)
        )
        row = await cursor.fetchone()
        return _to_token(row) if row else None

    async def tokens_for(self, actor: str) -> tuple[DeviceToken, ...]:
        cursor = await self._execute(
            "SELECT * FROM auth_device_tokens WHERE actor = ? ORDER BY created",
            (actor,),
        )
        return tuple(_to_token(row) for row in await cursor.fetchall())

    async def touch_token(self, token_id: str, when: str) -> None:
        await self._execute(
            "UPDATE auth_device_tokens SET last_used=? WHERE id=?", (when, token_id)
        )
        await self._db.commit()

    async def all_tokens(self) -> tuple[DeviceToken, ...]:
        cursor = await self._execute(
            "SELECT * FROM auth_device_tokens ORDER BY created DESC"
        )
        return tuple(_to_token(row) for row in await cursor.fetchall())

    async def record_use(
        self, token_id: str, actor: str, when: str, client: str = ""
    ) -> None:
        # `first_seen` is written by the INSERT and never by the UPDATE. It is the fact
        # that separates a credential which has always been shared from one that started
        # leaking last week, and an upsert that refreshed it would erase exactly that.
        await self._execute(
            "INSERT INTO auth_token_use "
            "(token_id, actor, first_seen, last_seen, uses, client) "
            "VALUES (?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(token_id, actor) DO UPDATE SET "
            "last_seen=excluded.last_seen, uses=uses+1, "
            # `NULLIF` so a blank leaves the stored version alone: an older client that
            # sends no header must not erase one a newer client reported.
            "client=COALESCE(NULLIF(excluded.client, ''), auth_token_use.client)",
            (token_id, actor, when, when, client),
        )
        await self._db.commit()

    async def uses_for(self, token_id: str) -> tuple[TokenUse, ...]:
        cursor = await self._execute(
            "SELECT token_id, actor, first_seen, last_seen, uses, client "
            "FROM auth_token_use WHERE token_id = ? ORDER BY last_seen DESC",
            (token_id,),
        )
        return tuple(
            TokenUse(
                token_id=row[0],
                actor=row[1],
                first_seen=row[2],
                last_seen=row[3],
                uses=int(row[4]),
                client=str(row[5] or ""),
            )
            for row in await cursor.fetchall()
        )

    async def revoke_token(self, token_id: str) -> bool:
        cursor = await self._execute(
            "UPDATE auth_device_tokens SET revoked=1 WHERE id=? AND revoked=0",
            (token_id,),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def add_session(self, session: Session) -> None:
        await self._execute(
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
        cursor = await self._execute(
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
        await self._execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))
        await self._db.commit()
