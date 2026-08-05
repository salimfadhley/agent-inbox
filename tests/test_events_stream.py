"""The hub telling a client that mail arrived, and everything it must not tell it.

Three groups, and they are not equally important.

**Disclosure** is the group that carries the weight. This route is a new way for one
identity's mail to reach another identity's process, and every requirement about who may
hear what is a security requirement wearing ordinary clothes. Each of those tests was
proved by removal — the guard deleted, the test watched to fail — because a test that
would pass with the guard gone is not testing the guard.

**Content** is where the design could be lost quietly. The event says *that* mail
exists; the moment a body rides along, this becomes a second way to read mail, one that
consumes nothing and records no read, and the mailbox has two answers to "has this been
seen".

**Independence** is the promise to everyone who never uses this at all. A hub that emits
events must be indistinguishable, to a polling client, from one that does not.
"""

import asyncio
import inspect
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn

from agent_inbox.api import IDENTITY_HEADER, Api, build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.notify import Arrival, Listeners, TooManyListeners
from agent_inbox.records import ObjectRecord
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"
ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"
YITZHAK = "yitzhak_levin"

#: Long enough that a slow machine does not fail a passing test, short enough that a
#: genuinely broken one fails in seconds rather than hanging the suite.
PATIENCE = 5.0


def as_(name: str) -> dict[str, str]:
    return {IDENTITY_HEADER: name}


def note(to: list[str], content: str, **kw: object) -> dict:
    return {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Create",
        "object": {"type": "Note", "to": to, "content": content, **kw},
    }


def a_record(**kw: object) -> ObjectRecord:
    fields: dict[str, object] = {
        "id": "m1",
        "attributed_to": TREVOR,
        "to": (ROSEMARY,),
        "cc": (),
        "in_reply_to": None,
        "summary": "a subject",
        "content": "the body",
        "published": "2026-08-01T00:00:00+00:00",
    }
    return ObjectRecord(**{**fields, **kw})  # type: ignore[arg-type]


def a_house(**kw: object) -> House:
    return House(Mailbox(InMemoryStore(), hub_name="testhub"), **kw)  # type: ignore[arg-type]


class TestTheRegistry:
    """`Listeners` alone, with no hub around it. Where the invariants actually live."""

    def test_nobody_listening_is_the_ordinary_case(self) -> None:
        """Zero is not an error and never was. Mail waits, as it always has."""
        listeners = Listeners()
        reached = listeners.announce(ROSEMARY, Arrival("m1", TREVOR, "hello", "now"))
        assert reached == 0
        assert listeners.count() == 0

    async def test_two_sessions_as_one_agent_are_both_told(self) -> None:
        """One queue per connection, not per actor.

        Two sessions running as the same agent is the normal case for this project —
        a laptop with several harnesses open — and neither may consume the other's
        event, exactly as neither consumes the other's mail.
        """
        listeners = Listeners()
        with (
            listeners.listening(ROSEMARY) as first,
            listeners.listening(ROSEMARY) as second,
        ):
            assert listeners.count_for(ROSEMARY) == 2
            listeners.announce(ROSEMARY, Arrival("m1", TREVOR, "hello", "now"))
            assert first.get_nowait().id == "m1"
            assert second.get_nowait().id == "m1"

    async def test_a_closed_connection_stops_being_counted(self) -> None:
        """The leak that presents as working: entries left by clients long gone."""
        listeners = Listeners()
        with listeners.listening(ROSEMARY):
            assert listeners.count() == 1
        assert listeners.count() == 0
        assert listeners.by_actor() == {}

    async def test_it_unregisters_even_when_the_stream_is_cancelled(self) -> None:
        """Cancellation is what a client vanishing looks like from inside the hub.

        If this is not handled the registry fills with connections that closed hours
        ago, and the hub refuses new ones while holding nothing.
        """
        listeners = Listeners()
        started = asyncio.Event()

        async def hold() -> None:
            with listeners.listening(ROSEMARY) as queue:
                started.set()
                await queue.get()

        task = asyncio.create_task(hold())
        await started.wait()
        assert listeners.count() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert listeners.count() == 0

    async def test_a_client_that_has_fallen_behind_loses_events_not_mail(self) -> None:
        """A full queue drops, says so, and never blocks the sender.

        The alternative — waiting for a slow reader — makes one wedged client able to
        stall every send on the hub. The client that misses events has lost immediacy
        and nothing else: its mail is in the store, and polling is still first-class.
        """
        listeners = Listeners(queue_depth=2)
        with listeners.listening(ROSEMARY) as queue:
            for n in range(5):
                listeners.announce(ROSEMARY, Arrival(f"m{n}", TREVOR, "hi", "now"))
            assert queue.qsize() == 2

    async def test_the_cap_refuses_and_leaves_open_connections_alone(self) -> None:
        """FR-007: bounded, and a refusal that harms nothing already working."""
        listeners = Listeners(max_listeners=1)
        with listeners.listening(ROSEMARY) as held:
            with pytest.raises(TooManyListeners, match="maximum of 1"):
                listeners.open(TREVOR)
            # The point of the test: the connection that was already open still works.
            listeners.announce(ROSEMARY, Arrival("m1", TREVOR, "hello", "now"))
            assert held.get_nowait().id == "m1"


