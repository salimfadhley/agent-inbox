"""Proving a deployment took — issue #32.

Written against the two failures that actually happened, because both were
indistinguishable from success at the time:

- **v0.31.0** — the deploy API returned 200 while the hub kept running a version five
  releases old.
- **v0.31.1** — the deploy returned 500, left the containers created-but-not-started,
and
  took the hub down while still looking deployed.

The point of every test here is the **FAIL** case. A verifier that passes when things
are
right and also passes when they are wrong is the thing being replaced.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_inbox.deployment import (
    AUTHENTICATED_OPENER,
    OPEN_OPENER,
    verify,
    verify_all,
)


class _Hub:
    """A hub that says whatever a test needs it to say, over a real socket."""

    def __init__(self, version: str, authenticated: bool, prompt: str | None = None):
        self.version = version
        self.authenticated = authenticated
        self.prompt = prompt
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/prompts"):
                    if outer.prompt is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = outer.prompt.encode()
                    self.send_response(200)
                else:
                    body = json.dumps(
                        {
                            "version": outer.version,
                            "authenticated": outer.authenticated,
                        }
                    ).encode()
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_port
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> _Hub:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        assert not self._thread.is_alive(), "the test hub did not stop"


@pytest.fixture
def free_port() -> Iterator[int]:
    """A port with nothing on it — the v0.31.1 state."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        yield s.getsockname()[1]


class TestTheVersionCheck:
    """v0.31.0: the deploy reported success over a five-release-old hub."""

    def test_the_expected_version_passes(self) -> None:
        with _Hub("1.2.3", authenticated=True) as hub:
            assert verify(hub.base, "1.2.3").ok

    def test_an_old_version_fails(self) -> None:
        """**The one that matters.** This is v0.31.0, and nothing caught it."""
        with _Hub("0.26.0", authenticated=True) as hub:
            report = verify(hub.base, "1.2.3")
            assert not report.ok
            failed = [c for c in report.checks if not c.ok]
            assert "0.26.0" in failed[0].detail, "must say what it found, not only that"

    def test_no_expectation_asserts_nothing_about_version(self) -> None:
        """Useful for a health check; never what a deploy should do."""
        with _Hub("0.26.0", authenticated=True) as hub:
            assert verify(hub.base).ok


class TestTheReachabilityCheck:
    """v0.31.1: containers created but not started, so nothing was listening."""

    def test_a_hub_that_is_not_there_fails(self, free_port: int) -> None:
        report = verify(f"http://127.0.0.1:{free_port}", "1.2.3")
        assert not report.ok
        assert report.checks[0].name == "reachable"

    def test_it_stops_rather_than_reporting_downstream_noise(
        self, free_port: int
    ) -> None:
        """One cause, one failure. A hub that is down would otherwise fail every check
        and bury the reason in four lines of consequence."""
        report = verify(f"http://127.0.0.1:{free_port}", "1.2.3")
        assert len(report.checks) == 1


class TestThePromptInvariant:
    """The v0.31.0 prompt defect: the caution contradicted the descriptor."""

    def test_agreement_passes(self) -> None:
        with _Hub("1.2.3", True, prompt=f"blah {AUTHENTICATED_OPENER} blah") as hub:
            assert verify(hub.base, "1.2.3", f"{hub.base}/prompts/agent").ok

    def test_an_authenticated_hub_claiming_otherwise_fails(self) -> None:
        """Exactly the shipped defect: `authenticated: true`, open-network caution."""
        with _Hub("1.2.3", True, prompt=f"blah {OPEN_OPENER} blah") as hub:
            assert not verify(hub.base, "1.2.3", f"{hub.base}/prompts/agent").ok

    def test_an_open_hub_claiming_otherwise_fails(self) -> None:
        """The mirror. A word-search for "authenticate" would pass this."""
        with _Hub("1.2.3", False, prompt=f"blah {AUTHENTICATED_OPENER} blah") as hub:
            assert not verify(hub.base, "1.2.3", f"{hub.base}/prompts/agent").ok

    def test_a_prompt_carrying_both_fails(self) -> None:
        """Neither opener may appear alongside the other, or the check would pass a
        document that says two contradictory things."""
        both = f"{AUTHENTICATED_OPENER} and also {OPEN_OPENER}"
        with _Hub("1.2.3", True, prompt=both) as hub:
            assert not verify(hub.base, "1.2.3", f"{hub.base}/prompts/agent").ok

    def test_an_unreachable_prompt_fails(self) -> None:
        with _Hub("1.2.3", True, prompt=None) as hub:
            assert not verify(hub.base, "1.2.3", f"{hub.base}/prompts/agent").ok

    def test_the_check_is_skipped_when_no_prompt_url_is_given(self) -> None:
        with _Hub("1.2.3", True, prompt=f"blah {OPEN_OPENER} blah") as hub:
            assert verify(hub.base, "1.2.3").ok, "opted out, so not asserted"


class TestSeveralTargets:
    def test_all_good_passes(self) -> None:
        with _Hub("1.2.3", True) as a, _Hub("1.2.3", True) as b:
            _, ok = verify_all([(a.base, ""), (b.base, "")], "1.2.3")
            assert ok

    def test_one_bad_fails_the_whole_run(self) -> None:
        """Shipping to two targets means both, or it did not ship."""
        with _Hub("1.2.3", True) as good, _Hub("0.26.0", True) as stale:
            _, ok = verify_all([(good.base, ""), (stale.base, "")], "1.2.3")
            assert not ok

    def test_every_target_is_reported_not_just_the_first_failure(self) -> None:
        """ "Which of my hubs is wrong" is the question; stopping early answers a
        different one."""
        with _Hub("0.26.0", True) as stale, _Hub("1.2.3", True) as good:
            reports, ok = verify_all([(stale.base, ""), (good.base, "")], "1.2.3")
            assert not ok
            assert len(reports) == 2
            assert reports[1].ok, "the good one was still checked and still passed"
