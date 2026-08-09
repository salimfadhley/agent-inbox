"""The waiter's event stream — mission `wake-without-polling-01KZ23TA`.

`tests/test_wake.py` proves the decision (`wake_response`) and the loop as it was when
it only polled. This proves the connection that now sits underneath, and the one
property everything else rests on: **the stream can only ever shorten a sleep**.

Nothing here opens a socket. The reader takes its connection from a factory, so a test
hands it bytes at moments of its choosing and there is no timing to be flaky about.
"""

import threading
import time
import urllib.error

import pytest

from agent_inbox.client import Config, HubClient
from agent_inbox.wake import REARM_SETTLE, ArrivalStream

MAIL = b'event: mail\r\ndata: {"id": "abc"}\r\n\r\n'
KEEPALIVE = b": keep-alive\r\n"
OTHER = b'event: presence\r\ndata: {"who": "ludmila_coe"}\r\n\r\n'


def _client() -> HubClient:
    return HubClient(
        Config(
            hub="http://hub.invalid:8080",
            name="rosemary_nasrin",
            role="agent",
            engine="claude",
            token="a-token",
        )
    )


class FakeConnection:
    """Lines on demand, then a hold — a stream that is open and simply quiet."""

    def __init__(self, lines: list[bytes], *, then_close: bool = True) -> None:
        self.lines = list(lines)
        self.then_close = then_close
        self.closed = False
        self.released = threading.Event()
        self.drained = threading.Event()

    def readline(self) -> bytes:
        if self.lines:
            line = self.lines.pop(0)
            if not self.lines:
                self.drained.set()
            return line
        if self.then_close:
            return b""  # the hub closed the connection
        # Held open and silent, which is what a real stream is almost all the time.
        self.released.wait(5.0)
        return b""

    def close(self) -> None:
        self.closed = True
        self.released.set()


def _reader(conn: FakeConnection | Exception, **kw) -> ArrivalStream:
    def connect(url: str, headers: dict[str, str]):
        if isinstance(conn, Exception):
            raise conn
        connect.seen = (url, headers)  # type: ignore[attr-defined]
        return conn

    return ArrivalStream(_client(), connect=connect, rand=lambda: 0.0, **kw)


def _woken(stream: ArrivalStream, within: float = 5.0) -> bool:
    """Did an arrival land? Waits rather than sleeping, so it is fast and not racy."""
    started = time.monotonic()
    while time.monotonic() - started < within:
        if stream._arrived.is_set():
            return True
        time.sleep(0.005)
    return False


class TestItSignalsOnArrival:
    """FR-001, FR-002: an arrival on the wire becomes a shortened sleep."""

    def test_a_mail_event_wakes_the_sleeper(self) -> None:
        conn = FakeConnection([MAIL], then_close=False)
        stream = _reader(conn)
        stream.start()
        try:
            began = time.monotonic()
            stream.wait(30.0)  # would sleep half a minute if nothing arrived
            waited = time.monotonic() - began
            assert waited < 5.0, "the arrival did not shorten the sleep"
        finally:
            stream.close()

    def test_with_no_arrival_it_sleeps_the_whole_time(self) -> None:
        """The paired negative. Without it the test above would pass for free."""
        conn = FakeConnection([KEEPALIVE], then_close=False)
        stream = _reader(conn)
        stream.start()
        try:
            began = time.monotonic()
            stream.wait(0.2)
            assert time.monotonic() - began >= 0.19, "it returned early with no mail"
        finally:
            stream.close()

    def test_it_authenticates_as_the_client_does(self) -> None:
        """FR-001. Assembled by `HubClient`, never here — one place decides."""
        client = _client()
        conn = FakeConnection([KEEPALIVE], then_close=False)
        seen: dict[str, object] = {}

        def connect(url: str, headers: dict[str, str]):
            seen["url"], seen["headers"] = url, headers
            return conn

        stream = ArrivalStream(client, connect=connect, rand=lambda: 0.0)
        stream.start()
        try:
            for _ in range(200):  # let the thread reach connect
                if seen:
                    break
                time.sleep(0.005)
            assert seen["url"] == client.events_url()
            assert seen["headers"] == client.stream_headers()
            assert "Authorization" in client.stream_headers()
        finally:
            stream.close()


