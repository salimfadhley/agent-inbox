"""Two hubs in one process, wired to each other without a network.

Federation is two hubs talking, so every requirement about it is a statement about
what hub B ends up holding after hub A does something. None of that can be asserted
with one hub.

The charter forbids external services in the suite and requires it to run in normal CI,
so this is two Litestar apps with separate stores, and a transport that routes one
hub's outbound request to the other's ASGI handler. No sockets, no ports, no network.

**The transport routes by base URL, and refuses anything it does not recognise.** A
transport that delivered to whoever was listening would make every policy test pass for
the wrong reason — the failure mode this file exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from litestar.testing import TestClient

from agent_inbox.api import build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore


@dataclass
class Attempt:
    """One request a hub made of another, whether or not it arrived."""

    frm: str
    to: str
    method: str
    path: str
    status: int | None
    delivered: bool


@dataclass
class Hub:
    """One hub: its name, its address, its client, and its store."""

    name: str
    base: str
    client: TestClient
    house: House


@dataclass
class Fleet:
    """Two hubs and the wire between them."""

    hubs: dict[str, Hub] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)

    def __getitem__(self, name: str) -> Hub:
        return self.hubs[name]

    def fetch(self, frm: str, url: str, method: str = "GET") -> tuple[int, object]:
        """One hub asks another for something, by URL.

        Resolution is by base URL and nothing else. An unknown host fails the way an
        unreachable host would, so a test that points at nowhere proves it.
        """
        target = next((h for h in self.hubs.values() if url.startswith(h.base)), None)
        if target is None:
            self.attempts.append(Attempt(frm, url, method, url, None, False))
            raise ConnectionError(f"no hub answers at {url!r}")
        path = url[len(target.base) :] or "/"
        response = target.client.request(method, path)
        self.attempts.append(
            Attempt(frm, target.name, method, path, response.status_code, True)
        )
        body: object
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return response.status_code, body

    def attempted(self, to: str) -> list[Attempt]:
        """Every request aimed at a hub — including ones it refused.

        Tests assert on this rather than only on what arrived: an attempt that was made
        and rejected is still an attempt, and some rules are about not trying at all.
        """
        return [a for a in self.attempts if a.to == to]


def two_hubs(
    alpha: str = "alpha", beta: str = "beta"
) -> tuple[Fleet, list[TestClient]]:
    """Build two independent hubs. Names and stores are asserted distinct."""
    fleet = Fleet()
    clients: list[TestClient] = []
    for name in (alpha, beta):
        house = House(Mailbox(InMemoryStore(), hub_name=name))
        base = f"http://{name}.invalid"
        client = TestClient(app=build_api(house, base))
        clients.append(client)
        fleet.hubs[name] = Hub(name=name, base=base, client=client, house=house)

    first, second = fleet.hubs[alpha], fleet.hubs[beta]
    assert first.house is not second.house, "the hubs must not share a house"
    assert first.base != second.base, "the hubs must not share an address"
    return fleet, clients
