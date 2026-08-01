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
from agent_inbox.delivery import FederatedDelivery
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
        mailbox = Mailbox(InMemoryStore(), hub_name=name)
        # Injected exactly as `serve.py` does it, so this harness exercises the same
        # wiring production has rather than a hand-built approximation.
        self.house = House(
            mailbox,
            deliver=FederatedDelivery(mailbox=mailbox, public_url=self.base),
        )
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


class TestSendingToAPeer:
    """Step 6: this hub initiates, for the first time.

    Every step before this was inbound — another hub connected to us and a test could
    fake that. Here *we* resolve a hostname, open a socket and sign a POST, which is why
    these run against two real servers rather than the in-process harness.
    """

    @staticmethod
    def _keys(hub: Hub):
        from agent_inbox.api import Api

        key = asyncio.run(Api(hub.house, hub.base).signing_key())
        return key, f"{hub.base}/actors/sender#main-key"

    def test_a_remote_recipient_resolves_to_an_inbox(self, hubs) -> None:
        from agent_inbox.outbound import resolve

        alpha, beta = hubs
        who = resolve(f"alice@beta.localhost:{beta.port}")
        assert who.actor_uri.endswith("/actors/alice")
        assert who.inbox.endswith("/actors/alice/inbox")
        assert who.origin == peer_origin(beta.base)

    def test_a_message_reaches_an_actor_on_the_other_hub(self, hubs) -> None:
        """The whole point of the step, over a real socket."""
        from agent_inbox.outbound import deliver, resolve

        alpha, beta = hubs
        asyncio.run(alpha.house.join("sender"))
        # **Peering is mutual, and the two directions mean different things.** Beta
        # lists alpha so alpha's signature counts on the way in; alpha lists beta
        # because a hub should not send mail to one its operator never configured.
        asyncio.run(beta.house.mailbox.add_peer(peer_origin(alpha.base), "2026-07-29"))
        asyncio.run(alpha.house.mailbox.add_peer(peer_origin(beta.base), "2026-07-29"))

        key, key_id = self._keys(alpha)
        who = resolve(f"alice@beta.localhost:{beta.port}")
        deliver(
            who,
            {
                "type": "Create",
                "id": f"{alpha.base}/act/step6",
                "object": {
                    "type": "Note",
                    "to": ["alice"],
                    "content": "sent from alpha",
                    "summary": "step six",
                },
            },
            key=key,
            key_id=key_id,
            settings=asyncio.run(alpha.house.mailbox.hub_settings()),
            peers=asyncio.run(alpha.house.mailbox.peers()),
        )

        landed = asyncio.run(beta.house.observe_mailbox("alice"))
        assert [m.content for m in landed] == ["sent from alpha"]
        assert landed[0].attributed_to.startswith(alpha.base)

    def test_a_hub_that_does_not_federate_sends_nothing(self, hubs) -> None:
        """Checked inside `deliver`, from settings read at that moment — which is what
        stops a queue getting between the decision and the send (FR-050)."""
        from agent_inbox.outbound import DeliveryRefused, deliver, resolve

        alpha, beta = hubs
        who = resolve(f"alice@beta.localhost:{beta.port}")
        key, key_id = self._keys(alpha)

        with pytest.raises(DeliveryRefused) as refused:
            deliver(
                who,
                {
                    "type": "Create",
                    "id": "x",
                    "object": {"type": "Note", "to": ["alice"]},
                },
                key=key,
                key_id=key_id,
                settings={},  # federation absent — as if it had just been switched off
                peers=asyncio.run(alpha.house.mailbox.peers()),
            )
        assert "does not federate" in str(refused.value)

    def test_a_hub_we_do_not_trust_is_refused(self, hubs) -> None:
        from agent_inbox.outbound import DeliveryRefused, deliver, resolve

        alpha, beta = hubs
        who = resolve(f"alice@beta.localhost:{beta.port}")
        key, key_id = self._keys(alpha)

        with pytest.raises(DeliveryRefused) as refused:
            deliver(
                who,
                {
                    "type": "Create",
                    "id": "x",
                    "object": {"type": "Note", "to": ["alice"]},
                },
                key=key,
                key_id=key_id,
                settings={"federation": "enabled"},
                peers={},  # nobody trusted
            )
        assert "not a peer" in str(refused.value)

    def test_an_unknown_actor_is_reported_rather_than_delivered(self, hubs) -> None:
        from agent_inbox.outbound import DeliveryRefused, resolve

        _, beta = hubs
        with pytest.raises(DeliveryRefused) as refused:
            resolve(f"nobody_here@beta.localhost:{beta.port}")
        assert "nobody_here" in str(refused.value), "the refusal must name who"

    def test_an_agent_addresses_a_remote_actor_and_it_arrives(self, hubs) -> None:
        """**The whole of step 6, end to end.** Not `outbound.deliver` called by hand —
        an agent calling `send` with a remote address, through the house, exactly as an
        agent on a real hub would.

        Everything above this test proves a piece. This proves the piece is wired in.
        """
        from agent_inbox.peers import peer_origin

        alpha, beta = hubs
        # Peering is mutual and the two directions mean different things: beta lists
        # alpha so alpha's signature counts on the way in, alpha lists beta because a
        # hub should not send mail to one its operator never configured.
        asyncio.run(beta.house.mailbox.add_peer(peer_origin(alpha.base), "2026-07-30"))
        asyncio.run(alpha.house.mailbox.add_peer(peer_origin(beta.base), "2026-07-30"))
        asyncio.run(alpha.house.join("wired"))

        sent = asyncio.run(
            alpha.house.send(
                "wired",
                f"alice@beta.localhost:{beta.port}",
                "an agent sent this through send()",
                subject="step six, wired",
            )
        )

        assert [r.state for r in sent.receipts] == ["delivered"]
        assert sent.record.to == (f"{beta.base}/actors/alice",), (
            "a remote recipient is stored by its actor URI, not a local name"
        )

        landed = asyncio.run(beta.house.observe_mailbox("alice"))
        assert "an agent sent this through send()" in [m.content for m in landed]

    def test_a_send_to_a_hub_we_do_not_trust_reports_rather_than_arrives(
        self, hubs
    ) -> None:
        """The refusal reaches the *sender*, and the local copy survives it."""
        alpha, beta = hubs
        asyncio.run(alpha.house.mailbox.remove_peer(peer_origin(beta.base)))
        asyncio.run(alpha.house.join("hopeful"))

        sent = asyncio.run(
            alpha.house.send(
                "hopeful",
                f"alice@beta.localhost:{beta.port}",
                "should not arrive",
                subject="untrusted",
            )
        )

        assert [r.state for r in sent.receipts] == ["failed"]
        assert sent.reached_nobody, "nobody got it, so it must not read as success"
        assert sent.record.id, "and the sender still has their own copy"
        # Put it back: the fixture is module-scoped and later tests expect the peering.
        asyncio.run(alpha.house.mailbox.add_peer(peer_origin(beta.base), "2026-07-30"))
