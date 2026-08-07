"""What version is serving these tools? (issues #35 and #60)

There are **three installs**, not two: the hub, the `agent-inbox` in a shell, and the
MCP server process that actually answers an agent's tool calls. The third was
unmeasurable from anywhere.

`ludmila_coe` hit this on 2026-07-31 trying to settle whether a missing tool parameter
was a defect in what we advertise or merely a stale long-running session. Five rounds of
correspondence failed, and the reason was structural rather than careless:

- a stdio server keeps whatever it loaded when it started;
- upgrading afterwards overwrites the shims and dist-info, destroying the evidence;
- `lsof` on the live process shows nothing — Python does not hold that metadata open.

So the two halves of the comparison both had to be built. `ping` reports the version of
the process answering *now*; `mcp --describe` prints what a *fresh* build advertises.
Neither is useful alone, which is why they ship together.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_inbox import __version__


class TestPingNamesTheProcessThatAnswered:
    async def test_ping_reports_the_serving_version_beside_the_hub_s(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both numbers, because the interesting thing about either is the other.

        Reporting only the server's version would answer "what is serving me" while
        destroying "do these two agree" — which is the question the drift actually
        raises, and the one #60 was filed about.
        """
        from agent_inbox import mcp_client

        class Hub:
            def ping(self) -> dict[str, object]:
                return {"you": "ludmila_coe", "version": "9.9.9"}

        monkeypatch.setattr(mcp_client, "_client", lambda: Hub())
        monkeypatch.setattr(mcp_client, "_resolve_project", _nothing)
        monkeypatch.setattr(mcp_client, "_start_listening", lambda: None)

        answer = await mcp_client.ping()

        assert answer["version"] == "9.9.9", "the hub's version must not be replaced"
        assert answer["server"] == __version__


async def _nothing() -> None:
    return None


class TestDescribePrintsWhatThisBuildAdvertises:
    """The other half. A parameter that exists but is not advertised is a feature no
    agent can discover, and until now there was no way to notice."""

    def _described(self) -> dict[str, object]:
        from click.testing import CliRunner

        from agent_inbox.cli import cli

        result = CliRunner().invoke(cli, ["mcp", "--describe"])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_it_names_the_version_it_is_describing(self) -> None:
        """A schema with no version attached cannot settle anything — the whole point
        is comparing one build's advertisement against another's."""
        assert self._described()["version"] == __version__

    def test_it_lists_the_tools_with_their_parameters(self) -> None:
        described = self._described()
        tools = {tool["name"]: tool["parameters"] for tool in described["tools"]}  # type: ignore[index,union-attr]

        assert "check_inbox" in tools
        assert "send_message" in tools

    def test_it_settles_ludmilas_actual_question(self) -> None:
        """The reported observation was `check_inbox` exposed as zero-arg in a Codex
        session. This build advertises both parameters — so had this existed, the
        answer would have been "your session is stale", in one command instead of five
        rounds of correspondence.

        Asserted on the real tools rather than a fixture on purpose: a fixture would
        prove the printer works and say nothing about what we actually offer.
        """
        described = self._described()
        check_inbox = next(
            tool
            for tool in described["tools"]  # type: ignore[union-attr]
            if tool["name"] == "check_inbox"  # type: ignore[index]
        )

        assert set(check_inbox["parameters"]) >= {"since", "full"}  # type: ignore[index]

    def test_describing_does_not_start_the_server(self) -> None:
        """`--describe` must exit rather than fall through into `mcp.run()`, which
        would hang on stdio waiting for a client that is never coming."""
        from click.testing import CliRunner

        from agent_inbox.cli import cli

        result = CliRunner().invoke(cli, ["mcp", "--describe"])

        assert result.exit_code == 0


class TestDoctorDoesNotImplyItSawEverything:
    """#60. `doctor` prints the client's version and the hub's. Two numbers with
    nothing beside them read as the whole story — which is how somebody concludes an
    upgrade took while the process actually serving them is months behind."""

    class _Hub:
        def __init__(self, config: object) -> None:
            self.config = config

        def hub_info(self) -> dict[str, Any]:
            return {"name": "hub", "version": __version__, "authenticated": False}

        def remote_doctor(self) -> dict[str, Any]:
            return {"you": {"token": "not needed"}, "verdict": "fine"}

        def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
            return {"items": []}

        def ping(self) -> dict[str, Any]:
            return {"you": "ludmila_coe"}

        def whois(self, name: str) -> dict[str, Any]:
            return {"preferredUsername": name, "profile": {"purpose": "hosting"}}

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> str:
        from agent_inbox.cli import main
        from agent_inbox.client import CONFIG_NAME

        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\nname = "ludmila_coe"\n'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("CLAUDECODE", "1")
        for var in ("AGENT_MAILBOX_HUB", "AGENT_MAILBOX_NAME", "AGENT_INBOX_HUB"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("agent_inbox.cli.HubClient", self._Hub)
        assert main(["doctor"]) == 0
        return capsys.readouterr().out

    def test_it_says_a_third_install_exists(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = self._run(tmp_path, monkeypatch, capsys)

        assert f"client {__version__}" in out, "precondition: the versions line ran"
        assert "third install" in out
        assert "ping" in out, "saying it is invisible without saying how to ask"

    def test_it_is_not_a_finding_of_its_own(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A `--` line nobody can ever clear is furniture, and a reader learns to skip
        it — including on the run where something else amber actually mattered. So this
        rides on the `ok` versions line rather than becoming a permanent amber marker.
        """
        out = self._run(tmp_path, monkeypatch, capsys)

        mcp_lines = [line for line in out.splitlines() if "third install" in line]
        assert len(mcp_lines) == 1
        assert mcp_lines[0].lstrip().startswith("ok"), mcp_lines[0]
