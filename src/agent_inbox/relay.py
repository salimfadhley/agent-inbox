"""One connection to the hub, however many people are watching the console.

The console and the API are different origins. A browser pointed straight at the hub's
stream would need CORS and cross-origin credentials, and — worse — would make *every
viewer* a hub listener, so ten operators watching would hold ten of the hub's sixty-four
slots. So the console holds **one** upstream connection and re-emits it to its own
subscribers on its own origin, which keeps `connect-src 'self'` standing and keeps the
console a plain client that decides nothing (ADR 0005).

**Connection state is published, never inferred.** This is the whole reason the module
has a state machine rather than just a queue. From a browser, a hub that has gone quiet
and a connection that has died look identical — both are silence — so a page left to
work it out from "no events lately" cannot tell them apart, and would show a confident,
still-pulsing view of a feed that stopped working an hour ago. That is this project's
oldest failure shape, and a live view is the worst possible place to reintroduce it.
Every subscriber is therefore *told* which of `open`, `reconnecting` and `lost` applies,
and told again on every transition.

Nothing here interprets an event. The relay forwards; what a row means is the page's
business and what a message means is the reader's.
"""

import asyncio
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent_inbox.backoff import reconnect_delay
from agent_inbox.client import HubClient, SseParser

logger = logging.getLogger(__name__)

#: How long a connection must last before its successor starts from the shortest delay
#: again. A proxy that answers 200 and closes immediately would otherwise be retried
#: about twice a second for ever, with nothing anywhere saying so.
SETTLED_AFTER = 5.0

#: Statuses that mean *this hub will not stream to us*, as opposed to *not just now*.
#: Retrying a 404 forever is how a console ends up hammering a hub too old to have the
#: route, and reporting `reconnecting` while it does.
FINAL_STATUSES = frozenset({401, 403, 404, 405, 501})

#: Consecutive failed attempts before `reconnecting` becomes `lost`. Small, because the
#: point of the distinction is to stop a page insisting things are nearly fine while an
#: operator watches nothing happen.
ATTEMPTS_BEFORE_LOST = 3

#: How far a subscriber may fall behind before it is dropped. A browser this far behind
#: has already lost the race that made a live view worth holding; it should reload.
SUBSCRIBER_DEPTH = 64

#: The event name the hub uses for an arrival.
ARRIVAL_EVENT = "mail"


class State(StrEnum):
    """What the upstream connection is doing, in the only three words a page needs."""

    OPEN = "open"
    RECONNECTING = "reconnecting"
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class Update:
    """One thing to tell a subscriber: either mail arrived, or the line changed.

    Two kinds down one queue, so a subscriber cannot receive them out of order — a
    `mail` update that overtook the `open` that preceded it would have a page rendering
    rows under a head row still saying `lost`.
    """

    kind: str
    #: The hub's own event payload, verbatim, for `kind == "mail"`. Never re-encoded and
    #: never interpreted: a second definition of the event next to the hub's would drift
    #: the first time a field was added.
    data: str = ""
    state: State | None = None

    @classmethod
    def mail(cls, data: str) -> Update:
        return cls(kind="mail", data=data)

    @classmethod
    def line(cls, state: State) -> Update:
        return cls(kind="state", state=state)


def _open_stream(url: str, headers: dict[str, str]) -> Any:
    """Open the upstream with the standard library, as the rest of this client does."""
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - hub url
    return urllib.request.urlopen(request, timeout=30)  # noqa: S310


