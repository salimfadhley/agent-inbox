"""Asking another hub who it is — and refusing to ask the wrong things.

A peer's descriptor is untrusted input from a machine we have not verified. Most of
these tests are about what we refuse to do with it.
"""

import json
import threading
import time
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


class TestServerSideRequestForgery:
    """Both found by outside review, 2026-07-29. Both were exploitable.

    A hostile peer controls the server at the URL an operator types. These are the two
    ways it could turn that into a request the hub never meant to make.
    """

    def test_a_redirect_is_refused_not_followed(self) -> None:
        """`urlopen` follows redirects by default, and the scheme check ran against the
        URL the operator typed rather than the one actually fetched.

        So a peer answering `302 Location: http://10.0.0.5:8080/` reached the internal
        network, and `http://169.254.169.254/` reached cloud metadata.

        The redirect here points at a **second local server that records being hit**.
        Asserting only that an error is raised would pass whether or not the redirect
        was followed, because an unreachable target raises too — the assertion that
        discriminates is that the target was never touched.
        """
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        touched: list[str] = []

        class Secret(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                touched.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_: object) -> None:
                return

        secret = HTTPServer(("127.0.0.1", 0), Secret)
        threading.Thread(target=secret.serve_forever, daemon=True).start()
        secret_url = f"http://127.0.0.1:{secret.server_port}/internal"

        class Redirector(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header("Location", secret_url)
                self.end_headers()

            def log_message(self, *_: object) -> None:
                return

        hostile = HTTPServer(("127.0.0.1", 0), Redirector)
        threading.Thread(target=hostile.serve_forever, daemon=True).start()
        try:
            with pytest.raises(PeerUnreachable):
                identify(f"http://127.0.0.1:{hostile.server_port}")
        finally:
            hostile.shutdown()
            secret.shutdown()

        assert touched == [], f"the redirect was followed and reached {touched}"

    def test_userinfo_cannot_disguise_the_real_host(self) -> None:
        """`https://good.example@127.0.0.1:8443/x` starts with `https://good.example`
        and points at loopback: everything before the `@` is userinfo.

        The origin check compared strings, so this passed it. It now compares parsed
        origins, and credentials in an address are refused outright.
        """
        with pytest.raises(PeerUnreachable) as caught:
            identify("https://good.example@127.0.0.1:8443")
        assert "credentials" in str(caught.value)

    def test_a_descriptor_cannot_point_at_a_disguised_host(self, stub) -> None:
        """The same trick one hop later, crafted so the *old* check would have passed.

        The old test compared `href.startswith(base)`. This href genuinely starts with
        the base string and still resolves elsewhere, because everything before the
        `@` is userinfo — which is the whole point.
        """
        base = stub({})
        disguised = f"{base}@169.254.169.254/nodeinfo/2.1"
        assert disguised.startswith(base), (
            "the test input must defeat the prefix check, or it proves nothing"
        )
        stub(
            {
                "/.well-known/nodeinfo": {
                    "links": [
                        {
                            "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                            "href": disguised,
                        }
                    ]
                }
            }
        )
        with pytest.raises(PeerUnreachable):
            identify(base)

    def test_a_dripping_peer_cannot_hold_the_request_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The socket timeout is an *idle* timeout: it resets on every byte.

        A peer sending one byte every nine seconds satisfies it forever, so the request
        needs a wall-clock budget as well. Found by outside review, 2026-07-29.

        The deadline is shortened here rather than waiting for the real one — the
        behaviour under test is that elapsed time is checked at all.
        """
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from agent_inbox import peers

        class Dripper(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(peers.MAX_DESCRIPTOR_BYTES))
                self.end_headers()
                for _ in range(peers.MAX_DESCRIPTOR_BYTES):
                    try:
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.05)

            def log_message(self, *_: object) -> None:
                return

        monkeypatch.setattr(peers, "FETCH_DEADLINE_SECONDS", 1)
        monkeypatch.setattr(peers, "_CHUNK", 1)

        server = HTTPServer(("127.0.0.1", 0), Dripper)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started = time.monotonic()
        try:
            with pytest.raises(PeerUnreachable) as caught:
                peers.identify(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()

        elapsed = time.monotonic() - started
        assert "longer than" in str(caught.value), str(caught.value)
        assert elapsed < 10, f"the deadline did not stop it; took {elapsed:.1f}s"
