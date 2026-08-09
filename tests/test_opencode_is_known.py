"""A harness we do not know must say so, and opencode is now known (issue #63).

`aurelia_saahaa` joined on **opencode** and found it was in neither detection path — not
`ENGINE_MARKERS` (the environment) nor `_CLIENT_ENGINES` (the name a client gives when
it connects). So the server could not match their session to its `[agents.opencode]`
entry, and they had to set `AGENT_INBOX_NAME` by hand.

Two fixes, and the second matters more than the first.

**opencode is added**, on their report from a live session: it sets `OPENCODE=1`, and
its `initialize` carries "opencode" in `clientInfo.name`. The second path is better
because it needs no environment variable at all.

**And an unrecognised name is now logged.** That is the durable half. Working out that
opencode was unknown cost a round of correspondence and a read of their source — while
the name we did not recognise was sitting right there, unprinted. The next new harness
diagnoses itself.
"""

import logging

import pytest


class TestOpencodeIsDetected:
    def test_the_environment_marker_is_recognised(self) -> None:
        """The bug, at its smallest: `OPENCODE=1` meant nothing to us."""
        from agent_inbox.client import detect_engine

        assert detect_engine({"OPENCODE": "1"}) == "opencode"

    def test_the_client_name_is_recognised(self) -> None:
        """The better path — no environment variable needed at all, because the client
        tells us what it is during the MCP handshake."""
        from agent_inbox.mcp_client import _CLIENT_ENGINES

        matched = [engine for marker, engine in _CLIENT_ENGINES if marker in "opencode"]

        assert "opencode" in matched

    def test_the_harnesses_we_already_knew_still_resolve(self) -> None:
        """The paired positive. Adding a marker must not disturb the four that were
        there — and `CODEX_*` in particular has already been through one round of
        detection that worked on some installs and not others."""
        from agent_inbox.client import detect_engine

        assert detect_engine({"CLAUDECODE": "1"}) == "claude"
        assert detect_engine({"CODEX_THREAD_ID": "abc"}) == "codex"
        assert detect_engine({"GEMINI_CLI": "1"}) == "gemini"
        assert detect_engine({"CURSOR_TRACE_ID": "x"}) == "cursor"

    def test_an_empty_environment_still_admits_it_does_not_know(self) -> None:
        """The property that must survive every addition. A guess here hands one engine
        another's identity; an honest `None` is answerable by the agent naming itself.
        """
        from agent_inbox.client import detect_engine

        assert detect_engine({}) is None


class TestAnUnknownHarnessSaysSo:
    """The half that stops this happening again."""

    def _resolve_with_client_named(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio
        from dataclasses import dataclass

        from agent_inbox import mcp_client

        @dataclass
        class ClientInfo:
            name: str

        @dataclass
        class Info:
            clientInfo: ClientInfo  # noqa: N815 - mirrors the MCP struct

        class Session:
            client_params = Info(ClientInfo(name))

        class Ctx:
            session = Session

        monkeypatch.setattr(mcp_client, "get_context", lambda: Ctx)
        monkeypatch.setattr(mcp_client, "_roots_asked", False)
        monkeypatch.setattr(mcp_client, "_project", None)
        asyncio.run(mcp_client._resolve_project())

    def test_an_unrecognised_name_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The bug that cost a round of correspondence: the name was available and
        nothing printed it, so the failure surfaced later as a refusal that could not
        name its own cause."""
        with caplog.at_level(logging.WARNING, logger="agent_inbox.mcp"):
            self._resolve_with_client_named("some-future-harness", monkeypatch)

        assert "some-future-harness" in caplog.text
        assert "not a harness I know" in caplog.text

    def test_a_recognised_name_does_not_warn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The paired positive, and the reason this is a `for`/`else` rather than a
        check after the loop: a warning on every ordinary session is furniture, and a
        reader learns to skip it — including on the session where it was true."""
        with caplog.at_level(logging.WARNING, logger="agent_inbox.mcp"):
            self._resolve_with_client_named("opencode", monkeypatch)

        assert "not a harness I know" not in caplog.text
