"""HTTP signatures: proving which hub made a request.

Most of these are refusals. A verifier that accepts for any reason other than a checked
signature over a fresh date is the whole hole, so the tests are mostly attempts to find
a second way to succeed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_inbox.keys import KEY_BITS, SigningKey, generate, verify
from agent_inbox.signatures import (
    MAX_CLOCK_SKEW,
    parse_signature,
    sign_request,
    verify_request,
)

URL = "http://beta.invalid/actors/alice"
KEY_ID = "http://alpha.invalid/actors/alice#main-key"


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return generate()


def _verify(claim, key: SigningKey, headers, path="/actors/alice", **kw) -> bool:
    return verify_request(claim, key.public_pem, "GET", path, headers, **kw)


class TestTheKeyItself:
    def test_it_never_renders_its_private_half(self, key: SigningKey) -> None:
        """However it is logged, printed, or included in an assertion message."""
        assert "PRIVATE" not in repr(key)
        assert "PRIVATE" not in str(key)
        assert "PRIVATE" not in f"{key}"

    def test_the_public_half_is_a_pem(self, key: SigningKey) -> None:
        assert key.public_pem.startswith("-----BEGIN PUBLIC KEY-----")

    def test_it_is_the_size_the_fediverse_expects(self) -> None:
        """Smaller is not interoperable; a key nothing verifies is decoration."""
        assert KEY_BITS == 2048

    def test_verification_has_exactly_one_way_to_succeed(self, key: SigningKey) -> None:
        signature = key.sign(b"hello")
        assert verify(key.public_pem, b"hello", signature)
        assert not verify(key.public_pem, b"hell0", signature)
        assert not verify(generate().public_pem, b"hello", signature)
        assert not verify("not a key at all", b"hello", signature)
        assert not verify(key.public_pem, b"hello", b"not a signature")


class TestSigningAndVerifying:
    def test_a_signed_request_verifies(self, key: SigningKey) -> None:
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        assert claim is not None
        assert _verify(claim, key, {"host": headers["host"], "date": headers["date"]})

    def test_the_path_is_covered(self, key: SigningKey) -> None:
        """Otherwise a signature for one URL authorises any other on that host."""
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        assert not _verify(
            claim,
            key,
            {"host": headers["host"], "date": headers["date"]},
            path="/actors/somebody_else",
        )

    def test_the_host_is_covered(self, key: SigningKey) -> None:
        """Otherwise a request captured for one hub replays against another."""
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        assert not _verify(
            claim, key, {"host": "somewhere.else", "date": headers["date"]}
        )

    def test_another_hubs_key_does_not_verify(self, key: SigningKey) -> None:
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        assert not verify_request(
            claim,
            generate().public_pem,
            "GET",
            "/actors/alice",
            {"host": headers["host"], "date": headers["date"]},
        )


class TestReplay:
    """A signature that never goes stale is a password that never expires."""

    def test_a_stale_request_is_refused(self, key: SigningKey) -> None:
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        later = datetime.now(UTC) + MAX_CLOCK_SKEW + timedelta(minutes=1)
        assert not _verify(
            claim, key, {"host": headers["host"], "date": headers["date"]}, now=later
        )

    def test_a_request_from_the_future_is_refused(self, key: SigningKey) -> None:
        """Skew cuts both ways; a peer whose clock is far ahead is as suspect."""
        ahead = datetime.now(UTC) + MAX_CLOCK_SKEW + timedelta(minutes=1)
        headers = sign_request(key, KEY_ID, "GET", URL, now=ahead)
        claim = parse_signature(headers["Signature"])
        assert not _verify(
            claim, key, {"host": headers["host"], "date": headers["date"]}
        )

    def test_a_request_inside_the_window_is_accepted(self, key: SigningKey) -> None:
        recent = datetime.now(UTC) - (MAX_CLOCK_SKEW / 2)
        headers = sign_request(key, KEY_ID, "GET", URL, now=recent)
        claim = parse_signature(headers["Signature"])
        assert _verify(claim, key, {"host": headers["host"], "date": headers["date"]})

    def test_a_signature_not_covering_date_is_refused(self, key: SigningKey) -> None:
        """Without a covered date a captured request replays forever."""
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        undated = type(claim)(
            key_id=claim.key_id,
            algorithm=claim.algorithm,
            headers=("(request-target)", "host"),
            signature=claim.signature,
        )
        assert not _verify(
            undated, key, {"host": headers["host"], "date": headers["date"]}
        )


class TestWhatCountsAsUnsigned:
    """None means *not verified*, never an error to route around."""

    @pytest.mark.parametrize(
        "header",
        ["", "   ", "Bearer something", 'keyId="x"', 'signature="!!!not base64!!!"'],
    )
    def test_nonsense_parses_as_unsigned(self, header: str) -> None:
        assert parse_signature(header) is None

    def test_an_unexpected_algorithm_is_refused(self, key: SigningKey) -> None:
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        swapped = type(claim)(
            key_id=claim.key_id,
            algorithm="hmac-sha256",
            headers=claim.headers,
            signature=claim.signature,
        )
        assert not _verify(
            swapped, key, {"host": headers["host"], "date": headers["date"]}
        )

    def test_an_unparseable_date_is_refused(self, key: SigningKey) -> None:
        headers = sign_request(key, KEY_ID, "GET", URL)
        claim = parse_signature(headers["Signature"])
        assert not _verify(claim, key, {"host": headers["host"], "date": "yesterday"})


class TestAValidSignatureIsNotEnough:
    """Possession of a key is not identity as a peer.

    Found by outside review, 2026-07-29. A valid signature proves only that the sender
    holds the key at the `keyId` they chose — and anyone can publish an actor document
    with their own key and sign correctly. Without a trust list, that made every
    stranger a "verified peer" and handed them the rich actor document.
    """

    @staticmethod
    def _hub(federating: bool = True):
        import asyncio

        from agent_inbox.api import build_api
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox
        from agent_inbox.store import InMemoryStore

        house = House(Mailbox(InMemoryStore(), hub_name="victim"))
        if federating:
            asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
        asyncio.run(house.join("alice"))
        return house, build_api(house, "http://victim.invalid")

    def test_a_stranger_signing_as_itself_still_gets_barebones(
        self, key: SigningKey
    ) -> None:
        """The exact attack: sign correctly, with a keyId you control.

        The attacker's actor document is served by a **real local server**, so its key
        is genuinely fetchable. An earlier version of this test pointed at
        `evil.example`, which does not resolve — so the attack failed because the host
        was unreachable rather than because the trust check refused it, and the test
        passed with the check removed. That is the third vacuous security test in this
        work; the fix each time is to make the attack actually possible.
        """
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from litestar.testing import TestClient

        published = {"publicKeyPem": key.public_pem, "owner": ""}

        class EvilActor(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                raw = json.dumps({"publicKey": published}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_: object) -> None:
                return

        evil = HTTPServer(("127.0.0.1", 0), EvilActor)
        threading.Thread(target=evil.serve_forever, daemon=True).start()
        evil_actor = f"http://127.0.0.1:{evil.server_port}/actor"
        published["owner"] = evil_actor

        house, app = self._hub()
        headers = sign_request(
            key, f"{evil_actor}#main-key", "GET", "http://victim.invalid/actors/alice"
        )
        try:
            with TestClient(app=app) as c:
                body = c.get("/actors/alice", headers=headers).json()
        finally:
            evil.shutdown()

        assert "profile" not in body, (
            "a stranger with a valid, fetchable key is still a stranger"
        )
        assert "lastSeen" not in body

    def test_a_hub_with_no_peers_verifies_nobody(self, key: SigningKey) -> None:
        """Which is every hub until an operator adds one, and is the right default."""
        import asyncio

        from agent_inbox.api import Api

        house, _ = self._hub()
        assert asyncio.run(house.mailbox.peers()) == {}

        api = Api(house, "http://victim.invalid")
        assert asyncio.run(api.house.mailbox.peers()) == {}

    def test_trusting_a_peer_is_what_makes_a_signature_count(self) -> None:
        """The other half: once trusted, an origin's signature is honoured.

        Asserted at the trust check rather than end to end, because verification then
        fetches the peer's key over the network — the two-hub demo covers that.
        """
        import asyncio

        from agent_inbox.peers import peer_origin

        house, _ = self._hub()
        origin = peer_origin("https://friend.example/actor#main-key")
        asyncio.run(house.mailbox.add_peer(origin, "2026-07-29"))
        assert origin in asyncio.run(house.mailbox.peers())
        assert peer_origin("https://evil.example/actor#main-key") not in asyncio.run(
            house.mailbox.peers()
        )
