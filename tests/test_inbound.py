"""Step 5: one message, one peer, inbound.

The rejection tests assert on **the recipient's mailbox**, not the status code.
"Refused before delivery" is untestable otherwise: a 4xx with the message delivered
anyway is exactly the failure that ordering exists to prevent.
"""

import asyncio
import json
from typing import Any

import pytest
from litestar.testing import TestClient

from agent_inbox.api import Api, build_api
from agent_inbox.house import House
from agent_inbox.inbound import MAX_ACTIVITY_BYTES
from agent_inbox.mailbox import Mailbox
from agent_inbox.peers import peer_origin
from agent_inbox.signatures import sign_request
from agent_inbox.store import InMemoryStore

BETA = "https://beta.invalid"
ALPHA = "https://alpha.invalid"
KEY_ID = f"{ALPHA}/actors/sender#main-key"


def activity(**over: Any) -> dict[str, Any]:
    base = {
        "type": "Create",
        "id": f"{ALPHA}/act/1",
        "object": {
            "type": "Note",
            "to": ["alice"],
            "content": "hello from alpha",
            "summary": "greetings",
        },
    }
    base.update(over)
    return base


@pytest.fixture
def beta():
    """A hub that federates, knows alpha, and has alice on it."""
    house = House(Mailbox(InMemoryStore(), hub_name="beta"))
    asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
    asyncio.run(house.join("alice"))
    asyncio.run(house.mailbox.add_peer(peer_origin(ALPHA), "2026-07-29"))
    with TestClient(app=build_api(house, BETA)) as client:
        yield house, client


def inbox(house: House) -> tuple:
    return asyncio.run(house.observe_mailbox("alice"))


def post(client: TestClient, body: bytes, headers: dict[str, str] | None = None):
    return client.post("/actors/alice/inbox", content=body, headers=headers or {})


class TestARefusedMessageNeverArrives:
    """Every one of these asserts the mailbox, not the response."""

    def test_unsigned(self, beta) -> None:
        house, client = beta
        post(client, json.dumps(activity()).encode())
        assert inbox(house) == (), "an unsigned delivery reached a mailbox"

    def test_an_unknown_activity_type(self, beta) -> None:
        house, client = beta
        post(client, json.dumps(activity(type="Follow")).encode())
        assert inbox(house) == ()

    def test_a_delete_naming_something_we_hold(self, beta) -> None:
        """A peer cannot reach into our store, in either direction — the owner's rule.

        The object must still be there afterwards, which is the assertion that
        distinguishes "refused" from "accepted and ignored".
        """
        house, client = beta
        asyncio.run(house.send("alice", "alice", "ours", subject="local"))
        before = inbox(house)
        assert before, "the premise: there is something to try to delete"

        post(client, json.dumps(activity(type="Delete")).encode())
        assert inbox(house) == before, "a remote Delete changed our store"

    def test_a_body_larger_than_the_bound(self, beta) -> None:
        house, client = beta
        post(client, b"x" * (MAX_ACTIVITY_BYTES + 10))
        assert inbox(house) == ()

    def test_garbage(self, beta) -> None:
        house, client = beta
        post(client, b"not an activity at all")
        assert inbox(house) == ()

    def test_a_hub_that_does_not_federate_accepts_nothing(self) -> None:
        house = House(Mailbox(InMemoryStore(), hub_name="beta"))
        asyncio.run(house.join("alice"))
        asyncio.run(house.mailbox.add_peer(peer_origin(ALPHA), "2026-07-29"))
        with TestClient(app=build_api(house, BETA)) as client:
            post(client, json.dumps(activity()).encode())
        assert inbox(house) == ()

    def test_a_hub_with_no_peers_accepts_nothing(self) -> None:
        house = House(Mailbox(InMemoryStore(), hub_name="beta"))
        asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
        asyncio.run(house.join("alice"))
        key = asyncio.run(Api(house, BETA).signing_key())
        body = json.dumps(activity()).encode()
        headers = sign_request(
            key, KEY_ID, "POST", f"{BETA}/actors/alice/inbox", body=body
        )
        with TestClient(app=build_api(house, BETA)) as client:
            post(client, body, headers)
        assert inbox(house) == ()


class TestRefusalsAreIndistinguishable:
    """Which of several reasons applied must not be visible to a stranger."""

    def test_a_real_and_an_invented_recipient_answer_alike(self, beta) -> None:
        _, client = beta
        body = json.dumps(activity()).encode()
        real = post(client, body)
        invented = client.post("/actors/nobody_here/inbox", content=body)
        assert real.status_code == invented.status_code
        assert real.json()["detail"] == invented.json()["detail"]


class TestLocalStaysLocal:
    def test_at_local_cannot_be_addressed_from_outside(self, beta) -> None:
        """`@local` is a promise of non-egress. A remote sender must not reach it.

        Asserted here rather than trusted to the addressing layer, because the
        guarantee is what a remote sender would most like to break.
        """
        house, client = beta
        post(
            client,
            json.dumps(
                activity(
                    object={
                        "type": "Note",
                        "to": ["alice@local"],
                        "content": "sneaking in",
                    }
                )
            ).encode(),
        )
        assert inbox(house) == ()


