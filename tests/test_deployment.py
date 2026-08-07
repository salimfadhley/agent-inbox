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


class TestAStaleConsoleIsCaught:
    """Issue #59: the deploy proved the hub and took the console on faith.

    A deploy updates two apps. This checked one — it fetched the prompt *from* the
    console to compare a caution, which a console five releases behind answers perfectly
    well. So it passed, and the summary said *"all 1 target(s) proved themselves"*.

    **A verifier reporting success for something it never examined is this project's
    worst failure shape, and it was sitting inside the tool built to catch it.** It cost
    real confusion: on 2026-08-05 a deploy was reported green while the console's own
    version was never established.
    """

    HUB = "https://hub.example"
    PROMPT = "https://console.example/prompts/agent"

    @staticmethod
    def _hub_body(version: str) -> bytes:
        import json

        return json.dumps(
            {"version": version, "authenticated": True, "id": "https://hub.example"}
        ).encode()

    def _answers(
        self, hub_version: str, console_version: str | None, prompt: str
    ) -> object:
        """A fetcher standing in for both apps, so the two versions can disagree."""
        import json

        def get(url: str, timeout: int = 0) -> tuple[int, bytes]:
            if url.endswith("/health"):
                body: dict[str, object] = {"status": "ok"}
                if console_version is not None:
                    body["version"] = console_version
                return 200, json.dumps(body).encode()
            if "/prompts/" in url:
                return 200, prompt.encode()
            return 200, self._hub_body(hub_version)

        return get

    def test_a_console_behind_the_hub_fails_the_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug, stated as a test. Both apps were deployed; only one moved."""
        from agent_inbox import deployment

        monkeypatch.setattr(
            deployment, "_get", self._answers("1.2.3", "1.0.0", AUTHENTICATED_OPENER)
        )

        report = deployment.verify(self.HUB, "1.2.3", self.PROMPT)

        assert not report.ok, "a console five releases behind passed the deploy check"
        assert any("console" in c.name for c in report.checks)

    def test_both_current_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The paired positive. A check that failed whenever a console was mentioned
        would satisfy the test above and block every deploy."""
        from agent_inbox import deployment

        monkeypatch.setattr(
            deployment, "_get", self._answers("1.2.3", "1.2.3", AUTHENTICATED_OPENER)
        )

        report = deployment.verify(self.HUB, "1.2.3", self.PROMPT)

        assert report.ok, [str(c) for c in report.checks]

    def test_a_console_too_old_to_say_is_a_failure_not_a_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case that would recreate the bug in a new place. A console predating this
        field is exactly the console the check exists to find, and treating its silence
        as a pass would be the same mistake wearing different clothes."""
        from agent_inbox import deployment

        monkeypatch.setattr(
            deployment, "_get", self._answers("1.2.3", None, AUTHENTICATED_OPENER)
        )

        report = deployment.verify(self.HUB, "1.2.3", self.PROMPT)

        assert not report.ok
        assert any("console reports a version" in c.name for c in report.checks)

    def test_the_hub_alone_is_still_checkable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No prompt url means no console — a hub-only deployment must not be failed for
        lacking a console it does not have."""
        from agent_inbox import deployment

        monkeypatch.setattr(deployment, "_get", self._answers("1.2.3", None, ""))

        report = deployment.verify(self.HUB, "1.2.3", "")

        assert report.ok
        assert not any("console" in c.name for c in report.checks)
