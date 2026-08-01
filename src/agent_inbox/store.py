"""The storage port: the smallest set of atomic operations messaging needs.

**This interface deliberately knows nothing about messaging.** It has no `send`,
no `inbox`, no `thread` — those are rules, and rules live in
:mod:`agent_inbox.rules` as pure functions. If a domain verb ever appears here,
logic has leaked into the adapter and the abstraction has stopped earning its
keep. The test: could a new backend be written by someone who has never read the
messaging rules?

What is left is deliberately dull — put, get, iterate, remove, and one
conditional insert. Everything interesting is computed above it.

Two operations must be **atomic**, and they are the only reason this is a
protocol rather than a bag of functions:

* :meth:`MessageStore.claim_name` — or two agents race and share one inbox.
* :meth:`MessageStore.mark_read` — otherwise a message is consumed twice.

:class:`InMemoryStore` is the reference implementation. It is not a test double: it is a
complete, correct backend, and the fact that it fits in a page is the evidence that the
port is narrow enough.
"""

from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable

from agent_inbox.records import ActorRecord, ObjectRecord, ReadRecord


@runtime_checkable
class MessageStore(Protocol):
    """Everything the messaging rules need persisted, and nothing more."""

    # -- actors ------------------------------------------------------------

    async def claim_name(self, actor: ActorRecord) -> bool:
        """Insert ``actor`` **only if** its name is free. ``True`` if claimed.

        Atomic. This is the single point where name uniqueness is enforced, so a
        check-then-insert in the caller would reintroduce the race it exists to close.
        """
        ...

    async def get_actor(self, name: str) -> ActorRecord | None: ...

    async def put_actor(self, actor: ActorRecord) -> None:
        """Overwrite an existing actor. Used for profile and last-seen updates."""
        ...

    async def actors(self) -> Iterable[ActorRecord]:
        """Every actor. Group membership is derived from these by the rules."""
        ...

    # -- objects -----------------------------------------------------------

    async def add_object(self, obj: ObjectRecord) -> None: ...

    async def get_object(self, object_id: str) -> ObjectRecord | None: ...

    async def objects(self) -> Iterable[ObjectRecord]:
        """Every stored object, oldest first.

        Whole-collection iteration is a deliberate choice at this scale: it keeps the
        port trivial and lets every routing and visibility decision be a pure function
        over records. A backend that needs indexes may add them internally; it may not
        push filtering up into this interface, because that is where messaging
        knowledge would start leaking down.
        """
        ...

    async def remove_objects(self, object_ids: Iterable[str]) -> int:
        """Delete objects and their read-state. Returns how many objects went."""
        ...

    # -- read state --------------------------------------------------------

    async def mark_read(self, read: ReadRecord) -> bool:
        """Record a consumption. ``False`` if this reader already consumed it.

        Atomic, so a message cannot be consumed twice by the same reader.
        """
        ...

    async def reads_of(
        self, object_ids: Iterable[str]
    ) -> Mapping[str, tuple[ReadRecord, ...]]:
        """Read-state for the given objects, keyed by object id."""
        ...

    async def hub_settings(self) -> dict[str, str]:
        """What the operator configured about this hub. May legitimately be empty."""
        ...

    async def peers(self) -> dict[str, str]:
        """Origins this hub trusts, mapped to when each was added."""
        ...

    async def seen_activity(self, activity_id: str) -> bool:
        """Whether this activity has already been delivered."""
        ...

    async def remember_activity(self, activity_id: str, seen: str) -> None:
        """Record an activity as delivered. Idempotent."""
        ...

    async def add_peer(self, origin: str, added: str, note: str = "") -> None:
        """Trust a hub. Idempotent."""
        ...

    async def remove_peer(self, origin: str) -> None:
        """Stop trusting a hub."""
        ...

    async def set_hub_setting(self, key: str, value: str | None) -> None:
        """Store one setting, or clear it when ``value`` is None."""
        ...


class InMemoryStore:
    """A complete backend that happens to live in dictionaries.

    Used by the rule tests, and by anyone who wants a mailbox with no file on disk.
    """

    def __init__(self) -> None:
        self._actors: dict[str, ActorRecord] = {}
        self._objects: dict[str, ObjectRecord] = {}
        self._reads: dict[str, dict[str, ReadRecord]] = {}
        self._hub_settings: dict[str, str] = {}
        self._peers: dict[str, str] = {}
        self._seen: dict[str, str] = {}

    async def claim_name(self, actor: ActorRecord) -> bool:
        if actor.name in self._actors:
            return False
        self._actors[actor.name] = actor
        return True

    async def get_actor(self, name: str) -> ActorRecord | None:
        return self._actors.get(name)

    async def put_actor(self, actor: ActorRecord) -> None:
        self._actors[actor.name] = actor

    async def actors(self) -> Iterable[ActorRecord]:
        return tuple(self._actors.values())

    async def add_object(self, obj: ObjectRecord) -> None:
        self._objects[obj.id] = obj

    async def get_object(self, object_id: str) -> ObjectRecord | None:
        return self._objects.get(object_id)

    async def objects(self) -> Iterable[ObjectRecord]:
        return tuple(sorted(self._objects.values(), key=lambda o: (o.published, o.id)))

    async def remove_objects(self, object_ids: Iterable[str]) -> int:
        gone = 0
        for object_id in tuple(object_ids):
            if self._objects.pop(object_id, None) is not None:
                gone += 1
            self._reads.pop(object_id, None)
        return gone

    async def mark_read(self, read: ReadRecord) -> bool:
        readers = self._reads.setdefault(read.object_id, {})
        if read.reader in readers:
            return False
        readers[read.reader] = read
        return True

    async def reads_of(
        self, object_ids: Iterable[str]
    ) -> Mapping[str, tuple[ReadRecord, ...]]:
        return {
            object_id: tuple(self._reads.get(object_id, {}).values())
            for object_id in object_ids
        }

    async def hub_settings(self) -> dict[str, str]:
        return dict(self._hub_settings)

    async def set_hub_setting(self, key: str, value: str | None) -> None:
        if value is None:
            self._hub_settings.pop(key, None)
        else:
            self._hub_settings[key] = value

    async def peers(self) -> dict[str, str]:
        return dict(self._peers)

    async def add_peer(self, origin: str, added: str, note: str = "") -> None:
        self._peers[origin] = added

    async def remove_peer(self, origin: str) -> None:
        self._peers.pop(origin, None)

    async def seen_activity(self, activity_id: str) -> bool:
        return activity_id in self._seen

    async def remember_activity(self, activity_id: str, seen: str) -> None:
        self._seen.setdefault(activity_id, seen)


_conforms: MessageStore = InMemoryStore()