class TestOnlyMailSignals:
    """FR-011: an unknown event type is ignored, not treated as an arrival."""

    @pytest.mark.parametrize("noise", [KEEPALIVE, OTHER], ids=["keep-alive", "unknown"])
    def test_noise_does_not_wake(self, noise: bytes) -> None:
        conn = FakeConnection([noise], then_close=False)
        stream = _reader(conn)
        stream.start()
        try:
            conn.drained.wait(5.0)
            time.sleep(0.05)
            woke = stream._arrived.is_set()
            assert woke is False, "something other than mail woke it"
        finally:
            stream.close()

    def test_mail_after_noise_still_wakes(self) -> None:
        """The paired positive: the noise above is genuinely reaching the parser."""
        conn = FakeConnection([KEEPALIVE, OTHER, MAIL], then_close=False)
        stream = _reader(conn)
        stream.start()
        try:
            assert _woken(stream), "mail behind a keep-alive did not arrive"
        finally:
            stream.close()


class TestFailingIsNotAnError:
    """FR-008, NFR-004: every failure leaves a usable reader and says nothing."""

    @pytest.mark.parametrize(
        "failure",
        [
            ConnectionRefusedError("hub is down"),
            urllib.error.URLError("no route to host"),
            OSError("something else entirely"),
            RuntimeError("a bug in here"),
        ],
        ids=["refused", "url-error", "os-error", "bug"],
    )
    def test_a_connection_that_raises_is_silent(
        self, failure: Exception, capsys
    ) -> None:
        stream = _reader(failure)
        stream.start()
        try:
            time.sleep(0.05)
            assert stream.connected is False
            began = time.monotonic()
            stream.wait(0.1)
            assert time.monotonic() - began >= 0.09, "wait must behave as time.sleep"
        finally:
            stream.close()
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == "", "a wake must print nothing"

    def test_garbage_on_the_wire_is_silent(self, capsys) -> None:
        conn = FakeConnection([b"\xff\xfe not utf-8 at all\r\n", b"}{\r\n"])
        stream = _reader(conn)
        stream.start()
        try:
            time.sleep(0.05)
            assert stream._arrived.is_set() is False
        finally:
            stream.close()
        assert capsys.readouterr().err == ""

    def test_close_is_idempotent_and_silent(self) -> None:
        stream = _reader(FakeConnection([KEEPALIVE]))
        stream.start()
        stream.close()
        stream.close()  # must not raise


