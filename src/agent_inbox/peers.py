"""Asking another hub who it is.

Step 2 made a hub answerable. This makes it able to ask — the same NodeInfo and
WebFinger functions, consumed rather than served.

Nothing here trusts what it reads. A peer's descriptor is **untrusted input from a
machine we have not verified**: it is bounded before it is parsed, and every field is
treated as text that will be shown to an operator, never as markup or instruction. That
is charter directive 7's second bullet arriving over HTTP rather than in a message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from agent_inbox.exceptions import MailboxError

#: Bounds, so a hostile or broken peer cannot cost us unbounded work. Deliberately
#: small: a descriptor is a few hundred bytes and anything larger is not one.
FETCH_TIMEOUT_SECONDS = 10
MAX_DESCRIPTOR_BYTES = 64 * 1024

#: The only scheme we will fetch. HTTP federation is a later step, if ever, and a
#: scheme allowlist is the only kind worth having — a denylist is a guess about what
#: exists.
ALLOWED_SCHEMES = ("https",)

#: …except against a hub on this machine, which is how the demo and the tests work.
#: Narrow by design: an explicit opt-in for loopback only, not "http when you feel
#: like it".
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")

NODEINFO_REL_PREFIX = "http://nodeinfo.diaspora.software/ns/schema/2."


class PeerUnreachable(MailboxError):
    """A peer could not be read, for any reason.

    One answer for several causes — unreachable, refused, malformed, too large. The
    operator needs to know it did not work and why in prose; a caller does not need to
    branch on which.
    """

    code = "peer_unreachable"


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    """What another hub says it is. Every field is that hub's claim, not our finding."""

    base: str
    software: str
    version: str
    federates: bool
    title: str | None = None
    description: str | None = None
    users: int | None = None


def _origin(url: str) -> tuple[str, str, str]:
    """Parse a URL into (scheme, host, port-or-empty), refusing what we will not fetch.

    Returns the *parsed* pieces rather than a string, because comparing origins by
    string prefix is exploitable: ``https://good.example@127.0.0.1:8443/x`` starts with
    ``https://good.example`` and yet points at loopback, since everything before the
    ``@`` is userinfo. Found by outside review, 2026-07-29.
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        raise PeerUnreachable(f"{url!r} is not a URL — try https://hub.example")
    if parts.username or parts.password:
        # Nothing legitimate needs it, and its only use here is to make a URL read as
        # one host while resolving to another.
        raise PeerUnreachable(
            f"{url!r} carries credentials in the address, which this hub will not fetch"
        )
    host = (parts.hostname or "").lower()
    if not host:
        raise PeerUnreachable(f"{url!r} names no host")
    if parts.scheme not in ALLOWED_SCHEMES and not (
        parts.scheme == "http" and host in LOOPBACK_HOSTS
    ):
        raise PeerUnreachable(
            f"{parts.scheme!r} is not a scheme this hub will fetch — https only, "
            "except http to a hub on this machine"
        )
    port = f":{parts.port}" if parts.port else ""
    return parts.scheme, host, port


def _permitted(url: str) -> str:
    """Normalise a peer URL to its origin, or refuse it with the rule it broke.

    Drops path, query and fragment: a peer is an origin, and keeping the rest would let
    a typo point us at an arbitrary URL on that host.
    """
    scheme, host, port = _origin(url)
    return urlunsplit((scheme, f"{host}{port}", "", "", ""))


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse redirects rather than following them.

    ``urlopen`` follows them by default, and a peer that can redirect can send us
    anywhere: ``302 Location: http://169.254.169.254/`` reaches cloud metadata, and
    ``http://10.0.0.5:8080/`` reaches whatever is on the internal network. The scheme
    check ran against the URL the operator typed, not the one actually fetched.

    Refusing outright rather than re-validating: a hub's own well-known documents are
    at fixed paths on its own origin, so a redirect is a misconfiguration at best.
    Found by outside review, 2026-07-29.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(
            newurl,
            code,
            f"redirected to {newurl!r}, which this hub will not follow",
            headers,
            fp,
        )


def _fetch_json(url: str) -> dict[str, object]:
    """Read a small JSON document, bounded in both time and size."""
    request = urllib.request.Request(  # noqa: S310 — scheme is checked in _permitted
        url, headers={"Accept": "application/json", "User-Agent": "agent-inbox"}
    )
    opener = urllib.request.build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_DESCRIPTOR_BYTES + 1)
    except (urllib.error.URLError, OSError) as failure:
        raise PeerUnreachable(f"could not reach {url} — {failure}") from failure
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise PeerUnreachable(f"{url} returned more than {MAX_DESCRIPTOR_BYTES} bytes")
    try:
        document = json.loads(raw)
    except ValueError as bad:
        raise PeerUnreachable(f"{url} did not return JSON — {bad}") from bad
    if not isinstance(document, dict):
        raise PeerUnreachable(
            f"{url} returned {type(document).__name__}, not an object"
        )
    return document


def _text(value: object, limit: int = 200) -> str | None:
    """A peer's free text, clipped, or None. Never markup, never unbounded."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def identify(url: str) -> PeerIdentity:
    """Ask a hub who it is, following NodeInfo's two hops.

    Raises :class:`PeerUnreachable` for everything that goes wrong, including a hub that
    answers but does not federate — from here those are the same fact: there is nobody
    to talk to at that address.
    """
    base = _permitted(url)
    index = _fetch_json(f"{base}/.well-known/nodeinfo")

    links = index.get("links")
    href = None
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            rel, target = link.get("rel"), link.get("href")
            if isinstance(rel, str) and rel.startswith(NODEINFO_REL_PREFIX):
                if isinstance(target, str):
                    href = target
    if href is None:
        raise PeerUnreachable(f"{base} does not advertise a NodeInfo document")
    # Compared as parsed origins, never as strings. `startswith` was exploitable by
    # `https://good.example@127.0.0.1:8443/…`, where the apparent host is userinfo.
    try:
        if _origin(href) != _origin(base):
            raise PeerUnreachable(f"{base} points its NodeInfo at another host")
    except PeerUnreachable:
        raise
    except ValueError as bad:
        raise PeerUnreachable(f"{base} advertises an unusable NodeInfo URL") from bad

    document = _fetch_json(href)
    software = document.get("software")
    software = software if isinstance(software, dict) else {}
    metadata = document.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    usage = document.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    users = usage.get("users") if isinstance(usage.get("users"), dict) else {}
    total = users.get("total") if isinstance(users, dict) else None

    return PeerIdentity(
        base=base,
        software=_text(software.get("name"), 64) or "unknown",
        version=_text(software.get("version"), 64) or "unknown",
        federates=metadata.get("federation") == "enabled",
        title=_text(metadata.get("title")),
        description=_text(metadata.get("description"), 500),
        users=total if isinstance(total, int) and total >= 0 else None,
    )