class TestTheEventItself:
    """What crosses the wire, and what must never."""

    def test_it_carries_no_body(self) -> None:
        """FR-002. Asserted on the *whole* payload, not on one absent key.

        `assert "content" not in event` passes cheerfully the day a body arrives under
        another name, which is exactly how this requirement would be lost.
        """
        event = Arrival.of(a_record()).as_event()
        assert set(event) == {"id", "from", "subject", "published"}
        assert "the body" not in str(event)

    def test_an_absent_subject_is_an_empty_one(self) -> None:
        """Rather than a missing key, which makes every client write the same branch."""
        assert Arrival.of(a_record(summary=None)).as_event()["subject"] == ""


class TestDisclosure:
    """Who may hold a stream, and whose mail they may hear about."""

    def test_a_connection_without_a_name_is_refused(self) -> None:
        with ServedHub() as hub, pytest.raises(urllib.error.HTTPError) as refusal:
            hub.hold(f"/actors/{ROSEMARY}/events", {})
        assert refusal.value.code == 400
        assert IDENTITY_HEADER in refusal.value.read().decode()

    def test_a_connection_as_somebody_else_is_refused(self) -> None:
        """The same rule every per-actor route shares, and for the same reason.

        **Served for real, and that is not incidental.** Written against a `TestClient`
        this test *hung* when the guard was removed rather than failing: the client
        waits for a complete body, the refusal had become an endless stream, and a test
        that hangs is a test whose failure nobody reads. Over a socket the removal is
        loud — `urlopen` returns an open stream instead of raising, and the assertion
        fails in the ordinary way.

        Proved by removal: with the `owns` call deleted from `Api.events`, Trevor is
        handed a live stream on Rosemary's mailbox.
        """
        with ServedHub() as hub, pytest.raises(urllib.error.HTTPError) as refusal:
            hub.hold(f"/actors/{ROSEMARY}/events", as_(TREVOR))
        assert refusal.value.code == 403
        detail = refusal.value.read().decode()
        assert ROSEMARY in detail and TREVOR in detail

    async def test_mail_for_somebody_else_produces_no_event(self) -> None:
        """The disclosure case, at the layer where the mistake would be made."""
        listeners = Listeners()
        house = a_house(listeners=listeners)
        async with house:
            for name in (ROSEMARY, TREVOR, YITZHAK):
                await house.mailbox.join(name)
            with listeners.listening(ROSEMARY) as rosemary_hears:
                await house.send(TREVOR, [YITZHAK], "not for you", subject="private")
                assert rosemary_hears.empty()

    async def test_a_cc_recipient_is_told_because_they_are_a_recipient(self) -> None:
        """Not a special case — `local_recipients` already includes cc, and should."""
        listeners = Listeners()
        house = a_house(listeners=listeners)
        async with house:
            for name in (ROSEMARY, TREVOR, YITZHAK):
                await house.mailbox.join(name)
            with listeners.listening(YITZHAK) as yitzhak_hears:
                await house.send(
                    TREVOR, [ROSEMARY], "for you both", subject="hi", cc=[YITZHAK]
                )
                assert yitzhak_hears.get_nowait().sender == TREVOR


