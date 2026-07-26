"""The command line's own surface.

Only what something else depends on. `--version` is here because the onboarding prompt
tells every arriving agent to run it before installing: if the flag ever stops working,
the check silently becomes "not a command" and every agent reinstalls unconditionally —
harmless the first time, wrong as a diagnosis, and invisible without this test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_mailbox import __version__
from agent_mailbox.cli import main
from agent_mailbox.client import Config


def test_version_is_asked_for_without_a_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reader runs it before they have any idea what the subcommands are.

    A copy too old to know today's subcommands must still be able to say how old it
    is, so this pins that `--version` answers with no subcommand at all — and answers
    successfully, since the prompt treats any failure as "install it".
    """
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    # Compared against the package version, not a literal: a number typed into the
    # parser would stop being true at the next release without anything failing. The
    # program name is whichever of the two commands was invoked, so only the version
    # itself is pinned here.
    assert out.strip().endswith(__version__)
    assert out.split()[0] in {"agent-mailbox", "agent-inbox", "pytest"}


def test_every_documented_command_exists() -> None:
    """The prompt, the help text and the token instructions all name commands.

    A command named in text and missing from the program is a dead end an agent cannot
    diagnose, and the two drift apart silently.
    """
    from agent_mailbox.cli import cli

    names = set(cli.commands)
    assert {"doctor", "join", "config", "mcp", "serve", "console", "ping"} <= names
    # `configure` is an alias rather than a second command, so it resolves without
    # appearing twice in help.
    assert "configure" not in names
    assert cli.get_command(None, "configure") is cli.get_command(None, "config")  # type: ignore[arg-type]


def test_doctor_says_what_to_do_when_there_is_no_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before `join`, no config is the normal state — not a stack trace.

    It is also the first rung of the ladder: if this does not stop cleanly, every
    later check produces a second, more confusing error about the same cause.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_MAILBOX_HUB", raising=False)
    monkeypatch.delenv("AGENT_MAILBOX_NAME", raising=False)
    assert main(["doctor"]) == 2
    err = capsys.readouterr().err
    assert "configuration" in err
    assert "join" in err or "agent-mailbox.toml" in err


def test_doctor_keeps_the_global_token_when_identity_is_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A human shell has no engine marker, but the shared token still applies."""

    class FakeHubClient:
        configs: list[Config] = []

        def __init__(self, config: Config) -> None:
            self.config = config
            self.configs.append(config)

        def hub_info(self) -> dict[str, Any]:
            return {"name": "hub", "version": "test", "authenticated": True}

        def remote_doctor(self) -> dict[str, Any]:
            if self.config.token:
                return {
                    "you": {"token": "accepted"},
                    "verdict": "your token was accepted",
                }
            return {
                "you": {"token": "not presented"},
                "verdict": "no token presented",
            }

    xdg = tmp_path / "xdg"
    (xdg / "agent-inbox").mkdir(parents=True)
    (xdg / "agent-inbox" / "config.toml").write_text('token = "shared-secret"\n')
    (tmp_path / "agent-mailbox.toml").write_text(
        'hub = "http://hub:8081"\n\n'
        "[agents.claude]\n"
        'name = "nicole_ruzickova"\n\n'
        "[agents.codex]\n"
        'name = "pablo_fantomas"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.delenv("CODEX_SANDBOX", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_MANAGED_BY_NPM", raising=False)
    monkeypatch.delenv("CODEX_CI", raising=False)
    monkeypatch.delenv("AGENT_MAILBOX_TOKEN", raising=False)
    monkeypatch.setattr("agent_mailbox.cli.HubClient", FakeHubClient)

    assert main(["doctor"]) == 2

    out = capsys.readouterr().out
    assert FakeHubClient.configs[0].token == "shared-secret"
    assert "no entry for this engine yet" in out
    assert "device token accepted by the hub" in out
    assert "shared, from" in out
    assert "api             not joined yet" in out


class TestConfigure:
    """The tool owns its configuration; nobody should be editing these files."""

    def _run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("AGENT_MAILBOX_HUB", raising=False)
        monkeypatch.delenv("AGENT_MAILBOX_NAME", raising=False)
        monkeypatch.chdir(tmp_path)
        return main(["config", *args])

    def test_a_shared_token_goes_machine_wide_and_stays_private(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A credential admits the machine, so it is written once — and 0600.

        The default umask would leave it world-readable, which for a token that admits
        every agent on the box is the whole security of the thing.
        """
        run = self._run(tmp_path, monkeypatch, "set", "--global", "token", "sekrit")
        assert run == 0
        written = tmp_path / "xdg" / "agent-inbox" / "config.toml"
        assert 'token = "sekrit"' in written.read_text()
        assert written.stat().st_mode & 0o077 == 0, "readable by others"

    def test_the_key_value_form_is_accepted_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`name=value` is what anyone who has used a config tool reaches for."""
        assert self._run(tmp_path, monkeypatch, "set", "role=host") == 0
        assert 'role = "host"' in (tmp_path / "agent-mailbox.toml").read_text()

    def test_identity_is_refused_machine_wide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same engine in two repositories is two correspondents.

        A machine-wide name would quietly merge them into one inbox — the exact
        failure hub-issued names exist to prevent.
        """
        assert self._run(tmp_path, monkeypatch, "set", "--global", "name", "x") == 2

    def test_an_unknown_setting_is_refused_rather_than_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A silently accepted typo leaves a file that reads correct and is not."""
        assert self._run(tmp_path, monkeypatch, "set", "tokne", "sekrit") == 2
