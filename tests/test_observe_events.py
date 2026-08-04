"""The three routes that let a console watch a hub, over HTTP.

All three are `/observe/*`, which is a promise with two halves: they take no caller, and
they consume nothing. The second is worth asserting rather than reasoning about — the
console reads these on every page load, and a read that consumed would empty an agent's
inbox by being looked at.

`/observe/events` is the hub's counterpart to `/actors/{name}/events`. That one is an
agent's own mail and needs the agent's own credential; this one is the hub working and
needs what every other observe route needs. It discloses nothing new, because a
signed-in operator can already read any mailbox one at a time — it shows the same
authority as motion rather than as a series of lookups.

**The stream is tested against a real socket**, for the reason `test_events_stream.py`
already records: Litestar's test transports deliver a response once, complete, which is
the one thing an endless stream never is. A `TestClient` asked to hold this and then
send a message deadlocks — observed while writing these tests. The plain routes need no
such thing and use `TestClient` as everything else does.
"""

import json
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator

import pytest
import uvicorn
from litestar.testing import TestClient

from agent_inbox.api import (
    DEFAULT_RECENT,
    IDENTITY_HEADER,
    MAX_RECENT,
    Api,
    build_api,
)
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"

#: Long enough that a slow machine does not fail a passing test, short enough that a
#: genuinely broken one fails in seconds rather than hanging the suite.
PATIENCE = 5.0
ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"


@pytest.fixture
def house() -> House:
    return House(Mailbox(InMemoryStore(), hub_name="testhub"))


@pytest.fixture
def client(house: House) -> Iterator[TestClient]:
    with TestClient(app=build_api(house, HUB)) as c:
        yield c


def as_(name: str) -> dict[str, str]:
    return {IDENTITY_HEADER: name}


def join(client: TestClient, *names: str) -> None:
    for name in names:
        assert (
            client.post("/actors", json={"preferredUsername": name}).status_code == 201
        )


def send(client: TestClient, frm: str, to: list[str], **kw: object) -> None:
    r = client.post(
        f"/actors/{frm}/outbox",
        json={
            "@context": "https://www.w3.org/ns/activitystreams",
            "type": "Create",
            "object": {"type": "Note", "to": to, "content": "body", **kw},
        },
        headers=as_(frm),
    )
    assert r.status_code == 201, r.text


class TestTheObservedOutbox:
    def test_it_shows_what_an_agent_sent(self, client: TestClient) -> None:
        join(client, ROSEMARY, TREVOR)
        send(client, ROSEMARY, [TREVOR], summary="outbound")

        r = client.get(f"/observe/outbox/{ROSEMARY}")  # no caller header at all

        assert r.status_code == 200
        assert [n["summary"] for n in r.json()["items"]] == ["outbound"]

    def test_it_is_not_the_inbox(self, client: TestClient) -> None:
        """The paired negative — a route returning everything passes the test above."""
        join(client, ROSEMARY, TREVOR)
        send(client, ROSEMARY, [TREVOR], summary="outbound")

        assert client.get(f"/observe/outbox/{TREVOR}").json()["items"] == []
        inbox = client.get(f"/observe/mailbox/{TREVOR}").json()["items"]
        assert [n["summary"] for n in inbox] == ["outbound"]

    def test_it_consumes_nothing(self, client: TestClient) -> None:
        join(client, ROSEMARY, TREVOR)
        send(client, ROSEMARY, [TREVOR], summary="untouched")

        client.get(f"/observe/outbox/{ROSEMARY}")
        client.get(f"/observe/mailbox/{TREVOR}")

        waiting = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert waiting["totalItems"] == 1, "observing marked the agent's mail read"


class TestTheSnapshot:
    def test_it_returns_recent_traffic(self, client: TestClient) -> None:
        join(client, ROSEMARY, TREVOR)
        send(client, ROSEMARY, [TREVOR], summary="one")
        send(client, TREVOR, [ROSEMARY], summary="two")

        items = client.get("/observe/recent").json()["items"]

        assert [n["summary"] for n in items] == ["one", "two"]

    @pytest.mark.parametrize(
        ("asked", "expected"),
        [
            (MAX_RECENT + 5000, MAX_RECENT),  # clamped down
            (0, 1),  # clamped up — `[-0:]` is the whole store, not nothing
            (-10, 1),
            (2, 2),  # the paired positive: clamping must not become ignoring
            (MAX_RECENT, MAX_RECENT),  # the boundary itself is allowed
        ],
    )
    def test_the_bound_is_the_hubs_to_enforce(
        self, house: House, asked: int, expected: int
    ) -> None:
        """What the storage layer is *actually asked for*, not what a small store gives.

        Written this way after the obvious version turned out to be vacuous: asserting
        `len(items) <= MAX_RECENT` against a store holding five messages passes whether
        the clamp exists or not, so deleting the clamp changed nothing and the test
        stayed green. Observed, not theorised — the removal proof produced no failure.

        Without the clamp, `/observe/recent?limit=100000` is a whole-store dump wearing
        a small name, reachable by any signed-in operator. And `limit=0` is worse than
        it looks: `records[-0:]` is Python for *the entire list*, so an unclamped zero
        returns everything rather than nothing.
        """
        seen: list[int] = []

        async def spy(limit: int) -> tuple[()]:
            seen.append(limit)
            return ()

        house.observe_recent = spy  # type: ignore[method-assign]
        with TestClient(app=build_api(house, HUB)) as spied:
            assert spied.get(f"/observe/recent?limit={asked}").status_code == 200

        assert seen == [expected]

    def test_the_default_is_a_screenful(self, house: House) -> None:
        """A caller that says nothing gets the default, not the maximum."""
        seen: list[int] = []

        async def spy(limit: int) -> tuple[()]:
            seen.append(limit)
            return ()

        house.observe_recent = spy  # type: ignore[method-assign]
        with TestClient(app=build_api(house, HUB)) as spied:
            spied.get("/observe/recent")

        assert seen == [DEFAULT_RECENT]

    def test_it_really_returns_the_newest(self, client: TestClient) -> None:
        """The end-to-end half, so the spy above cannot be the only evidence."""
        join(client, ROSEMARY, TREVOR)
        for n in range(5):
            send(client, ROSEMARY, [TREVOR], summary=str(n))

        items = client.get("/observe/recent?limit=2").json()["items"]

        assert [n["summary"] for n in items] == ["3", "4"]

    def test_it_consumes_nothing(self, client: TestClient) -> None:
        join(client, ROSEMARY, TREVOR)
        send(client, ROSEMARY, [TREVOR], summary="untouched")

        client.get("/observe/recent")

        waiting = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert waiting["totalItems"] == 1, "observing marked the agent's mail read"


