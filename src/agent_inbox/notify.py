"""Who is listening right now, so that a send can tell them.

The hub's entire contribution to being woken is one sentence — *"there is mail for you,
from X, about Y"* — and this module is where that sentence is handed to whoever is
holding a connection open. It knows nothing about harnesses, sessions or interruption;
a client decides what to do with what it hears, and the hub never learns what that was.

**Nothing here may raise into a send.** A hub that refuses mail because nobody could be
told about it has inverted its own priorities, and that inversion is the worst outcome
available: mail is the product, notification is a convenience on top of it. So
:meth:`Listeners.announce` neither blocks nor raises — it returns how many listeners it
reached, and drops what it cannot deliver.

**Nothing here is durable, and that is correct.** A connection is not a fact worth
surviving a restart, because a dropped client reconnects and its mail waited for it in
the store the whole time (FR-005). This is per-process, in-memory, and lost on shutdown
by design — which also means the count it reports is *this process's* listeners, not the
deployment's.

**Which makes one worker a load-bearing assumption.** `serve.py` runs a single uvicorn
process with no `workers` argument, so every send and every held connection share this
registry. Add workers and the failure is silent and partial: a client connected to
worker A hears nothing about mail sent through worker B, some of the time, depending on
which process took which request. Nothing raises, no test fails, and the symptom is
"notifications are unreliable". Crossing that line needs a shared bus — or it needs not
to be crossed.

The vocabulary is deliberately narrow. A listener is **a connected session**, never "an
agent who is present": an agent mid-turn on a long task is connected and reading
nothing, and an agent that runs no MCP server at all is never connected and may be
entirely here. What "present" means is issue #7's decision, and this module supplies
input to it rather than making it.
"""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from agent_inbox.records import ObjectRecord

logger = logging.getLogger("agent_inbox.notify")

#: How many connections one hub process will hold at once. An unbounded fan-out is a
#: resource leak that presents as working (FR-007), so there is a number, it is small
#: enough to notice, and reaching it refuses clearly rather than degrading.
DEFAULT_MAX_LISTENERS = 64

#: How many unread events one connection may fall behind by before the next is dropped.
#: A client this far behind has already lost the race that made a stream worth holding;
#: what it should do is poll, which FR-003 keeps first-class precisely for this case.
DEFAULT_QUEUE_DEPTH = 32


class TooManyListeners(Exception):
    """The cap is reached. Raised at registration, never during delivery.

    Deliberately not a :class:`MailboxError`: nothing about the mailbox has gone wrong,
    and a caller that is refused here has lost immediacy and nothing else.
    """


@dataclass(frozen=True, slots=True)
class Arrival:
    """That mail exists, and enough to decide whether to fetch it. Never the body.

    The three fields are the whole contract. `id` is sufficient to fetch, `sender` and
    `subject` are sufficient to *decide whether to* (FR-008) — which is what stops a
    client having to make a second call before it can make up its mind.

    There is no body here and there must never be one (FR-002): a body pushed at a
    client is a body nobody asked for, and it would make this stream a second way to
    read mail, consuming nothing and leaving no read record. `read_message` remains the
    only thing that consumes.
    """

    #: The message id, sufficient to fetch it by the ordinary route.
    id: str
    #: Who sent it — the only field a recipient's own policy may be gated on, because it
    #: is the only one the *sender* does not choose the meaning of.
    sender: str
    #: What it is about. Shown so an agent can decide what to do; never an input to
    #: whether it is disturbed (FR-011 — that rule lives in the client, but the reason
    #: the field is here at all is worth stating where the field is defined).
    subject: str
    #: When the hub stored it, in the hub's own timestamp format.
    published: str

    @classmethod
    def of(cls, record: ObjectRecord) -> Arrival:
        """Describe a stored message. Reads only fields that are safe to disclose."""
        return cls(
            id=record.id,
            sender=record.attributed_to,
            # An absent subject is an empty one on the wire. The alternative — omitting
            # the key — makes every client write the same defensive branch.
            subject=record.summary or "",
            published=record.published,
        )

    def as_event(self) -> dict[str, str]:
        """The JSON payload, as a client sees it.

        Written out field by field rather than serialised from the dataclass, so that
        adding a field to :class:`Arrival` cannot silently put it on the wire. Every
        field a recipient receives should be one somebody chose to send.
        """
        return {
            "id": self.id,
            "from": self.sender,
            "subject": self.subject,
            "published": self.published,
        }


