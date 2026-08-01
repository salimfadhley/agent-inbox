"""The client half: parsing the stream, and holding it open across a hub restart.

Two things are worth testing here and they are not the same thing.

**The framing** is pure and gets the detailed treatment, because every mistake in it is
one a hand-written test would not make. A stream does not arrive as tidy events: reads
return whatever the socket had, which is regularly half a line, and on a quiet mailbox
the *only* traffic is keep-alive comments. A parser that works on the examples in the
specification and breaks on a split packet is the normal outcome.

**The holding** is tested for the two failures that actually cost something: a reconnect
loop that spins, and a client that keeps asking a hub which will never answer. Neither
shows up as an error — both look like a working client that quietly does nothing, or a
hub being hammered by a client its operator believes is idle.

What is deliberately *not* here: any assertion that an agent was interrupted. Nothing an
agent experiences changes in this work package. Hearing is not waking.
"""

import asyncio
import json

import pytest

from agent_inbox.client import SseEvent, SseParser
from agent_inbox.mcp_client import _RECONNECT_CAP, reconnect_delay


class TestTheFraming:
    """`SseParser` alone. No socket, no hub, no event loop."""

    def test_one_ordinary_event(self) -> None:
        parser = SseParser()
        assert parser.feed('event: mail\ndata: {"id": "abc"}\n\n') == [
            SseEvent("mail", '{"id": "abc"}')
        ]

    def test_a_comment_carries_no_event(self) -> None:
        """The keep-alive. On a quiet mailbox this is the only thing on the wire.

        A parser that treated every line as data would emit an event every fifteen
        seconds saying nothing arrived, and a client acting on those would wake an agent
        four times a minute for ever.
        """
        assert SseParser().feed(":keep-alive\n\n") == []

    def test_an_event_split_across_reads_arrives_whole(self) -> None:
        """The failure a hand-written test never produces, and a real socket does.

        Reads return whatever arrived. Any parser that assumes a read is a frame works
        perfectly until the day a packet lands mid-line.
        """
        parser = SseParser()
        assert parser.feed("event: ma") == []
        assert parser.feed('il\ndata: {"id": "a') == []
        assert parser.feed('bc"}\n\n') == [SseEvent("mail", '{"id": "abc"}')]

    def test_two_events_in_one_read_are_both_returned(self) -> None:
        parser = SseParser()
        got = parser.feed("event: mail\ndata: one\n\nevent: mail\ndata: two\n\n")
        assert [e.data for e in got] == ["one", "two"]

    def test_data_lines_are_one_payload(self) -> None:
        """Successive `data:` lines are joined, not separate events."""
        got = SseParser().feed('data: {\ndata:   "id": "abc"\ndata: }\n\n')
        assert len(got) == 1
        assert json.loads(got[0].data) == {"id": "abc"}

    def test_the_id_and_a_default_event_name(self) -> None:
        got = SseParser().feed("id: abc\ndata: hello\n\n")
        assert got == [SseEvent("message", "hello", "abc")]

    def test_carriage_returns_are_not_part_of_the_payload(self) -> None:
        """Which is what the hub actually sends, so getting this wrong breaks everything
        rather than something."""
        got = SseParser().feed("event: mail\r\ndata: hello\r\n\r\n")
        assert got == [SseEvent("mail", "hello")]

    def test_a_field_this_version_does_not_know_is_ignored(self) -> None:
        """Not refused — it is how the hub adds a field without breaking old clients."""
        got = SseParser().feed("event: mail\nretry: 5000\ndata: hello\n\n")
        assert got == [SseEvent("mail", "hello")]

    def test_state_does_not_leak_between_events(self) -> None:
        """An event name or id belongs to its own event and must not carry forward.

        Otherwise one `event: mail` makes every later event on that connection look like
        mail — including keep-alives and anything added in a future release.
        """
        parser = SseParser()
        parser.feed("event: mail\nid: one\ndata: first\n\n")
        assert parser.feed("data: second\n\n") == [SseEvent("message", "second", None)]


