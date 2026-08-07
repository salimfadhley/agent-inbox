"""SQLite behind the storage port.

An **adapter**, and nothing else. Every messaging decision — who receives a copy, which
turns of a thread you may see, which conversations have gone quiet — is made above this
file by pure functions. What happens here is rows in and rows out.

That division is why this module is dull, and dullness is the goal: if this file
ever needs to know what a broadcast is, the port is wrong.

Shape follows ADR 0006 — typed columns for everything routed on, plus a ``document``
column holding the object as received. ActivityStreams requires preserving
properties you do not understand, and a peer may send extensions we have never seen.

Two statements carry the correctness of the whole system, and both are ``INSERT OR
IGNORE`` against a primary key:

* claiming a name — otherwise two agents race and silently share an inbox;
* marking a read — otherwise one message is consumed twice.

SQLite decides both, atomically, rather than a read-then-write in Python that a second
connection could interleave with.
"""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import aiosqlite

from agent_inbox.exceptions import StoreNotOpen
from agent_inbox.records import ActorRecord, ObjectRecord, ReadRecord
from agent_inbox.store import MessageStore
from agent_inbox.vocabulary import ActorType, ObjectType

#: Bumped when the schema changes shape. There is nothing to migrate *from* yet: this
#: package is a fresh start, and the superseded implementation's data is not carried
#: over (its messages expire in a fortnight anyway).
#: Bumped to 2 when ``hub_settings`` arrived. Every statement in ``_SCHEMA`` is
#: ``CREATE ... IF NOT EXISTS`` and is re-applied on open, so an existing database gains
#: the table without a migration step and without any existing table being touched. The
#: number is a record that the shape changed, not a trigger for anything.
SCHEMA_VERSION = 2

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS actors (
        name       TEXT PRIMARY KEY,
        actor_type TEXT NOT NULL,
        profile    TEXT NOT NULL DEFAULT '{}',
        created    TEXT NOT NULL DEFAULT '',
        last_seen  TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS objects (
        id            TEXT PRIMARY KEY,
        object_type   TEXT NOT NULL,
        attributed_to TEXT NOT NULL,
        to_names      TEXT NOT NULL DEFAULT '[]',
        cc_names      TEXT NOT NULL DEFAULT '[]',
        in_reply_to   TEXT,
        summary       TEXT,
        content       TEXT NOT NULL DEFAULT '',
        published     TEXT NOT NULL DEFAULT '',
        document      TEXT NOT NULL DEFAULT '{}'
    )
    """,
    # Read-state is per (object, reader): the composite key is what makes a second
    # consumption by the same reader a no-op rather than a duplicate row.
    """
    CREATE TABLE IF NOT EXISTS reads (
        object_id TEXT NOT NULL,
        reader    TEXT NOT NULL,
        at        TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (object_id, reader)
    )
    """,
    # The first thing the hub keeps about *itself*. Three tables above are all about
    # mail; this one is about the mailbox. One row per key rather than one row with
    # three columns, so "never set" is the absence of a row rather than a NULL — and
    # absence is the state of every hub that existed before this table did.
    # Hubs this one has been told to trust. Separate from `hub_settings` because this
    # is not configuration — it is a trust list, and the difference matters: a setting
    # answers "how is this hub set up", and a row here answers "whose signature counts".
    """
    CREATE TABLE IF NOT EXISTS federation_peers (
        origin  TEXT PRIMARY KEY,
        added   TEXT NOT NULL DEFAULT '',
        note    TEXT NOT NULL DEFAULT ''
    )
    """,
    # Origins this hub refuses. **A separate table from the peers, not a column on it**,
    # because a block is not a kind of peer: an operator blocks hubs they have never
    # added and never will, and a block must outlive the removal of a peering. Keeping
    # them in one table would make "blocked" a property of something trusted, which is
    # the wrong shape and the one that produces a bypass when a peer is deleted.
    """
    CREATE TABLE IF NOT EXISTS federation_blocks (
        origin  TEXT PRIMARY KEY,
        added   TEXT NOT NULL DEFAULT '',
        note    TEXT NOT NULL DEFAULT ''
    )
    """,
    # Activity ids already delivered. FR-5: a peer that retries must not double-deliver,
    # and "have I seen this" is the only way to know.
    """
    CREATE TABLE IF NOT EXISTS seen_activities (
        activity_id TEXT PRIMARY KEY,
        seen        TEXT NOT NULL DEFAULT '',
        delivered   INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hub_settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS objects_published ON objects (published, id)",
    "CREATE INDEX IF NOT EXISTS objects_in_reply_to ON objects (in_reply_to)",
    "CREATE INDEX IF NOT EXISTS reads_object ON reads (object_id)",
)


def _loads(raw: str | None, fallback: Any) -> Any:
    """Tolerate a malformed JSON column rather than making the mailbox unopenable.

    A corrupt row should cost one message, not the whole store.
    """
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _to_actor(row: aiosqlite.Row) -> ActorRecord:
    return ActorRecord(
        name=row["name"],
        actor_type=ActorType(row["actor_type"]),
        profile=_loads(row["profile"], {}),
        created=row["created"],
        last_seen=row["last_seen"],
    )


def _to_object(row: aiosqlite.Row) -> ObjectRecord:
    return ObjectRecord(
        id=row["id"],
        object_type=ObjectType(row["object_type"]),
        attributed_to=row["attributed_to"],
        to=tuple(_loads(row["to_names"], [])),
        cc=tuple(_loads(row["cc_names"], [])),
        in_reply_to=row["in_reply_to"],
        summary=row["summary"],
        content=row["content"],
        published=row["published"],
        document=_loads(row["document"], {}),
    )


class SqliteStore:
    """The storage port, backed by one SQLite file.

    Used as an async context manager, which is where the connection and schema live::

        async with SqliteStore("mail.db") as store:
            await store.claim_name(actor)

    ``:memory:`` is accepted and gives a store that vanishes with the connection.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Self:
        conn = await aiosqlite.connect(self._path)
        conn.row_factory = aiosqlite.Row
        # WAL lets readers run while a write is in flight. Only one process opens this
        # file (ADR 0005), so this is about the server's own concurrency, not sharing.
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA:
            await conn.execute(statement)
        # Additive, for a store written before the claim existed (#41). Existing rows
        # get `delivered = 1`, which is exactly what they are: every one of them was
        # written by the old `remember_activity`, which only ever ran *after* a
        # successful delivery. Defaulting them to 0 would make every activity this hub
        # has ever received reclaimable, and a peer that retried an old id would deliver
        # it a second time — the very bug this closes, introduced by its own fix.
        cursor = await conn.execute("PRAGMA table_info(seen_activities)")
        held = {row[1] for row in await cursor.fetchall()}
        if "delivered" not in held:
            await conn.execute(
                "ALTER TABLE seen_activities "
                "ADD COLUMN delivered INTEGER NOT NULL DEFAULT 1"
            )
        await conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        await conn.commit()
        self._conn = conn
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise StoreNotOpen(
                "SqliteStore must be used as an async context manager: "
                "`async with SqliteStore(path) as store:`"
            )
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

    async def schema_version(self) -> int:
        cursor = await self._execute("PRAGMA user_version")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    # -- hub settings ------------------------------------------------------

    async def seen_activity(self, activity_id: str) -> bool:
        cursor = await self._execute(
            "SELECT 1 FROM seen_activities WHERE activity_id=?", (activity_id,)
        )
        return await cursor.fetchone() is not None

    async def remember_activity(self, activity_id: str, seen: str) -> None:
        await self._execute(
            "INSERT INTO seen_activities (activity_id, seen, delivered) "
            "VALUES (?, ?, 1) "
            "ON CONFLICT(activity_id) DO UPDATE SET delivered = 1",
            (activity_id, seen),
        )
        await self._db.commit()

    async def claim_activity(
        self, activity_id: str, now: str, stale_before: str
    ) -> bool:
        """Win the right to deliver this activity, atomically (issue #41).

        **One statement decides**, which is the whole point. `INSERT ... ON CONFLICT DO
        UPDATE ... WHERE` is a single write under SQLite's write lock, so of two POSTs
        carrying the same activity id exactly one can come away with `rowcount == 1`.
        The previous shape asked `seen_activity` and then delivered, and both callers
        could pass the question before either wrote the answer.

        The `WHERE` is what keeps a crash from costing a message. A row that was claimed
        and never completed is taken over once it is older than *stale_before*; a row
        that was *delivered* is never taken over at all, whatever its age. So the two
        failures land where they should: a genuine duplicate is refused for ever, and an
        abandoned delivery is retried late.
        """
        cursor = await self._execute(
            "INSERT INTO seen_activities (activity_id, seen, delivered) "
            "VALUES (?, ?, 0) "
            "ON CONFLICT(activity_id) DO UPDATE SET seen = excluded.seen "
            "WHERE seen_activities.delivered = 0 AND seen_activities.seen < ?",
            (activity_id, now, stale_before),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def complete_activity(self, activity_id: str) -> None:
        await self._execute(
            "UPDATE seen_activities SET delivered = 1 WHERE activity_id = ?",
            (activity_id,),
        )
        await self._db.commit()

    async def release_activity(self, activity_id: str) -> None:
        """Delete an *uncompleted* claim. The `delivered = 0` is the safety."""
        await self._execute(
            "DELETE FROM seen_activities WHERE activity_id = ? AND delivered = 0",
            (activity_id,),
        )
        await self._db.commit()

    async def peers(self) -> dict[str, str]:
        """Origins this hub trusts, mapped to when each was added."""
        cursor = await self._execute("SELECT origin, added FROM federation_peers")
        return {str(r["origin"]): str(r["added"]) for r in await cursor.fetchall()}

    async def add_peer(self, origin: str, added: str, note: str = "") -> None:
        await self._execute(
            "INSERT INTO federation_peers (origin, added, note) VALUES (?, ?, ?) "
            "ON CONFLICT(origin) DO UPDATE SET note=excluded.note",
            (origin, added, note),
        )
        await self._db.commit()

    async def remove_peer(self, origin: str) -> None:
        await self._execute("DELETE FROM federation_peers WHERE origin=?", (origin,))
        await self._db.commit()

    async def blocks(self) -> dict[str, str]:
        """Origins this hub refuses, mapped to the note explaining why."""
        cursor = await self._execute("SELECT origin, note FROM federation_blocks")
        return {str(r["origin"]): str(r["note"]) for r in await cursor.fetchall()}

    async def add_block(self, origin: str, added: str, note: str = "") -> None:
        await self._execute(
            "INSERT INTO federation_blocks (origin, added, note) VALUES (?, ?, ?) "
            "ON CONFLICT(origin) DO UPDATE SET note=excluded.note",
            (origin, added, note),
        )
        await self._db.commit()

    async def remove_block(self, origin: str) -> None:
        await self._execute("DELETE FROM federation_blocks WHERE origin=?", (origin,))
        await self._db.commit()

    async def hub_settings(self) -> dict[str, str]:
        """What the operator configured about this hub. Often empty, legitimately."""
        cursor = await self._execute("SELECT key, value FROM hub_settings")
        return {str(row["key"]): str(row["value"]) for row in await cursor.fetchall()}

    async def set_hub_setting(self, key: str, value: str | None) -> None:
        """Store one setting, or clear it when ``value`` is None.

        Clearing removes the row rather than storing an empty string, because the two
        mean different things: no row is "never set", and an empty string is a value an
        operator chose. The console renders them the same and the API does not.
        """
        if value is None:
            await self._execute("DELETE FROM hub_settings WHERE key=?", (key,))
        else:
            await self._execute(
                "INSERT INTO hub_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        await self._db.commit()

    # -- actors ------------------------------------------------------------

    async def claim_name(self, actor: ActorRecord) -> bool:
        """Insert only if the name is free — SQLite decides, not us.

        ``INSERT OR IGNORE`` against the primary key means the loser of a race changes
        nothing, so a second claimant can never overwrite the incumbent's profile.
        """
        cursor = await self._execute(
            "INSERT OR IGNORE INTO actors "
            "(name, actor_type, profile, created, last_seen) VALUES (?, ?, ?, ?, ?)",
            (
                actor.name,
                actor.actor_type.value,
                json.dumps(dict(actor.profile)),
                actor.created,
                actor.last_seen,
            ),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def get_actor(self, name: str) -> ActorRecord | None:
        cursor = await self._execute("SELECT * FROM actors WHERE name = ?", (name,))
        row = await cursor.fetchone()
        return _to_actor(row) if row else None

    async def put_actor(self, actor: ActorRecord) -> None:
        await self._execute(
            "INSERT INTO actors (name, actor_type, profile, created, last_seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "actor_type=excluded.actor_type, profile=excluded.profile, "
            "last_seen=excluded.last_seen",
            (
                actor.name,
                actor.actor_type.value,
                json.dumps(dict(actor.profile)),
                actor.created,
                actor.last_seen,
            ),
        )
        await self._db.commit()

    async def actors(self) -> Iterable[ActorRecord]:
        cursor = await self._execute("SELECT * FROM actors ORDER BY name")
        return tuple(_to_actor(row) for row in await cursor.fetchall())

    # -- objects -----------------------------------------------------------

    async def add_object(self, obj: ObjectRecord) -> None:
        await self._execute(
            "INSERT OR REPLACE INTO objects (id, object_type, attributed_to, to_names, "
            "cc_names, in_reply_to, summary, content, published, document) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obj.id,
                obj.object_type.value,
                obj.attributed_to,
                json.dumps(list(obj.to)),
                json.dumps(list(obj.cc)),
                obj.in_reply_to,
                obj.summary,
                obj.content,
                obj.published,
                json.dumps(dict(obj.document)),
            ),
        )
        await self._db.commit()

    async def get_object(self, object_id: str) -> ObjectRecord | None:
        cursor = await self._execute("SELECT * FROM objects WHERE id = ?", (object_id,))
        row = await cursor.fetchone()
        return _to_object(row) if row else None

    async def objects(self) -> Iterable[ObjectRecord]:
        cursor = await self._execute(
            "SELECT * FROM objects ORDER BY published ASC, id ASC"
        )
        return tuple(_to_object(row) for row in await cursor.fetchall())

    async def remove_objects(self, object_ids: Iterable[str]) -> int:
        ids = tuple(object_ids)
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        # Read-state goes with the objects. Leaving it behind would accumulate rows
        # referring to messages that no longer exist, for ever.
        await self._execute(f"DELETE FROM reads WHERE object_id IN ({marks})", ids)
        cursor = await self._execute(f"DELETE FROM objects WHERE id IN ({marks})", ids)
        await self._db.commit()
        return cursor.rowcount

    # -- read state --------------------------------------------------------

    async def mark_read(self, read: ReadRecord) -> bool:
        """Record a consumption, once. ``False`` if this reader already consumed it."""
        cursor = await self._execute(
            "INSERT OR IGNORE INTO reads (object_id, reader, at) VALUES (?, ?, ?)",
            (read.object_id, read.reader, read.at),
        )
        await self._db.commit()
        return cursor.rowcount == 1

    async def reads_of(
        self, object_ids: Iterable[str]
    ) -> Mapping[str, tuple[ReadRecord, ...]]:
        ids = tuple(object_ids)
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        cursor = await self._execute(
            f"SELECT * FROM reads WHERE object_id IN ({marks})", ids
        )
        found: dict[str, list[ReadRecord]] = {object_id: [] for object_id in ids}
        for row in await cursor.fetchall():
            found[row["object_id"]].append(
                ReadRecord(row["object_id"], row["reader"], row["at"])
            )
        return {object_id: tuple(reads) for object_id, reads in found.items()}


# A static conformance check. `runtime_checkable` only verifies that method *names*
# exist, so this assignment is what actually holds the adapter to the port's
# signatures — pyright rejects the module if they drift.
_conforms: MessageStore = SqliteStore(":memory:")