class TestAFinalRefusalStopsAsking:
    """T005's answer, made a rule: 404 and 401 will not come good inside one wait."""

    @staticmethod
    def _http_error(code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError("http://hub.invalid/e", code, "no", {}, None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("code", [401, 403, 404, 405])
    def test_it_gives_up_on_a_final_status(self, code: int) -> None:
        """A hub too old for the route will not grow one in eight hours."""
        attempts = 0

        def connect(url: str, headers: dict[str, str]):
            nonlocal attempts
            attempts += 1
            raise self._http_error(code)

        stream = ArrivalStream(_client(), connect=connect, rand=lambda: 0.0)
        stream.start()
        try:
            time.sleep(0.1)
            assert attempts == 1, "a final refusal was retried"
            assert stream.connected is False
        finally:
            stream.close()

    def test_it_keeps_trying_after_a_retryable_status(self) -> None:
        """The paired positive. A 503 is a hub restarting, and it comes back."""
        attempts = 0

        def connect(url: str, headers: dict[str, str]):
            nonlocal attempts
            attempts += 1
            raise self._http_error(503)

        stream = ArrivalStream(_client(), connect=connect, rand=lambda: 0.0)
        stream.start()
        try:
            for _ in range(200):
                if attempts > 1:
                    break
                time.sleep(0.005)
            assert attempts > 1, "a retryable failure was treated as final"
        finally:
            stream.close()


class TestReconnecting:
    """FR-005: a dropped stream is re-established while the wait has time left."""

    def test_a_closed_stream_is_reopened_and_still_wakes(self) -> None:
        connections: list[FakeConnection] = []

        def connect(url: str, headers: dict[str, str]):
            conn = FakeConnection(
                [MAIL] if connections else [KEEPALIVE],
                then_close=not connections,
            )
            connections.append(conn)
            return conn

        stream = ArrivalStream(_client(), connect=connect, rand=lambda: 0.0)
        stream.start()
        try:
            assert _woken(stream), "mail after a reconnect never arrived"
            assert len(connections) >= 2, "the dropped connection was not replaced"
        finally:
            stream.close()

    def test_the_connection_is_closed_when_the_reader_stops(self) -> None:
        """FR-007. A hook leaking a connection per turn is a hook that gets removed."""
        conn = FakeConnection([KEEPALIVE], then_close=False)
        stream = _reader(conn)
        stream.start()
        for _ in range(200):
            if stream.connected:
                break
            time.sleep(0.005)
        stream.close()
        assert conn.closed, "the connection outlived the reader"


# -- WP02: the waiter's loop, sleeping on the stream ------------------------

#: The streaming interval, shrunk for the tests. The loop's deadline is wall-clock, so
#: a test that used the real sixty seconds would take a real ten minutes to prove the
#: interval is bounded. Shrinking the constant keeps the *shape* — several bounded
#: sleeps rather than one long one — which is the thing being asserted.
#:
#: `BASE` is the unstreamed interval and sits on `_wait_for_wake`'s own floor of
#: 0.1s, so a test asking for less does not silently get the floor instead.
TICK = 0.2
BASE = 0.1


class FakeStream:
    """A stream the loop can be driven against, with no thread and no connection.

    `_wait_for_wake` asks it for exactly three things — start, a sleeper, and close —
    so supplying those three shows the loop's real behaviour and nothing else's.
    """

    def __init__(self, *, connected: bool = True, arrives_after: int | None = None):
        self.connected = connected
        #: Sleep number on which mail "arrives", cutting the sleep short. `None` never.
        self.arrives_after = arrives_after
        self.sleeps: list[float] = []
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def wait(self, seconds: float) -> None:
        """Sleeps for real, unless an arrival cuts it short — as the real one does."""
        self.sleeps.append(seconds)
        if self.arrives_after is not None and len(self.sleeps) >= self.arrives_after:
            return
        time.sleep(seconds)

    def close(self) -> None:
        self.closed = True


def _drive(monkeypatch, tmp_path, stream, unread, **kw) -> int:
    """Run one wait against a supplied stream and a scripted sequence of inboxes."""
    from agent_inbox import wake

    queue = list(unread)

    def fetch_unread(root):
        return queue.pop(0) if queue else []

    monkeypatch.setattr(wake, "_fetch_unread", fetch_unread)
    monkeypatch.setattr(wake, "_stream_for", lambda root: stream)
    monkeypatch.setattr(wake, "STREAMING_POLL_INTERVAL", TICK)
    return wake.run(
        "Stop",
        root=tmp_path,
        wait=True,
        poll_interval=kw.pop("poll_interval", BASE),
        wait_timeout=kw.pop("wait_timeout", 10.0),
        sleep=kw.pop("sleep", lambda _s: None),
    )


def _msg(mid: str) -> dict[str, object]:
    return {"id": mid, "attributedTo": "jed_smith", "summary": "flaky tests"}


class TestTheWaiterSleepsOnTheStream:
    """FR-002, FR-007, NFR-001."""

    def test_an_arrival_reaches_the_wake_by_the_ordinary_path(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """The stream shortens the sleep; `wake_response` still decides what is said."""
        stream = FakeStream(arrives_after=1)
        code = _drive(monkeypatch, tmp_path, stream, [[], [_msg("a")]])

        assert code == 2, "the arrival did not become a wake"
        assert stream.sleeps == [TICK], "the loop did not sleep on the stream"
        assert "flaky tests" in capsys.readouterr().err

    def test_the_stream_is_started_and_closed(self, monkeypatch, tmp_path) -> None:
        stream = FakeStream(arrives_after=1)
        _drive(monkeypatch, tmp_path, stream, [[], [_msg("a")]])
        assert stream.started and stream.closed

    def test_it_is_closed_on_a_timeout_too(self, monkeypatch, tmp_path) -> None:
        stream = FakeStream()
        _drive(monkeypatch, tmp_path, stream, [[]], wait_timeout=0.0)
        assert stream.closed, "a wait that woke nobody still leaked its connection"


class TestTheIntervalIsBounded:
    """FR-006, NFR-002 — and T010's removal proof."""

    def test_it_lengthens_while_the_stream_is_connected(
        self, monkeypatch, tmp_path
    ) -> None:
        stream = FakeStream(connected=True, arrives_after=1)
        _drive(monkeypatch, tmp_path, stream, [[], [_msg("a")]], poll_interval=BASE)
        assert stream.sleeps == [TICK], "a held stream did not lengthen the poll"

    def test_it_stays_at_todays_value_when_nothing_is_connected(
        self, monkeypatch, tmp_path
    ) -> None:
        """A hub with no event route must not get a *slower* wake than it has today."""
        stream = FakeStream(connected=False)  # never signals: there is no stream
        _drive(monkeypatch, tmp_path, stream, [[], [_msg("a")]], poll_interval=BASE)
        assert stream.sleeps == [BASE], "an unstreamed wait was slowed down"

    def test_a_connected_but_silent_stream_is_still_polled(
        self, monkeypatch, tmp_path
    ) -> None:
        """**T010's removal proof.** A proxy that buffers gives a stream that is open,
        looks healthy, and delivers nothing. Only the poll underneath catches it.

        Remove the bound — make the interval `remaining` — and this drops to a single
        sleep spanning the whole wait, so mail that arrived in minute two is announced
        in hour eight. That is the failure this asserts against.
        """
        stream = FakeStream(connected=True)
        _drive(monkeypatch, tmp_path, stream, [], wait_timeout=TICK * 6)

        # The last sleep is the re-arm settle, not a poll (2026-08-09). It is
        # deliberately long and deliberately taken on the *stream*, so that mail landing
        # during it still shortens it — but it is not the interval this bounds.
        polls, settle = stream.sleeps[:-1], stream.sleeps[-1]

        assert len(polls) > 1, "the whole wait was spent in one sleep"
        assert max(polls) <= TICK, "the interval is unbounded"
        assert settle == REARM_SETTLE, (
            "the wait ended with something other than the re-arm settle"
        )


class TestPollingIsStillTheFloor:
    """FR-004, NFR-003 — T009's removal proof."""

    def test_a_hub_with_no_event_route_still_wakes(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """**T009's removal proof.** A hub too old for the route never connects, so
        nothing will ever shorten a sleep. The poll is the only thing that wakes it.

        Delete the poll — leave the loop waiting on the stream alone — and this stops
        waking at all, which is what proves the fallback under test is the fallback.
        """
        # It must never signal. A fake that pretends to would make this pass on the
        # strength of the arrival rather than the poll — which is exactly what the
        # removal proof caught the first time this test was written.
        stream = FakeStream(connected=False)
        code = _drive(monkeypatch, tmp_path, stream, [[], [_msg("a")]])

        assert code == 2, "an unstreamed hub stopped waking"
        # And woke *at the unstreamed interval*, not eventually. Without this second
        # assertion the test passes even with the poll removed, because a single sleep
        # spanning the whole wait still ends in a poll — eight hours late. Waking late
        # enough is not waking.
        assert stream.sleeps == [BASE], "it woke, but only after the whole wait"
        assert "flaky tests" in capsys.readouterr().err

    def test_no_stream_at_all_is_todays_behaviour(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """`_stream_for` returning `None` — unconfigured, unreadable, anything."""
        sleeps: list[float] = []
        code = _drive(
            monkeypatch,
            tmp_path,
            None,
            [[], [_msg("a")]],
            poll_interval=BASE,
            sleep=sleeps.append,
        )

        assert code == 2
        assert sleeps == [BASE], "without a stream the injected sleeper must be used"
        assert "flaky tests" in capsys.readouterr().err