class TestTheBackoff:
    """The reconnect delay, which is the difference between polite and a stampede."""

    def test_it_grows_and_then_stops_growing(self) -> None:
        full = {"rand": lambda: 1.0}
        assert reconnect_delay(0, **full) == 1.0
        assert reconnect_delay(3, **full) == 8.0
        # Capped, so a hub that has been down for an hour is not asked constantly.
        assert reconnect_delay(30, **full) == _RECONNECT_CAP

    def test_it_is_jittered_across_the_whole_window(self) -> None:
        """The part usually left out, and the part that matters here.

        This hub is redeployed several times a day and every release disconnects every
        client at the same instant. Without jitter they all wait the same interval and
        reconnect together, so the hub's first act on coming up is to serve a herd it
        created itself — and a herd that fails together retries together.

        Asserted as a *range*, not a value: what matters is that two clients that
        disconnect together do not come back together.
        """
        ceiling = reconnect_delay(4, rand=lambda: 1.0)
        assert reconnect_delay(4, rand=lambda: 0.0) == 0.0
        assert 0 < reconnect_delay(4, rand=lambda: 0.5) < ceiling

    def test_it_never_returns_a_negative_or_a_spin(self) -> None:
        """Zero attempts through the cap, with the extremes of the random source."""
        for attempt in range(0, 40):
            for value in (0.0, 0.5, 1.0):
                delay = reconnect_delay(attempt, rand=lambda v=value: v)
                assert 0.0 <= delay <= _RECONNECT_CAP