class TestAMessageActuallyArrives:
    """The premise for every refusal above.

    Each of those asserts an **empty** mailbox — so if delivery were simply broken they
    would all pass and prove nothing. This is the test that makes them mean something.

    It needs alpha's key to be genuinely fetchable, so a real local server publishes
    alpha's actor document. Pointing at an unreachable host would make delivery fail for
    the wrong reason, which is how three earlier security tests in this work came to be
    vacuous.
    """

    @staticmethod
    def _alpha_serving_its_key(public_pem: str):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        holder: dict[str, str] = {}

        class Actor(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                raw = json.dumps(
                    {
                        "publicKey": {
                            "owner": holder["actor"],
                            "publicKeyPem": public_pem,
                        }
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Actor)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f"http://127.0.0.1:{server.server_port}"
        holder["actor"] = f"{origin}/actors/sender"
        return server, origin, holder["actor"]

    def test_a_signed_message_from_a_known_peer_arrives(self) -> None:
        house = House(Mailbox(InMemoryStore(), hub_name="beta"))
        asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
        asyncio.run(house.join("alice"))

        key = asyncio.run(Api(house, BETA).signing_key())
        server, origin, actor = self._alpha_serving_its_key(key.public_pem)
        asyncio.run(house.mailbox.add_peer(peer_origin(origin), "2026-07-29"))

        body = json.dumps(activity(id=f"{origin}/act/7")).encode()
        headers = sign_request(
            key, f"{actor}#main-key", "POST", f"{BETA}/actors/alice/inbox", body=body
        )
        try:
            with TestClient(app=build_api(house, BETA)) as client:
                first = post(client, body, headers)
                second = post(client, body, headers)
        finally:
            server.shutdown()

        assert first.json() == {"delivered": True}, first.text
        landed = inbox(house)
        assert len(landed) == 1, "a signed message from a known peer must arrive"
        assert landed[0].content == "hello from alpha"
        assert landed[0].attributed_to == actor, (
            "the sender is the peer's actor URI, with no local identifier minted"
        )

        # FR-5: the same activity again is a no-op, not a second message.
        assert second.json() == {"delivered": False, "reason": "already seen"}
        assert len(inbox(house)) == 1

    def test_the_same_body_with_a_swapped_activity_is_refused(self) -> None:
        """FR-2 at the route: the signature covers a digest, so the body cannot change.

        This is the trap carried from Step 4 — a signature that did not cover the body
        would authorise any body, and look like proof while doing it.
        """
        house = House(Mailbox(InMemoryStore(), hub_name="beta"))
        asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
        asyncio.run(house.join("alice"))

        key = asyncio.run(Api(house, BETA).signing_key())
        server, origin, actor = self._alpha_serving_its_key(key.public_pem)
        asyncio.run(house.mailbox.add_peer(peer_origin(origin), "2026-07-29"))

        signed_body = json.dumps(activity(id=f"{origin}/act/8")).encode()
        headers = sign_request(
            key,
            f"{actor}#main-key",
            "POST",
            f"{BETA}/actors/alice/inbox",
            body=signed_body,
        )
        swapped = json.dumps(
            activity(
                id=f"{origin}/act/8",
                object={
                    "type": "Note",
                    "to": ["alice"],
                    "content": "not what was signed",
                },
            )
        ).encode()
        try:
            with TestClient(app=build_api(house, BETA)) as client:
                post(client, swapped, headers)
        finally:
            server.shutdown()

        assert inbox(house) == (), "a body the signature did not cover was delivered"

    def test_a_fetchable_stranger_is_still_refused(self) -> None:
        """The trust check, discriminated properly.

        `test_a_hub_with_no_peers_accepts_nothing` above signs with an unreachable
        keyId, so its fetch fails whatever the trust list says — it proves nothing about
        trust. Here the stranger's key **is** genuinely fetchable and its signature is
        valid; the only thing wrong is that beta was never told to trust that origin.

        Verified by removal: delete the peer check and this is the test that fails.
        """
        house = House(Mailbox(InMemoryStore(), hub_name="beta"))
        asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
        asyncio.run(house.join("alice"))

        key = asyncio.run(Api(house, BETA).signing_key())
        server, origin, actor = self._alpha_serving_its_key(key.public_pem)
        # Deliberately NOT added as a peer.
        assert asyncio.run(house.mailbox.peers()) == {}

        body = json.dumps(activity(id=f"{origin}/act/99")).encode()
        headers = sign_request(
            key, f"{actor}#main-key", "POST", f"{BETA}/actors/alice/inbox", body=body
        )
        try:
            with TestClient(app=build_api(house, BETA)) as client:
                post(client, body, headers)
        finally:
            server.shutdown()

        assert inbox(house) == (), "a valid signature from a stranger delivered mail"
