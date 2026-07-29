"""Two hubs, two real servers, two real hostnames — and no Docker.

The in-process harness (`harness.py`) proves the logic; the container harness proves the
shipped image. This sits between them and is the one that runs in the ordinary suite.

**Why it is not just the localhost demo again.** `*.localhost` resolves to 127.0.0.1
by RFC 6761, on every resolver, with no configuration — so `alpha.localhost` and
`beta.localhost` are *distinct hostnames* needing no `/etc/hosts` edit, no root and no
container network. That matters because `localhost` is the one hostname that cannot
catch a mistake in host matching: WebFinger's `acct:name@host`, the peer trust list
keyed by origin, and `_origin()`'s scheme/host/port comparison are all string work that
a single degenerate hostname barely exercises.

It also exercises the insecure-transport opt-in, because `alpha.localhost` is not in
`LOOPBACK_HOSTS` — plain HTTP to it is refused unless a deployment has opted in, which
is exactly the case that switch exists for.

The charter allows this: real sockets, but no external services and no gating.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn

from agent_inbox.api import build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.peers import identify, peer_origin
from agent_inbox.store import InMemoryStore


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Hub:
    """One hub, served for real, addressed by a name that is not `localhost`."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.port = _free_port()
        self.base = f"http://{name}.localhost:{self.port}"
        self.house = House(Mailbox(InMemoryStore(), hub_name=name))
        self._server = uvicorn.Server(
            uvicorn.Config(
                build_api(self.house, self.base),
                host="127.0.0.1",
                port=self.port,
                log_level="error",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{self.base}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"{self.name} did not come up")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def run(self, coro):
        return asyncio.run(coro)

    def get(self, path: str) -> tuple[int, object]:
        try:
            with urllib.request.urlopen(f"{self.base}{path}", timeout=5) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None


@pytest.fixture(scope="module")
def hubs(request):
    """Two hubs, both federating, both opted into insecure transport."""
    import os

    os.environ["AGENT_INBOX_FEDERATION_INSECURE"] = "true"
    alpha, beta = Hub("alpha"), Hub("beta")
    for hub in (alpha, beta):
        hub.start()
        asyncio.run(hub.house.mailbox.set_hub_setting("federation", "enabled"))
    asyncio.run(beta.house.join("alice"))
    yield alpha, beta
    for hub in (alpha, beta):
        hub.stop()
    os.environ.pop("AGENT_INBOX_FEDERATION_INSECURE", None)


def test_the_hostnames_are_genuinely_distinct(hubs) -> None:
    """The premise. If both resolved to the same name this would prove nothing."""
    alpha, beta = hubs
    assert "alpha.localhost" in alpha.base
    assert "beta.localhost" in beta.base
    assert alpha.base != beta.base
    assert socket.gethostbyname("alpha.localhost") == "127.0.0.1"


def test_each_hub_reports_its_own_name(hubs) -> None:
    alpha, beta = hubs
    assert alpha.get("/")[1]["name"] == "alpha"
    assert beta.get("/")[1]["name"] == "beta"


def test_one_hub_identifies_the_other_over_a_real_socket(hubs) -> None:
    """`identify` doing real DNS, a real connection, and a real NodeInfo round trip."""
    alpha, beta = hubs
    who = identify(beta.base)
    assert who.software == "agent-inbox"
    assert who.federates is True
    assert who.base == beta.base


def test_webfinger_matches_a_hostname_that_is_not_localhost(hubs) -> None:
    """The check every other test exercises against the degenerate case.

    `alpha.localhost` and `beta.localhost` differ, so a hub that matched hosts loosely —
    or not at all — would resolve an account it has no business resolving.
    """
    alpha, beta = hubs
    status, body = beta.get(
        f"/.well-known/webfinger?resource=acct:alice@beta.localhost:{beta.port}"
    )
    assert status == 200, body
    assert body["subject"].startswith("acct:alice@beta.localhost")

    # The same account, asked of the wrong hub, and asked of beta under alpha's name.
    assert (
        alpha.get(
            f"/.well-known/webfinger?resource=acct:alice@alpha.localhost:{alpha.port}"
        )[0]
        == 404
    )
    assert (
        beta.get(
            f"/.well-known/webfinger?resource=acct:alice@alpha.localhost:{alpha.port}"
        )[0]
        == 404
    )


def test_a_peer_origin_distinguishes_the_two_hubs(hubs) -> None:
    """The trust list is keyed by origin, so two hubs must not share one."""
    alpha, beta = hubs
    assert peer_origin(alpha.base) != peer_origin(beta.base)


def test_insecure_transport_is_what_makes_this_reachable(hubs) -> None:
    """`alpha.localhost` is not in LOOPBACK_HOSTS, so plain HTTP to it needs the opt-in.

    Removing it must make these hubs unreachable — otherwise the switch is decoration
    and this suite is quietly proving the wrong thing.
    """
    import os

    from agent_inbox.peers import PeerUnreachable

    _, beta = hubs
    os.environ.pop("AGENT_INBOX_FEDERATION_INSECURE", None)
    try:
        with pytest.raises(PeerUnreachable) as refused:
            identify(beta.base)
        assert "scheme" in str(refused.value)
    finally:
        os.environ["AGENT_INBOX_FEDERATION_INSECURE"] = "true"