class TestHoldingTheStream:
    """The loop, driven against a fake hub rather than a real one.

    A real server would test uvicorn and httpx as much as this code; what needs proving
    is the *decisions* — when to give up, when to come back, and whether a handler that
    explodes can take the connection with it.
    """

    async def test_a_hub_that_will_never_stream_is_not_asked_twice(self) -> None:
        """404, 401, 403: none of these come good by asking again.

        A hub too old to have the route will not grow one during this process's life,
        and a credential this process holds will not become valid by repetition.
        Retrying either is a loop that costs the hub something and the agent nothing —
        and it is invisible, because the client still appears to be working.
        """
        from agent_inbox import mcp_client

        for status in (401, 403, 404, 405):
            attempts = 0

            class OneAnswer:
                def __init__(self, *_: object, **__: object) -> None:
                    pass

                async def __aenter__(self) -> OneAnswer:
                    return self

                async def __aexit__(self, *_: object) -> None:
                    return None

                def stream(self, *_: object, **__: object) -> OneAnswer:
                    nonlocal attempts
                    attempts += 1
                    return self

                status_code = status

                def raise_for_status(self) -> None:
                    raise AssertionError("should have given up before this")

            client = _a_client()
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(mcp_client.httpx, "AsyncClient", OneAnswer)
                await asyncio.wait_for(mcp_client._hold_the_stream(client), timeout=2.0)
            assert attempts == 1, f"{status} was retried"

    async def test_it_delivers_what_it_hears_and_comes_back_after_a_drop(self) -> None:
        """The happy path and the recovery, which are the same loop.

        A hub restart is not an exceptional event here — it happens on every release,
        several times a day — so "the stream ended" has to be ordinary. What must be
        true afterwards is that the client is listening again and that it waited a
        jittered interval first rather than reconnecting instantly in a tight loop.

        The delays are asserted, not just the reconnection. A client that comes back
        immediately also passes a test that only checks it came back, and it is the one
        that turns a routine deploy into a self-inflicted denial of service.
        """
        from agent_inbox import mcp_client

        heard: list[dict[str, object]] = []
        waits: list[int] = []
        attempts = 0

        class Restarting:
            """A hub that serves one event, drops, serves another, then goes away."""

            status_code = 200

            def __init__(self, *_: object, **__: object) -> None:
                pass

            async def __aenter__(self) -> Restarting:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            def stream(self, *_: object, **__: object) -> Restarting:
                nonlocal attempts
                attempts += 1
                if attempts > 2:
                    raise asyncio.CancelledError
                return self

            def raise_for_status(self) -> None:
                return None

            async def aiter_text(self):
                yield f'event: mail\ndata: {{"id": "m{attempts}"}}\n\n'

        def instant(attempt: int) -> float:
            waits.append(attempt)
            return 0.0

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(mcp_client.httpx, "AsyncClient", Restarting)
            patch.setattr(mcp_client, "reconnect_delay", instant)
            patch.setattr(mcp_client, "_on_arrival", heard.append)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(
                    mcp_client._hold_the_stream(_a_client()), timeout=5.0
                )

        assert [a["id"] for a in heard] == ["m1", "m2"]
        # A delay was taken before each reconnection — never a straight retry. Two, not
        # three: the third attempt is cancelled, and cancellation must propagate at once
        # rather than sleeping first. A shutdown that waits out a backoff is a process
        # that will not stop when asked.
        #
        # And *climbing*, `[0, 1]` rather than `[0, 0]`, which is the interaction with
        # the test below. These connections deliver an event and close immediately, so
        # neither lasted long enough to count as proof the hub is healthy. Delivering
        # one message is not the same as being a stream worth trusting, and this
        # assertion said otherwise until the accepts-and-drops case was written.
        assert waits == [0, 1]

    async def test_a_hub_that_accepts_and_drops_is_backed_off(self) -> None:
        """The failure an outside review found, and it is invisible from both ends.

        A hub that *accepts* a connection and immediately closes it — a proxy answering
        200 and hanging up, a server that crashes on its first write — is not an error
        the client ever sees as one. An earlier version reset the backoff as soon as a
        connection was accepted, so this reconnected roughly twice a second for ever,
        with the delay reset each time and nothing in any log to say so. The client
        looks healthy; the hub is being hammered by something its operator believes is
        idle.

        The fix is that a connection has to *last* before it counts as having worked, so
        this asserts the attempt counter climbs rather than that anything failed.
        """
        from agent_inbox import mcp_client

        waits: list[int] = []
        attempts = 0

        class AcceptsAndDrops:
            status_code = 200

            def __init__(self, *_: object, **__: object) -> None:
                pass

            async def __aenter__(self) -> AcceptsAndDrops:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            def stream(self, *_: object, **__: object) -> AcceptsAndDrops:
                nonlocal attempts
                attempts += 1
                if attempts > 4:
                    raise asyncio.CancelledError
                return self

            def raise_for_status(self) -> None:
                return None

            async def aiter_text(self):
                return
                yield  # pragma: no cover - an immediately-closed stream yields nothing

        def instant(attempt: int) -> float:
            waits.append(attempt)
            return 0.0

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(mcp_client.httpx, "AsyncClient", AcceptsAndDrops)
            patch.setattr(mcp_client, "reconnect_delay", instant)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(
                    mcp_client._hold_the_stream(_a_client()), timeout=5.0
                )

        # Climbing, not stuck at zero. Zeros here would be the bug: an accepted-and-
        # dropped connection treated as proof the hub is healthy.
        assert waits == [0, 1, 2, 3]

    async def test_a_handler_that_raises_does_not_end_the_stream(self) -> None:
        """A wake that fails must not cost the client everything it would hear next."""
        from agent_inbox import mcp_client

        seen: list[dict[str, object]] = []

        def explode(arrival: dict[str, object]) -> None:
            seen.append(arrival)
            raise RuntimeError("the decision layer fell over")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(mcp_client, "_on_arrival", explode)
            mcp_client._deliver("mail", '{"id": "one"}')
            mcp_client._deliver("mail", '{"id": "two"}')
        assert [a["id"] for a in seen] == ["one", "two"]

    async def test_an_unknown_event_type_is_ignored(self) -> None:
        """Forward compatibility: a future event must not be read as mail."""
        from agent_inbox import mcp_client

        seen: list[dict[str, object]] = []
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(mcp_client, "_on_arrival", seen.append)
            mcp_client._deliver("something-new", '{"id": "one"}')
            assert seen == []
            mcp_client._deliver("mail", '{"id": "two"}')
            assert [a["id"] for a in seen] == ["two"]


def _a_client() -> object:
    """A hub client that knows an address and a credential and nothing else."""
    from agent_inbox.client import Config, HubClient

    return HubClient(
        Config(
            hub="http://hub.invalid",
            name="rosemary_nasrin",
            role="agent",
            engine="claude",
            token="t",
        )
    )
