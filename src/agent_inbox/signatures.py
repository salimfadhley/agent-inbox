"""HTTP signatures: proving which hub made a request.

The fediverse's `AUTHORIZED_FETCH` in miniature. A hub signs the requests it makes,
and a hub receiving one can check who made it — which is what lets a peer be told apart
from a stranger, and therefore what makes the rich actor document reachable at all.

**Draft-cavage HTTP Signatures, not RFC 9421.** The newer standard is better designed
and almost nothing in the fediverse speaks it; the installed base verifies the draft.
The standing rule is to do the most normal thing for the fediverse unless it conflicts
with the goals of a developer tool, and interoperating with nobody is not a goal.

The signature covers `(request-target)`, `host` and `date`. It deliberately does
**not** cover a body, because every signed request here is a GET — when something is
POSTed between hubs a `digest` header must join the covered set, and a signature that
did not cover the body would be worse than none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlsplit

from agent_inbox.keys import SigningKey, verify

#: How far apart two clocks may be before a signature is refused. Too tight and honest
#: peers fail; too loose and a captured request stays replayable. Mastodon's window is
#: on this order.
MAX_CLOCK_SKEW = timedelta(minutes=5)

#: The covered set, in order. Order is part of the signature: a verifier rebuilds the
#: string from the header's own `headers=` list, so a sender that reorders is still
#: verifiable, but what *we* send is fixed.
SIGNED_HEADERS = ("(request-target)", "host", "date")

_PAIR = re.compile(r'(\w+)="([^"]*)"')


@dataclass(frozen=True, slots=True)
class SignatureClaim:
    """What an incoming `Signature` header claims, before anything is checked."""

    key_id: str
    algorithm: str
    headers: tuple[str, ...]
    signature: bytes


def _signing_string(
    method: str, path: str, headers: dict[str, str], covered: tuple[str, ...]
) -> bytes:
    lines = []
    for name in covered:
        if name == "(request-target)":
            lines.append(f"(request-target): {method.lower()} {path}")
        else:
            lines.append(f"{name}: {headers.get(name, '')}")
    return "\n".join(lines).encode()


def sign_request(
    key: SigningKey, key_id: str, method: str, url: str, *, now: datetime | None = None
) -> dict[str, str]:
    """Headers proving this hub made this request.

    `key_id` is the actor-document fragment a verifier fetches to find our public key —
    the same `#main-key` the actor document publishes.
    """
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    when = format_datetime(now or datetime.now(UTC), usegmt=True)
    headers = {"host": parts.netloc, "date": when}
    material = _signing_string(method, path, headers, SIGNED_HEADERS)
    from base64 import b64encode

    signature = b64encode(key.sign(material)).decode()
    covered = " ".join(SIGNED_HEADERS)
    return {
        **headers,
        "Signature": (
            f'keyId="{key_id}",algorithm="rsa-sha256",'
            f'headers="{covered}",signature="{signature}"'
        ),
    }


def parse_signature(header: str) -> SignatureClaim | None:
    """Read a `Signature` header, or None if it is not one.

    None means "unsigned", and every caller must treat that as *not verified* rather
    than as an error to work around.
    """
    from base64 import b64decode

    fields = dict(_PAIR.findall(header or ""))
    key_id, raw, covered = (
        fields.get("keyId"),
        fields.get("signature"),
        fields.get("headers"),
    )
    if not key_id or not raw:
        return None
    try:
        signature = b64decode(raw, validate=True)
    except Exception:
        return None
    return SignatureClaim(
        key_id=key_id,
        algorithm=fields.get("algorithm", ""),
        headers=tuple((covered or "date").split()),
        signature=signature,
    )


def verify_request(
    claim: SignatureClaim,
    public_pem: str,
    method: str,
    path: str,
    headers: dict[str, str],
    *,
    now: datetime | None = None,
) -> bool:
    """Whether this request really came from the holder of `public_pem`.

    Every failure returns False. There is exactly one path to True, and it requires a
    signature that checks out over a `date` within the skew window — a verifier that can
    accept for any other reason is the hole this module exists to close.
    """
    if claim.algorithm and claim.algorithm.lower() != "rsa-sha256":
        return False
    if "date" not in claim.headers:
        # Without a covered date a captured request is replayable forever.
        return False
    sent = headers.get("date", "")
    try:
        when = parsedate_to_datetime(sent)
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if abs((now or datetime.now(UTC)) - when) > MAX_CLOCK_SKEW:
        return False
    material = _signing_string(method, path, headers, claim.headers)
    return verify(public_pem, material, claim.signature)