class Listeners:
    """The open connections, keyed by the actor each one is authenticated as.

    One :class:`asyncio.Queue` per connection rather than one per actor: two sessions
    running as the same agent must both be told, and neither may consume the other's
    event. That mirrors the mailbox itself, where reading is per-recipient.

    Free of Litestar and of :class:`~agent_inbox.house.House` on purpose — everything
    here is testable with nothing but `asyncio`, which is what makes the disclosure
    tests cheap enough to write honestly.
    """

    def __init__(
        self,
        *,
        max_listeners: int = DEFAULT_MAX_LISTENERS,
        queue_depth: int = DEFAULT_QUEUE_DEPTH,
    ) -> None:
        self._by_actor: dict[str, set[asyncio.Queue[Arrival]]] = {}
        self._max_listeners = max_listeners
        self._queue_depth = queue_depth

    @property
    def max_listeners(self) -> int:
        return self._max_listeners

    def count(self) -> int:
        """Connections held by this process, across every actor."""
        return sum(len(queues) for queues in self._by_actor.values())

    def count_for(self, actor: str) -> int:
        """Connections held for one actor. Sessions, not people."""
        return len(self._by_actor.get(actor, ()))

    def by_actor(self) -> dict[str, int]:
        """A count per actor, omitting actors with nothing open."""
        return {
            actor: len(queues) for actor, queues in self._by_actor.items() if queues
        }

    def at_capacity(self) -> bool:
        """Whether the next :meth:`open` would be refused.

        Asked separately from opening so that a caller which cannot refuse cleanly once
        it has started responding — an HTTP handler, for instance — can refuse *before*
        it starts. This is not a reservation: nothing stops two callers both seeing room
        and both taking it, which briefly exceeds the cap and then drains as they leave.
        The alternative, reserving a slot that a caller might never use, leaks it.
        """
        return self.count() >= self._max_listeners

    def full_message(self) -> str:
        """The refusal text, so a caller that checks separately says the same thing.

        One sentence, one place. Two versions of "we are full" is how a route ends up
        naming a cap that no longer matches the one being enforced.
        """
        return (
            f"this hub is holding its maximum of {self._max_listeners} event streams — "
            "poll `check_inbox` instead, which is unaffected"
        )

    def open(self, actor: str) -> asyncio.Queue[Arrival]:
        """Register a connection for `actor`, or refuse because the hub is full.

        Separate from the streaming itself, and deliberately so. A cap enforced *inside*
        a response generator cannot refuse clearly: by the time the first item is pulled
        the status line has gone, so the only thing left is to close an already-started
        stream, which a client cannot tell apart from a network fault. Registering first
        means a refusal is an ordinary HTTP error with a reason in it (FR-007), and that
        connections already open are demonstrably untouched by it.

        Every caller must pair this with :meth:`close`. :meth:`listening` does that for
        you and is what tests should use.
        """
        if self.at_capacity():
            raise TooManyListeners(self.full_message())
        queue: asyncio.Queue[Arrival] = asyncio.Queue(maxsize=self._queue_depth)
        self._by_actor.setdefault(actor, set()).add(queue)
        logger.info("event=mailbox.listen.opened actor=%s open=%d", actor, self.count())
        return queue

    def close(self, actor: str, queue: asyncio.Queue[Arrival]) -> None:
        """Unregister a connection. Idempotent, because the caller is a `finally`."""
        listeners = self._by_actor.get(actor)
        if listeners is not None:
            listeners.discard(queue)
            if not listeners:
                del self._by_actor[actor]
        logger.info("event=mailbox.listen.closed actor=%s open=%d", actor, self.count())

    @contextmanager
    def listening(self, actor: str) -> Iterator[asyncio.Queue[Arrival]]:
        """:meth:`open` and :meth:`close` as a pair that cannot be left half-done.

        The failure this prevents is the one that presents as working: a stream
        cancelled mid-yield — which is what a client disappearing looks like from in
        here — leaves an entry behind that will never be read from and never removed. Do
        that a few hundred times and the cap is reached entirely by connections that
        closed hours ago, while the hub reports itself busy.
        """
        queue = self.open(actor)
        try:
            yield queue
        finally:
            self.close(actor, queue)

    def announce(self, actor: str, arrival: Arrival) -> int:
        """Tell everyone listening as `actor`. Never blocks, never raises.

        Returns how many connections took it. Zero is the ordinary case — nobody is
        listening, mail waits as it always has, and nothing about the send is different.

        A full queue **drops the event and says so**. Silently pretending it was
        delivered would leave a client believing it is up to date when it is behind,
        which is worse than the drop: the client can recover from knowing nothing, and
        cannot recover from being wrong.
        """
        reached = 0
        for queue in tuple(self._by_actor.get(actor, ())):
            try:
                queue.put_nowait(arrival)
            except asyncio.QueueFull:
                logger.warning(
                    "event=mailbox.listen.dropped actor=%s message=%s reason=behind",
                    actor,
                    arrival.id,
                )
            else:
                reached += 1
        return reached
