"""One upstream connection, many viewers — and a line that says what it is doing.

Two properties carry this module, and they fail in opposite ways.

**One connection.** If it broke, ten operators would hold ten of the hub's sixty-four
slots and nothing would say so until the hub started refusing agents. Asserted on the
count, because the count is the thing that would be wrong.

**State is published, never inferred.** From a browser a quiet hub and a dead connection
are both silence, so a page that worked it out for itself could not tell them apart —
and would keep pulsing confidently over a feed that stopped an hour ago. Every state
test here is paired with its opposite: a *quiet* upstream must stay `open`, or a relay
that cried `lost` constantly would satisfy every failure test in the file.

No sockets and no sleeping. The upstream is a fake the test drives line by line, which
is the same choice `tests/test_wake_stream.py` made and for the same reason.
"""

import asyncio
import threading
import urllib.error

import pytest

from agent_inbox.client import Config, HubClient
from agent_inbox.relay import ATTEMPTS_BEFORE_LOST, Relay, State, Update

PATIENCE = 5.0


class FakeUpstream:
    """A stream the test feeds by hand, and can break on purpose."""

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self._ready = threading.Condition()
        self.closed = False
        self.opened = threading.Event()

    def push(self, raw: str) -> None:
        with self._ready:
            self.lines.append(raw.encode())
            self._ready.notify_all()

    def send_event(self, data: str) -> None:
        """A complete SSE frame, as the hub actually writes one."""
        self.push("event: mail\n")
        self.push(f"data: {data}\n")
        self.push("\n")

    def drop(self) -> None:
        """End the connection, as a proxy timing out would."""
        with self._ready:
            self.lines.append(b"")
            self._ready.notify_all()

    def readline(self) -> bytes:
        with self._ready:
            while not self.lines:
                if not self._ready.wait(timeout=PATIENCE):
                    return b""
            return self.lines.pop(0)

    def close(self) -> None:
        self.closed = True


class Upstreams:
    """A sequence of connections, so a test can decide what the *next* attempt gets."""

    def __init__(self, *plan: object) -> None:
        self.plan = list(plan)
        self.opened: list[FakeUpstream] = []
        self.attempts = 0
        self.exhausted = threading.Event()

    def __call__(self, url: str, headers: dict[str, str]) -> FakeUpstream:
        self.attempts += 1
        nxt = self.plan.pop(0) if self.plan else FakeUpstream()
        if not self.plan:
            self.exhausted.set()
        if isinstance(nxt, Exception):
            raise nxt
        assert isinstance(nxt, FakeUpstream)
        self.opened.append(nxt)
        nxt.opened.set()
        return nxt


def a_client() -> HubClient:
    return HubClient(Config(hub="http://hub.invalid", name="jed_smith", token="tok"))


async def next_update(queue: asyncio.Queue[Update], kind: str) -> Update:
    """The next update of one kind, ignoring the other."""
    async with asyncio.timeout(PATIENCE):
        while True:
            update = await queue.get()
            if update.kind == kind:
                return update


async def state_becomes(queue: asyncio.Queue[Update], wanted: State) -> None:
    async with asyncio.timeout(PATIENCE):
        while True:
            update = await queue.get()
            if update.kind == "state" and update.state == wanted:
                return


class TestOneConnection:
    async def test_many_viewers_cost_one_upstream(self) -> None:
        """NFR-001, and the reason this module exists at all."""
        upstreams = Upstreams(FakeUpstream())
        relay = Relay(a_client(), connect=upstreams)
        relay.start(asyncio.get_running_loop())
        try:
            with (
                relay.subscribe(),
                relay.subscribe(),
                relay.subscribe(),
                relay.subscribe(),
                relay.subscribe(),
            ):
                assert relay.subscriber_count() == 5
                await asyncio.sleep(0.05)
                assert upstreams.attempts == 1
        finally:
            relay.close()

    async def test_leaving_unsubscribes(self) -> None:
        relay = Relay(a_client(), connect=Upstreams(FakeUpstream()))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe():
                assert relay.subscriber_count() == 1
            assert relay.subscriber_count() == 0
        finally:
            relay.close()

    async def test_an_event_reaches_every_subscriber(self) -> None:
        upstream = FakeUpstream()
        relay = Relay(a_client(), connect=Upstreams(upstream))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as first, relay.subscribe() as second:
                upstream.opened.wait(PATIENCE)
                upstream.send_event('{"id":"m1","subject":"hello"}')

                assert "m1" in (await next_update(first, "mail")).data
                assert "m1" in (await next_update(second, "mail")).data
        finally:
            relay.close()

    async def test_the_payload_is_forwarded_verbatim(self) -> None:
        """The relay forwards; it does not interpret.

        A second definition of the event next to the hub's would drift the first time a
        field was added, and the drift would be invisible until a page stopped showing
        something.
        """
        upstream = FakeUpstream()
        relay = Relay(a_client(), connect=Upstreams(upstream))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                upstream.opened.wait(PATIENCE)
                upstream.send_event('{"id":"m1","from":"a","subject":"s","extra":1}')

                got = await next_update(queue, "mail")

                assert got.data == '{"id":"m1","from":"a","subject":"s","extra":1}'
        finally:
            relay.close()


