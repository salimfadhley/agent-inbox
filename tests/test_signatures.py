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