class TestTheSendIsUnaffected:
    """The requirement that outranks every other one in this mission."""

    async def test_a_broken_notifier_cannot_fail_a_send(self) -> None:
        """A hub that refuses mail because nobody could be told has inverted itself.

        `announce` is written not to raise. This proves the guarantee holds anyway, for
        the version of this module that somebody edits later without reading the comment
        explaining why it must not.
        """

        class Exploding(Listeners):
            def announce(self, actor: str, arrival: Arrival) -> int:
                raise RuntimeError("the notifier is broken")

        house = a_house(listeners=Exploding())
        async with house:
            for name in (ROSEMARY, TREVOR):
                await house.mailbox.join(name)
            sent = await house.send(TREVOR, [ROSEMARY], "still arrives", subject="hi")
            assert sent.record.content == "still arrives"
            # And it is genuinely in the mailbox, not merely returned.
            assert [m.id for m in await house.peek(ROSEMARY)] == [sent.record.id]

    def test_a_stream_that_is_never_read_holds_no_slot(self) -> None:
        """Building the response must not register anything. Only reading does.

        The leak this pins is invisible and permanent. An earlier version registered
        beside the capacity check, above the generator, which reads better — and if the
        response is never iterated, because the client disconnected between the headers
        and the first frame, the `finally` that unregisters never runs at all: a
        generator that was never started has nothing to unwind. Every such connection
        burned one slot out of the cap for the lifetime of the process, until the hub
        refused new streams while holding none.

        Written against the count rather than against a disconnect, because the count is
        the thing that would be wrong and it can be asked directly.
        """
        house = a_house()
        api = Api(house, HUB)
        response = api.events(ROSEMARY, ROSEMARY)
        assert response is not None
        assert house.listeners.count() == 0

    def test_announce_stays_synchronous(self) -> None:
        """Two guarantees rest on this, and both fail silently if it changes.

        `House._announce` calls `announce` without awaiting it. Made `async def`, the
        call would build a coroutine, never run it, and deliver **nothing** — a mailbox
        that has quietly stopped notifying anybody, with a "coroutine was never awaited"
        warning as its only symptom. And the narrower `except Exception` there is
        correct only because nothing inside it can be cancelled, which is true only
        while this is synchronous.

        An outside review raised the `BaseException` question; this is the assumption
        that made the answer "no", written down as something that fails loudly.
        """
        assert not inspect.iscoroutinefunction(Listeners.announce)

    async def test_mail_that_arrived_with_a_listener_is_ordinary_mail(self) -> None:
        """FR-009: nothing about the socket changes what mail *is*.

        Two messages, one sent with a stream open and one without, compared on
        everything a recipient can observe. An event is a way to hear about mail, not a
        different kind of message.
        """
        listeners = Listeners()
        house = a_house(listeners=listeners)
        async with house:
            for name in (ROSEMARY, TREVOR):
                await house.mailbox.join(name)
            with listeners.listening(ROSEMARY):
                heard = await house.send(TREVOR, [ROSEMARY], "one", subject="s")
            unheard = await house.send(TREVOR, [ROSEMARY], "two", subject="s")

            waiting = {m.id: m for m in await house.peek(ROSEMARY)}
            assert set(waiting) == {heard.record.id, unheard.record.id}
            observable = lambda m: (m.attributed_to, m.to, m.cc, m.summary, m.content)  # noqa: E731
            assert (
                observable(waiting[heard.record.id])[:4]
                == observable(waiting[unheard.record.id])[:4]
            )
            # Both consume identically, and both leave a read record.
            assert (await house.read(ROSEMARY, heard.record.id)).id == heard.record.id
            second = await house.read(ROSEMARY, unheard.record.id)
            assert second.id == unheard.record.id
            assert not await house.peek(ROSEMARY)