class TestTheLineSaysWhatItIsDoing:
    async def test_a_new_subscriber_is_told_the_state_immediately(self) -> None:
        """A page that connected while the upstream was down must not sit mute.

        On a hub that stays down there is no next transition, so a subscriber waiting
        for one would wait for ever — looking exactly like a working feed on a quiet
        hub, which is the confusion this whole module exists to prevent.
        """
        relay = Relay(a_client(), connect=Upstreams(FakeUpstream()))
        try:
            with relay.subscribe() as queue:
                first = queue.get_nowait()

                assert first.kind == "state"
                assert first.state is not None
        finally:
            relay.close()

    async def test_connecting_publishes_open(self) -> None:
        upstream = FakeUpstream()
        relay = Relay(a_client(), connect=Upstreams(upstream))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.OPEN)
                assert relay.state is State.OPEN
        finally:
            relay.close()

    async def test_a_dropped_upstream_publishes_reconnecting(self) -> None:
        first, second = FakeUpstream(), FakeUpstream()
        relay = Relay(a_client(), connect=Upstreams(first, second))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.OPEN)
                first.drop()

                await state_becomes(queue, State.RECONNECTING)
        finally:
            relay.close()

    async def test_it_recovers_and_says_so(self) -> None:
        first, second = FakeUpstream(), FakeUpstream()
        relay = Relay(a_client(), connect=Upstreams(first, second))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.OPEN)
                first.drop()
                await state_becomes(queue, State.RECONNECTING)

                await state_becomes(queue, State.OPEN)  # the second connection
        finally:
            relay.close()

    async def test_repeated_failure_becomes_lost(self) -> None:
        """`reconnecting` for ever is a lie told once a second."""
        failures = [OSError("no route") for _ in range(ATTEMPTS_BEFORE_LOST + 2)]
        relay = Relay(a_client(), connect=Upstreams(*failures))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.LOST)
        finally:
            relay.close()

    async def test_a_hub_that_refuses_outright_is_lost_at_once(self) -> None:
        """A 404 means this hub has no such route. Retrying it for ever is hammering."""
        refusal = urllib.error.HTTPError("u", 404, "no", {}, None)  # type: ignore[arg-type]
        relay = Relay(a_client(), connect=Upstreams(refusal))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.LOST)
        finally:
            relay.close()

    async def test_a_quiet_upstream_stays_open(self) -> None:
        """**The paired positive**, and the one that makes the rest mean anything.

        Without it, a relay that published `lost` unconditionally would satisfy every
        failure test above — and a console that always claimed the line was down would
        be exactly as useless as one that always claimed it was up.
        """
        upstream = FakeUpstream()
        relay = Relay(a_client(), connect=Upstreams(upstream))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.OPEN)

                await asyncio.sleep(0.2)  # a quiet hub, sending nothing at all

                assert relay.state is State.OPEN
                while not queue.empty():
                    update = queue.get_nowait()
                    assert update.state is not State.LOST, "silence was read as failure"
        finally:
            relay.close()


class TestItNeverGetsInTheWay:
    async def test_a_failing_upstream_does_not_raise_into_the_console(self) -> None:
        """The console's pages must keep serving while the stream is down."""
        relay = Relay(a_client(), connect=Upstreams(OSError("boom"), FakeUpstream()))
        relay.start(asyncio.get_running_loop())
        try:
            with relay.subscribe() as queue:
                await state_becomes(queue, State.OPEN)
        finally:
            relay.close()

    async def test_closing_twice_is_harmless(self) -> None:
        relay = Relay(a_client(), connect=Upstreams(FakeUpstream()))
        relay.start(asyncio.get_running_loop())
        relay.close()
        relay.close()

    async def test_starting_twice_holds_one_connection(self) -> None:
        upstreams = Upstreams(FakeUpstream())
        relay = Relay(a_client(), connect=upstreams)
        loop = asyncio.get_running_loop()
        relay.start(loop)
        relay.start(loop)
        try:
            await asyncio.sleep(0.05)
            assert upstreams.attempts == 1
        finally:
            relay.close()

    async def test_it_authenticates_like_every_other_call(self) -> None:
        """Duplicated auth is how a stream works on an open hub and is refused on a
        closed one, months after the change that caused it."""
        seen: list[dict[str, str]] = []

        def spy(url: str, headers: dict[str, str]) -> FakeUpstream:
            seen.append(headers)
            return FakeUpstream()

        relay = Relay(a_client(), connect=spy)
        relay.start(asyncio.get_running_loop())
        try:
            await asyncio.sleep(0.05)
        finally:
            relay.close()

        assert seen and seen[0]["Authorization"] == "Bearer tok"

    async def test_it_reads_the_hub_wide_stream_not_one_actors(self) -> None:
        seen: list[str] = []

        def spy(url: str, headers: dict[str, str]) -> FakeUpstream:
            seen.append(url)
            return FakeUpstream()

        relay = Relay(a_client(), connect=spy)
        relay.start(asyncio.get_running_loop())
        try:
            await asyncio.sleep(0.05)
        finally:
            relay.close()

        assert seen and seen[0].endswith("/observe/events")
        assert "jed_smith" not in seen[0]


async def test_a_subscriber_that_falls_behind_is_dropped_not_stalled() -> None:
    """One stuck browser must not hold up everybody else's feed."""
    upstream = FakeUpstream()
    relay = Relay(a_client(), connect=Upstreams(upstream))
    relay.start(asyncio.get_running_loop())
    try:
        with relay.subscribe() as slow, relay.subscribe() as quick:
            upstream.opened.wait(PATIENCE)
            for n in range(200):  # far past SUBSCRIBER_DEPTH
                upstream.send_event(f'{{"id":"m{n}"}}')
            await asyncio.sleep(0.3)

            assert not slow.empty()
            assert not quick.empty()
    finally:
        relay.close()


@pytest.mark.parametrize("state", list(State))
def test_every_state_has_a_distinct_wire_word(state: State) -> None:
    """The page renders these strings, so a collision would merge two meanings."""
    assert len({s.value for s in State}) == len(list(State))
    assert state.value.islower()
