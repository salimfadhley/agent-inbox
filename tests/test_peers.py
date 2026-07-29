"""Asking another hub who it is — and refusing to ask the wrong things.

A peer's descriptor is untrusted input from a machine we have not verified. Most of
these tests are about what we refuse to do with it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_inbox.peers import (
    MAX_DESCRIPTOR_BYTES,
    PeerUnreachable,
    identify,
)


class _Stub(BaseHTTPRequestHandler):
    """A hub-shaped thing that answers whatever the test told it to."""

    routes: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        body = self.routes.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_: object) -> None:
        return


@pytest.fixture
def stub():
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def serve(routes: dict[str, object]) -> str:
        _Stub.routes = routes
        return base

    yield serve
    server.shutdown()


def _nodeinfo(base: str, **metadata: object) -> dict[str, object]:
    return {
        f"{base}/.well-known/nodeinfo": {
            "links": [
                {
                    "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                    "href": f"{base}/nodeinfo/2.1",
                }
            ]
        },
        f"{base}/nodeinfo/2.1": {
            "version": "2.1",
            "software": {"name": "agent-inbox", "version": "9.9.9"},
            "protocols": ["activitypub"],
            "services": {"inbound": [], "outbound": []},
            "openRegistrations": False,
            "usage": {"users": {"total": 4}},
            "metadata": {"federation": "enabled", **metadata},
        },
    }


class TestIdentifying:
    def test_it_reads_a_hub(self, stub) -> None:
        base = stub({})
        routes = {k.replace(base, ""): v for k, v in _nodeinfo(base).items()}
        stub(routes)
        who = identify(base)
        assert who.software == "agent-inbox"
        assert who.version == "9.9.9"
        assert who.federates is True
        assert who.users == 4

    def test_free_text_is_carried_but_clipped(self, stub) -> None:
        base = stub({})
        long = "x" * 5000
        routes = {
            k.replace(base, ""): v
            for k, v in _nodeinfo(base, title="The Salt Club", description=long).items()
        }
        stub(routes)
        who = identify(base)
        assert who.title == "The Salt Club"
        assert who.description is not None
        assert len(who.description) <= 500, "a peer must not decide how much we store"


class TestWhatItRefusesToDo:
    """The interesting half. A descriptor is a claim from an unverified machine."""

    def test_only_https_and_loopback_http(self) -> None:
        for url in (
            "http://elsewhere.invalid",
            "ftp://x.invalid",
            "file:///etc/passwd",
        ):
            with pytest.raises(PeerUnreachable) as caught:
                identify(url)
            assert "scheme" in str(caught.value) or "not a URL" in str(caught.value)

    def test_https_is_permitted(self) -> None:
        """It will try, and fail to connect — which is a different failure."""
        with pytest.raises(PeerUnreachable) as caught:
            identify("https://nothing.invalid")
        assert "could not reach" in str(caught.value)

    def test_a_path_is_discarded(self, stub) -> None:
        """A peer is an origin. Keeping the path would let a typo point us anywhere."""
        base = stub({})
        routes = {k.replace(base, ""): v for k, v in _nodeinfo(base).items()}
        stub(routes)
        assert identify(f"{base}/some/deep/path?x=1").base == base

    def test_a_descriptor_pointing_elsewhere_is_refused(self, stub) -> None:
        """Either misconfigured, or trying to make us fetch a third party."""
        base = stub(
            {
                "/.well-known/nodeinfo": {
                    "links": [
                        {
                            "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                            "href": "https://somewhere-else.invalid/nodeinfo/2.1",
                        }
                    ]
                }
            }
        )
        with pytest.raises(PeerUnreachable) as caught:
            identify(base)
        assert "another host" in str(caught.value)

    def test_an_oversized_document_is_refused(self, stub) -> None:
        base = stub({})
        routes = {k.replace(base, ""): v for k, v in _nodeinfo(base).items()}
        routes["/nodeinfo/2.1"] = b"{" + b"x" * (MAX_DESCRIPTOR_BYTES + 100)
        stub(routes)
        with pytest.raises(PeerUnreachable) as caught:
            identify(base)
        assert "bytes" in str(caught.value)

    def test_a_hub_with_no_nodeinfo_is_refused(self, stub) -> None:
        base = stub({"/.well-known/nodeinfo": {"links": []}})
        with pytest.raises(PeerUnreachable) as caught:
            identify(base)
        assert "does not advertise" in str(caught.value)

    def test_garbage_is_refused_rather_than_crashing(self, stub) -> None:
        base = stub({"/.well-known/nodeinfo": b"not json at all"})
        with pytest.raises(PeerUnreachable):
            identify(base)

    def test_a_non_object_document_is_refused(self, stub) -> None:
        base = stub({"/.well-known/nodeinfo": b"[1,2,3]"})
        with pytest.raises(PeerUnreachable):
            identify(base)

    def test_a_hub_that_does_not_federate_reads_as_such(self, stub) -> None:
        base = stub({})
        routes = {k.replace(base, ""): v for k, v in _nodeinfo(base).items()}
        routes["/nodeinfo/2.1"]["metadata"]["federation"] = "disabled"
        stub(routes)
        assert identify(base).federates is False