class Relay:
    """Holds the hub's stream and re-emits it to console subscribers.

    Started once per console process. Subscribers come and go with page loads; the
    upstream connection does not.
    """

    def __init__(
        self,
        client: HubClient,
        *,
        connect: Callable[[str, dict[str, str]], Any] = _open_stream,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        # Address and credential come from the client, once. Assembling them here is how
        # a stream ends up authenticating differently from every other call months after
        # the change that caused it.
        self._url = client.hub_events_url()
        self._headers = client.stream_headers()
        self._connect = connect
        self._loop = loop
        self._subscribers: set[asyncio.Queue[Update]] = set()
        self._lock = threading.Lock()
        self._state = State.RECONNECTING
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: Any = None

    # -- what the console uses ---------------------------------------------

    @property
    def state(self) -> State:
        """What the upstream is doing right now."""
        return self._state

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Begin holding the upstream. Idempotent, and never raises."""
        if loop is not None:
            self._loop = loop
        if self._loop is None:
            with suppress(RuntimeError):
                self._loop = asyncio.get_running_loop()
        if self._thread is not None:
            return
        thread = threading.Thread(
            target=self._run, name="agent-inbox-relay", daemon=True
        )
        self._thread = thread
        try:
            thread.start()
        except RuntimeError:  # pragma: no cover - a machine that will not give a thread
            self._thread = None

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Update]]:
        """A queue of updates for one viewer, unsubscribed however the caller leaves.

        **The current state is delivered immediately**, before any event. A page that
        connected while the upstream was down would otherwise sit showing nothing and
        saying nothing until the next transition — which on a hub that stays down is
        never, so it would look exactly like a working feed on a quiet hub.
        """
        queue: asyncio.Queue[Update] = asyncio.Queue(maxsize=SUBSCRIBER_DEPTH)
        queue.put_nowait(Update.line(self._state))
        with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            with self._lock:
                self._subscribers.discard(queue)

    def close(self) -> None:
        """Let go of the upstream. Idempotent, and never raises."""
        self._stopped.set()
        _shut(self._response)
        thread, self._thread = self._thread, None
        if thread is not None:
            # Bounded: the thread may be blocked in a read that closing does not always
            # interrupt. It is a daemon, so a straggler delays no shutdown.
            thread.join(timeout=2.0)

    # -- the thread --------------------------------------------------------

    def _run(self) -> None:
        """Connect, read, reconnect — until told to stop. Silent on every path."""
        attempt = 0
        while not self._stopped.is_set():
            opened_at: float | None = None
            try:
                opened_at = self._read_one_connection()
            except urllib.error.HTTPError as refusal:
                if refusal.code in FINAL_STATUSES:
                    # This hub will not stream to us at all. Saying `reconnecting` for
                    # ever would be a lie told once a second.
                    self._publish_state(State.LOST)
                    return
            except Exception:  # noqa: BLE001 - a dropped upstream is not the console's to raise
                # Swallowed because the console's pages must keep serving while the
                # stream is down; the state published below is how anyone finds out.
                logger.debug("relay upstream failed", exc_info=True)
            if opened_at is not None and time.monotonic() - opened_at >= SETTLED_AFTER:
                attempt = 0
            self._publish_state(
                State.LOST if attempt >= ATTEMPTS_BEFORE_LOST else State.RECONNECTING
            )
            if self._stopped.wait(reconnect_delay(attempt)):
                return
            attempt += 1

    def _read_one_connection(self) -> float:
        """Hold one upstream connection until it ends."""
        response = self._connect(self._url, self._headers)
        self._response = response
        opened_at = time.monotonic()
        self._publish_state(State.OPEN)
        try:
            parser = SseParser()
            while not self._stopped.is_set():
                # A line at a time: server-sent events are a line format, and a buffered
                # `read(n)` would sit on a small event waiting for bytes a quiet hub
                # never sends. The parser accepts any chunking.
                line = response.readline()
                if not line:
                    return opened_at  # the hub closed; reconnect
                for event in parser.feed(line.decode("utf-8", "replace")):
                    if event.event == ARRIVAL_EVENT:
                        self._publish(Update.mail(event.data))
        finally:
            self._response = None
            _shut(response)
        return opened_at

    # -- delivery ----------------------------------------------------------

    def _publish_state(self, state: State) -> None:
        """Record and announce a transition. Announced only when it *is* one."""
        if state == self._state:
            return
        self._state = state
        logger.info("event=console.relay.state state=%s", state)
        self._publish(Update.line(state))

    def _publish(self, update: Update) -> None:
        """Hand an update to every subscriber, from the reader thread.

        Subscribers hold `asyncio.Queue`s belonging to the console's event loop, and
        this runs on a plain thread, so delivery is marshalled onto that loop rather
        than touching the queues directly — an `asyncio.Queue` is not thread-safe, and
        the failure would be rare, silent and impossible to reproduce.
        """
        loop = self._loop
        if loop is None:  # pragma: no cover - start() resolves this
            return
        with self._lock:
            queues = tuple(self._subscribers)
        for queue in queues:
            try:
                loop.call_soon_threadsafe(self._offer, queue, update)
            except RuntimeError:  # pragma: no cover - the loop closed under us
                return

    @staticmethod
    def _offer(queue: asyncio.Queue[Update], update: Update) -> None:
        """Put, or drop.

        A viewer this far behind should reload, not stall everyone else.
        """
        try:
            queue.put_nowait(update)
        except asyncio.QueueFull:
            logger.warning("event=console.relay.dropped reason=behind")


def _shut(response: Any) -> None:
    if response is None:
        return
    try:
        response.close()
    except Exception:  # noqa: BLE001 - closing is best-effort by definition
        pass
