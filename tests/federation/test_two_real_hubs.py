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
from agent_inbox.outbound import AlreadyDelivered
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


class TestARetriedActivityArrivesOnce:
    """Step 7's open question — T015 of `retry-delivery-to-a-sleeping-peer-01KYWFWB`.

    An attempt can fail *after* the peer received it: a timeout on a POST that in fact
    succeeded is, from the sending side, indistinguishable from one that never arrived.
    So the retry queue will sometimes send a message the recipient already holds, and
    whether that costs them a duplicate is a property of the **receiving** half — which
    is why it is asked here, of two real hubs, rather than of the retry loop's fakes.

    **The sequential case, and since issue #41 the concurrent one too.** These began by
    proving only that one attempt finishing before the next begins costs no duplicate —
    which is what the queue usually does — and recorded that atomicity was absent. It is
    now present: the receiver claims the activity id in a single write before it
    delivers, so of two attempts in flight together exactly one proceeds.
    """

    @staticmethod
    def _copies(beta, marker: str) -> int:
        landed = asyncio.run(beta.house.observe_mailbox("alice"))
        return sum(1 for m in landed if m.content == marker)

    def test_the_same_activity_sent_twice_lands_once(self, hubs) -> None:
        """The premise holds: `id` derives from the record, so a retry repeats it."""
        from agent_inbox.outbound import deliver, resolve

        alpha, beta = hubs
        asyncio.run(alpha.house.join("retrier"))
        key, key_id = TestSendingToAPeer._keys(alpha)
        who = resolve(f"alice@beta.localhost:{beta.port}")
        marker = "delivered twice, on purpose"
        activity = {
            "type": "Create",
            "id": f"{alpha.base}/act/t015-stable",
            "object": {
                "type": "Note",
                "to": ["alice"],
                "content": marker,
                "summary": "the retry that was not needed",
            },
        }

        def attempt() -> None:
            deliver(
                who,
                activity,
                key=key,
                key_id=key_id,
                settings=asyncio.run(alpha.house.mailbox.hub_settings()),
                peers=asyncio.run(alpha.house.mailbox.peers()),
            )

        attempt()
        # **The second attempt now says so rather than passing quietly.** It used to
        # return like any success, which is how a genuine collision came to be recorded
        # as `delivered` (issue #40). The peer answers
        # `{"delivered": false, "reason": "already seen"}`; we no longer discard it.
        with pytest.raises(AlreadyDelivered):
            attempt()

        assert self._copies(beta, marker) == 1, (
            "a retried activity must not cost the recipient a second copy"
        )

    def test_two_simultaneous_deliveries_land_once(self, hubs) -> None:
        """Window (a) of issue #41, against two real hubs.

        The premise of the retry feature is that an attempt can fail *after* the peer
        received it — a client-side timeout does not cancel the peer's in-flight
        request. So the queue's retry can arrive while the first attempt is still inside
        `house.send`, and the old check-then-act let both through: both passed
        `seen_activity` before either recorded an answer, and `Mailbox.send` mints a
        fresh uuid per call, so nothing downstream could catch the second.

        Run rather than reasoned about, with the two attempts genuinely overlapping.
        """
        import threading

        from agent_inbox.outbound import deliver, resolve

        alpha, beta = hubs
        asyncio.run(alpha.house.join("racer"))
        key, key_id = TestSendingToAPeer._keys(alpha)
        who = resolve(f"alice@beta.localhost:{beta.port}")
        marker = "delivered twice, simultaneously"
        activity = {
            "type": "Create",
            "id": f"{alpha.base}/act/41-concurrent",
            "object": {
                "type": "Note",
                "to": ["alice"],
                "content": marker,
                "summary": "the retry that raced its own first attempt",
            },
        }
        settings = asyncio.run(alpha.house.mailbox.hub_settings())
        peers = asyncio.run(alpha.house.mailbox.peers())
        start = threading.Barrier(2)
        outcomes: list[str] = []

        def attempt() -> None:
            start.wait(timeout=10)
            try:
                deliver(
                    who,
                    activity,
                    key=key,
                    key_id=key_id,
                    settings=settings,
                    peers=peers,
                )
                outcomes.append("delivered")
            except AlreadyDelivered:
                outcomes.append("refused")

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert self._copies(beta, marker) == 1, (
            f"two simultaneous attempts delivered {self._copies(beta, marker)} copies"
        )
        assert sorted(outcomes) == ["delivered", "refused"], outcomes

    def test_a_changed_id_is_a_different_message(self, hubs) -> None:
        """The paired positive, and the proof the assertion above can fail.

        De-duplication that swallowed everything would pass the test above for the
        wrong reason. Two genuinely distinct activities must both arrive.
        """
        from agent_inbox.outbound import deliver, resolve

        alpha, beta = hubs
        key, key_id = TestSendingToAPeer._keys(alpha)
        who = resolve(f"alice@beta.localhost:{beta.port}")
        marker = "two distinct activities"
        for n in (1, 2):
            deliver(
                who,
                {
                    "type": "Create",
                    "id": f"{alpha.base}/act/t015-distinct-{n}",
                    "object": {
                        "type": "Note",
                        "to": ["alice"],
                        "content": marker,
                        "summary": "not a retry",
                    },
                },
                key=key,
                key_id=key_id,
                settings=asyncio.run(alpha.house.mailbox.hub_settings()),
                peers=asyncio.run(alpha.house.mailbox.peers()),
            )

        assert self._copies(beta, marker) == 2, (
            "distinct activities must not be mistaken for a retry of one"
        )

    def test_two_recipients_on_one_peer_both_receive(self, hubs) -> None:
        """Fixed in 0.59.0 — this was `xfail(strict=True)` and the marker did its job.

        The activity id derived from the *record*, and one record can name several
        remote recipients. Two of them on the same hub arrived as the same activity id,
        the second was discarded as a retry of the first, and the sender was told
        `delivered` for both. Silent loss, which this codebase calls the worst failure
        shape it has.

        The strict marker meant this test failed the day it started passing, which is
        exactly what happened when the id gained a per-recipient suffix. That is worth
        recording: the alarm was set by whoever found the bug and could not fix it
        there, and it went off on its own.
        """
        alpha, beta = hubs
        asyncio.run(beta.house.join("bob"))
        asyncio.run(alpha.house.join("fanout"))
        marker = "one message, two recipients on one hub"

        sent = asyncio.run(
            alpha.house.send(
                "fanout",
                [
                    f"alice@beta.localhost:{beta.port}",
                    f"bob@beta.localhost:{beta.port}",
                ],
                marker,
                subject="fan-out to one peer",
            )
        )

        assert [r.state for r in sent.receipts] == ["delivered", "delivered"]
        landed = asyncio.run(beta.house.observe_mailbox("bob"))
        assert marker in [m.content for m in landed], (
            "the second recipient on a peer was told delivered but got nothing"
        )
