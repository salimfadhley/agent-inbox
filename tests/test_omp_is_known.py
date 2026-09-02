"""omp (oh-my-pi) is a harness we know when it connects (issue #65, part A).

omp sends `clientInfo.name = "omp-coding-agent"` on the MCP handshake — read from its
`mcp/client.ts`, not recalled — and exports **no** environment marker to its children
at all. So `_CLIENT_ENGINES` is its only detection route, which is fine: it is the
better of the two anyway, needing no variable set by anybody.

It matters more than a new harness usually would, because omp **imports Claude Code's
MCP config** (`~/.claude.json` and friends). Anyone who configured the mailbox for
Claude Code already has it in omp, so an unrecognised `omp-coding-agent` has probably
been reaching hubs for a while — falling through to the unknown-harness warning #63
added, which is what made this diagnosable at all.
"""

import logging
from pathlib import Path

import pytest


class TestOmpIsDetected:
    def test_the_client_name_is_recognised(self) -> None:
        """The name omp actually sends, matched the way `_resolve_project` matches."""
        from agent_inbox.mcp_client import _CLIENT_ENGINES

        name = "omp-coding-agent"
        matched = [engine for marker, engine in _CLIENT_ENGINES if marker in name]

        assert matched == ["omp"]

    def test_the_shortest_marker_does_not_shadow_a_longer_one(self) -> None:
        """`omp` is three letters and matching is by substring. It must sit after the
        harnesses that were there, so no longer name is claimed by it first — and no
        name we know contains it, which is the property that keeps substring matching
        honest."""
        from agent_inbox.mcp_client import _CLIENT_ENGINES

        markers = [marker for marker, _ in _CLIENT_ENGINES]

        assert markers[-1] == "omp"
        assert not any("omp" in other for other in markers[:-1])

    def test_the_harnesses_we_already_knew_still_resolve(self) -> None:
        """The paired positive."""
        from agent_inbox.mcp_client import _CLIENT_ENGINES

        def resolve(name: str) -> str | None:
            for marker, engine in _CLIENT_ENGINES:
                if marker in name:
                    return engine
            return None

        assert resolve("claude-code") == "claude"
        assert resolve("opencode") == "opencode"
        assert resolve("codex-cli") == "codex"

    def test_omp_is_recognised_from_its_own_marker(self) -> None:
        """omp sets `OMPCODE=1` on the shell it gives its agent."""
        from agent_inbox.client import detect_engine

        assert detect_engine({"OMPCODE": "1"}) == "omp"

    def test_omp_beats_the_claude_marker_it_also_sets(self) -> None:
        """**The bug `espen_luo` hit.** omp imitates Claude Code — it sets
        `CLAUDECODE=1`
        as well as its own marker — and with the Claude entries first, every command an
        omp agent ran resolved as Claude Code. Their first `join` claimed the Claude
        identity: a wrong answer, the worst this can give."""
        from agent_inbox.client import detect_engine

        assert detect_engine({"CLAUDECODE": "1", "OMPCODE": "1"}) == "omp"

    def test_claude_code_alone_is_still_claude(self) -> None:
        """The paired positive: Claude Code sets only its own marker."""
        from agent_inbox.client import detect_engine

        assert detect_engine({"CLAUDECODE": "1"}) == "claude"
        assert detect_engine({"CLAUDE_CODE_ENTRYPOINT": "cli"}) == "claude"

    def test_the_omp_marker_is_checked_before_every_claude_one(self) -> None:
        """The structural fact the two tests above depend on: first match wins."""
        from agent_inbox.client import ENGINE_MARKERS

        markers = [marker for marker, _ in ENGINE_MARKERS]
        first_claude = min(
            i for i, (_, engine) in enumerate(ENGINE_MARKERS) if engine == "claude"
        )

        assert markers.index("OMPCODE") < first_claude


def _resolve_with_client_named(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive `_resolve_project` with a client that announced `name` on connect."""
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


class TestARecognisedOmpDoesNotWarn:
    def test_the_name_omp_sends_is_not_reported_as_unknown(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Before this, every omp session logged that it was not a harness we knew —
        the warning #63 added doing exactly its job. Now it is known, and the warning
        must fall silent, or it becomes furniture."""
        from agent_inbox import mcp_client

        with caplog.at_level(logging.WARNING, logger="agent_inbox.mcp"):
            _resolve_with_client_named("omp-coding-agent", monkeypatch)

        assert mcp_client._engine == "omp"
        assert "not a harness I know" not in caplog.text


class TestTheAnnouncedNameBeatsAnInheritedMarker:
    """The MCP server's `join` used to sniff the environment for its engine, ignoring
    the name the client had announced on connect. Under omp — which hands its children
    Claude Code's marker — that wrote `[agents.claude]` for an omp agent."""

    def test_join_records_the_engine_the_client_announced(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import anyio
        from fastmcp import Client

        from agent_inbox import mcp_client
        from agent_inbox.client import NotConfigured

        recorded: dict[str, object] = {}

        class FakeHub:
            def __init__(self, config: object) -> None:
                pass

            def join(self, name: str | None) -> dict[str, str]:
                return {"preferredUsername": name or "issued_name"}

        def write_config(hub: str, name: str, **kwargs: object) -> Path:
            recorded["engine"] = kwargs.get("engine")
            return tmp_path / "agent-inbox.toml"

        def not_configured(*args: object, **kwargs: object) -> object:
            raise NotConfigured("nothing here")

        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("OMPCODE", raising=False)
        monkeypatch.setattr(mcp_client, "_roots_asked", True)
        monkeypatch.setattr(mcp_client, "_engine", "omp")
        monkeypatch.setattr(mcp_client, "load_config", not_configured)
        monkeypatch.setattr(mcp_client, "load_hub", lambda: "http://hub.example")
        monkeypatch.setattr(mcp_client, "HubClient", FakeHub)
        monkeypatch.setattr(mcp_client, "write_config", write_config)

        async def call() -> None:
            async with Client(mcp_client.mcp) as client:
                await client.call_tool("join", {"name": "espen_luo"})

        anyio.run(call)

        # The premise: the write happened at all — a refusal or an early return would
        # leave `recorded` empty and the assertion below vacuous.
        assert "engine" in recorded
        assert recorded["engine"] == "omp"