class TestTheHubWideStream:
    def test_building_the_response_registers_nothing(self, house: House) -> None:
        """Only *reading* a stream may take a slot.

        The same leak `Api.events` carries a comment about: registering beside the
        capacity check rather than inside the generator burns a slot permanently every
        time a response is never iterated, and a hub that refuses connections while
        holding none is the "presents as working" failure this project keeps finding.
        """
        api = Api(house, HUB)

        response = api.observe_events()

        assert response is not None
        assert house.listeners.count() == 0

    def test_a_watcher_is_not_reported_as_an_agent_session(self, house: House) -> None:
        """`listeningBy` describes actors; a watcher is not listening *as* anybody."""
        with house.listeners.watching():
            assert house.listeners.by_actor() == {}
            assert house.listeners.count() == 1

    def test_the_route_is_registered_and_guarded_like_its_neighbours(
        self, client: TestClient
    ) -> None:
        """Wiring only — delivery is proved over a real socket below.

        Asserted by *absence of 404*: a route that was written but never added to the
        app's handler list would answer 404 here while every unit test still passed.
        """
        paths = {
            route.path
            for route in client.app.routes  # type: ignore[attr-defined]
        }
        assert "/observe/events" in paths
        assert "/observe/recent" in paths
        assert "/observe/outbox/{name:str}" in paths


def test_the_event_shape_carries_no_body() -> None:
    """A body on this wire would make the stream a second way to read mail.

    Pinned on `Arrival.as_event` itself, which is what both stream routes serialise, so
    the guarantee is checked once rather than once per route.
    """
    from agent_inbox.notify import Arrival

    event = Arrival(
        id="x", sender=ROSEMARY, subject="the subject", published="2026-08-04T00:00:00Z"
    ).as_event()

    assert set(event) == {"id", "from", "subject", "published"}
    assert "body" not in json.dumps(event)


class ServedHub:
    """One hub on a real socket, in a thread.

    Copied in shape from `tests/test_events_stream.py`, which needed it for the same
    reason and says so: a test transport delivers a response once, complete, and an
    endless stream never is. Everything above this line is testable without a socket
    and is; this is the one that would catch a route that is wired but does not deliver.
    """

    def __init__(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = int(probe.getsockname()[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
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
        else:  # pragma: no cover - only on a machine that cannot bind a socket
            raise RuntimeError("the hub did not come up")
        for name in (ROSEMARY, TREVOR):
            self.post("/actors", {"preferredUsername": name})
        return self

    def __exit__(self, *_: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def post(self, path: str, body: dict, headers: dict[str, str] | None = None) -> int:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=PATIENCE) as response:
            return int(response.status)

    def hold(self, path: str):  # noqa: ANN201 - an open http.client response
        return urllib.request.urlopen(
            urllib.request.Request(f"{self.base}{path}"), timeout=PATIENCE
        )


def _first_event(stream) -> dict[str, object]:  # noqa: ANN001 - an open response
    """Read frames until one is an event rather than a keep-alive comment."""
    while True:
        raw = stream.readline()
        if not raw:
            raise AssertionError("the stream ended without delivering an event")
        line = raw.decode().strip()
        if line.startswith("data:"):
            return dict(json.loads(line.removeprefix("data:").strip()))


def test_a_watcher_really_receives_an_arrival_over_http() -> None:
    """The test the rest of this file cannot do: does the wired route deliver?

    Everything else here proves a piece — the fan-out, the event shape, the
    registration. This proves they are connected to each other through a socket, which
    is the only place a mis-framed event or an unregistered handler shows up.
    """
    with ServedHub() as hub:
        stream = hub.hold("/observe/events")
        try:
            hub.post(
                f"/actors/{ROSEMARY}/outbox",
                {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "type": "Create",
                    "object": {
                        "type": "Note",
                        "to": [TREVOR],
                        "content": "body",
                        "summary": "seen by the watcher",
                    },
                },
                headers={IDENTITY_HEADER: ROSEMARY},
            )
            event = _first_event(stream)
        finally:
            stream.close()

    assert event["subject"] == "seen by the watcher"
    assert event["from"] == ROSEMARY
    # The watcher was never addressed and still heard it — which is the whole feature.
    assert TREVOR not in json.dumps(event)