class ServedHub:
    """One hub, served for real on a socket, in a thread.

    Not a `TestClient`. Litestar's test transports deliver a response once, complete,
    which is the one thing an endless stream never is — a client would block for ever
    waiting for a body that is not going to end. Everything else in this file can be
    tested without a socket and is; these two cannot, and they are the tests that would
    catch a wrong media type, a mis-framed event, or a route that is not wired up.

    Copied in shape from `tests/federation/test_two_real_hubs.py`, which needed a real
    server for the same underlying reason.
    """

    def __init__(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = int(probe.getsockname()[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.house = a_house()
        self._server = uvicorn.Server(
            uvicorn.Config(
                build_api(self.house, self.base),
                host="127.0.0.1",
                port=self.port,
                log_level="error",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> ServedHub:
        self._thread.start()
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{self.base}/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("the hub did not come up")
        for name in (ROSEMARY, TREVOR):
            assert self.post("/actors", {"preferredUsername": name})[0] == 201
        return self

    def __exit__(self, *_: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def post(
        self, path: str, body: dict, headers: dict[str, str] | None = None
    ) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=PATIENCE) as response:
            return response.status, json.loads(response.read() or b"null")

    def get(self, path: str, headers: dict[str, str] | None = None) -> dict:
        request = urllib.request.Request(f"{self.base}{path}", headers=headers or {})
        with urllib.request.urlopen(request, timeout=PATIENCE) as response:
            return json.loads(response.read() or b"null")

    def hold(self, path: str, headers: dict[str, str]):
        """Open a stream and return the response, headers received, body still open."""
        request = urllib.request.Request(f"{self.base}{path}", headers=headers)
        return urllib.request.urlopen(request, timeout=PATIENCE)


def first_event(stream) -> dict[str, object]:
    """Read frames off a held stream until one is an event, not a keep-alive."""
    fields: dict[str, str] = {}
    while True:
        raw = stream.readline()
        if not raw:
            raise AssertionError("the stream ended without delivering an event")
        line = raw.decode().rstrip("\r\n")
        if line.startswith(":"):
            continue  # a comment: the keep-alive frame, which carries no event
        if not line:
            if "data" in fields:
                return {**fields, "data": json.loads(fields["data"])}
            fields = {}
            continue
        key, _, value = line.partition(":")
        fields[key] = value.lstrip()


class TestOverHttp:
    """Two real round trips, because the framing is part of the contract."""

    def test_a_held_stream_is_told_when_mail_arrives(self) -> None:
        """End to end: hold the stream, send from elsewhere, hear about it."""
        with ServedHub() as hub:
            stream = hub.hold(f"/actors/{ROSEMARY}/events", as_(ROSEMARY))
            try:
                assert stream.status == 200
                assert stream.headers["content-type"].startswith("text/event-stream")

                status, sent = hub.post(
                    f"/actors/{TREVOR}/outbox",
                    note([ROSEMARY], "the body", summary="a subject"),
                    as_(TREVOR),
                )
                assert status == 201

                frame = first_event(stream)
            finally:
                stream.close()

        assert frame["event"] == "mail"
        data = frame["data"]
        assert isinstance(data, dict)
        assert data["from"] == TREVOR
        assert data["subject"] == "a subject"
        # FR-008: the id alone is enough to fetch it by the ordinary route.
        assert data["id"] == str(sent["id"]).rsplit("/", 1)[-1]
        # FR-002, on the wire this time rather than in the dataclass.
        assert "the body" not in str(frame)

    def test_the_count_is_visible_and_says_what_it_counts(self) -> None:
        """FR-007. And the name is the point: sessions listening, never "online"."""
        with ServedHub() as hub:
            assert hub.get("/observe/stats")["listeningSessions"] == 0
            stream = hub.hold(f"/actors/{ROSEMARY}/events", as_(ROSEMARY))
            try:
                during = hub.get("/observe/stats")
                assert during["listeningSessions"] == 1
                assert during["listeningBy"] == {ROSEMARY: 1}
            finally:
                stream.close()


class TestTheStreamCarriesNoBody:
    """WP01's central promise, and the one that would be quietly broken by a helpful
    change: the event says *that* mail exists and enough to decide whether to fetch it —
    never the message itself.

    Proved live against the deployment on 2026-08-05 (WP01/T008): an event arrived 0.04s
    after the send, carrying `id`, `from`, `subject` and `published`, and nothing else.
    This is the same assertion pinned where CI can keep it.
    """

    def test_the_wire_fields_are_exactly_the_four(self) -> None:
        from agent_inbox.notify import Arrival

        frame = Arrival(
            id="m-1",
            sender="rosemary_nasrin",
            subject="a subject",
            published="2026-08-05",
        ).as_event()

        assert sorted(frame) == ["from", "id", "published", "subject"]

    def test_a_body_cannot_reach_the_wire(self) -> None:
        """The negative that matters. A body pushed at a client is a body nobody asked
        for, and it would make this stream a second way to read mail — consuming
        nothing and leaving no read record.
        """
        from agent_inbox.notify import Arrival

        frame = Arrival(
            id="m-1", sender="x", subject="s", published="2026-08-05"
        ).as_event()

        assert not any(key in frame for key in ("content", "body", "message"))
