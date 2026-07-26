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
    # The property this test was written for, unchanged: the shared token reaches the
    # hub and is reported as accepted even though no identity could be resolved.
    assert FakeHubClient.configs[0].token == "shared-secret"
    assert "device token accepted by the hub" in out
    assert "shared, from" in out
    # The wording moved with the explicit-engine mission. "No entry for this engine"
    # was the old diagnosis and it was wrong here: the project has two entries, and
    # what is missing is the *choice*, not the configuration. Saying so — and naming
    # both engines — is the difference between "join" and "rerun with --engine".
    assert "no engine selected" in out
    assert "claude, codex" in out
    assert "--engine claude doctor" in out


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


class TestExplicitEngine:
    """A human shell must not be able to act as, or write to, the wrong agent.

    An agent session carries a marker and never meets any of this. A human shell does
    not, and in a project configuring several agents there is no honest default:
    picking one acts as somebody else, and a synthetic `default` entry belongs to
    nobody. So the CLI refuses and says how.
    """

    def _project(self, tmp_path: Path, *engines: str) -> Path:
        body = 'hub = "http://hub.invalid:8081"\n'
        for engine in engines:
            body += f'\n[agents.{engine}]\nname = "name_{engine}"\nrole = "agent"\n'
        (tmp_path / "agent-mailbox.toml").write_text(body)
        return tmp_path

    def _shell(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A plain human shell: no engine marker of any kind."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for var in (
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "CODEX_SANDBOX",
            "CODEX_HOME",
            "CODEX_THREAD_ID",
            "CODEX_MANAGED_BY_NPM",
            "CODEX_CI",
            "AGENT_MAILBOX_HUB",
            "AGENT_MAILBOX_NAME",
            "AGENT_MAILBOX_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_a_project_write_refuses_and_names_the_engines(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """NFR-001: nothing is written. The file must be byte-identical afterwards."""
        self._project(tmp_path, "claude", "codex")
        before = (tmp_path / "agent-mailbox.toml").read_text()
        self._shell(tmp_path, monkeypatch)

        assert main(["config", "set", "role", "host"]) == 2

        err = capsys.readouterr().err
        assert "cannot tell which engine" in err
        assert "claude, codex" in err
        assert "--engine claude config" in err
        assert (tmp_path / "agent-mailbox.toml").read_text() == before

    def test_an_agent_command_refuses_before_reaching_the_hub(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FR-004. The hub url here is unroutable: if it were contacted the failure
        would be a timeout, not a usage error, so this also pins the *ordering*."""
        self._project(tmp_path, "claude", "codex")
        self._shell(tmp_path, monkeypatch)
        assert main(["ping"]) == 2
        assert "cannot tell which engine" in capsys.readouterr().err

    def test_the_flag_resolves_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-001/FR-003: named explicitly, the write lands in that engine's entry."""
        self._project(tmp_path, "claude", "codex")
        self._shell(tmp_path, monkeypatch)

        assert main(["--engine", "codex", "config", "set", "role", "host"]) == 0

        written = (tmp_path / "agent-mailbox.toml").read_text()
        assert 'name = "name_codex"' in written
        codex_block = written.split("[agents.codex]")[1]
        assert 'role = "host"' in codex_block
        # and the other agent is untouched
        claude_block = written.split("[agents.claude]")[1].split("[agents.")[0]
        assert 'role = "agent"' in claude_block

    def test_machine_wide_settings_need_no_engine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-005: a credential admits the machine and names no agent, so a plain
        shell must be able to set one — and must not create a project entry doing it."""
        self._project(tmp_path, "claude", "codex")
        before = (tmp_path / "agent-mailbox.toml").read_text()
        self._shell(tmp_path, monkeypatch)

        assert main(["config", "set", "--global", "token", "sekrit"]) == 0
        assert main(["config", "list"]) == 0
        assert main(["config", "path"]) == 0

        assert (tmp_path / "agent-mailbox.toml").read_text() == before

    def test_a_single_entry_still_works_without_a_flag(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FR-009: one entry, nothing to get wrong. The compatibility case."""
        self._project(tmp_path, "claude")
        self._shell(tmp_path, monkeypatch)
        assert main(["config", "set", "role", "host"]) == 0
        assert 'role = "host"' in (tmp_path / "agent-mailbox.toml").read_text()

    def test_ambiguity_is_shown_rather_than_omitted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FR-010: `config list` must not report a configured project as empty."""
        self._project(tmp_path, "claude", "codex")
        self._shell(tmp_path, monkeypatch)
        assert main(["config", "list"]) == 0
        out = capsys.readouterr().out
        assert "ambiguous" in out
        assert "claude, codex" in out

    def test_naming_an_engine_the_project_lacks_says_so_precisely(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec edge case: chose an engine, and the choice does not exist.

        Distinct from having chosen nothing. Before this, it fell through to the
        generic "write agent-mailbox.toml in your project root" — telling someone to
        create a file that is open in front of them, for an engine they just named.
        """
        self._project(tmp_path, "claude")
        self._shell(tmp_path, monkeypatch)
        assert main(["--engine", "codex", "ping"]) == 2
        err = capsys.readouterr().err
        assert "no entry for engine 'codex'" in err
        assert "Configured engines: claude" in err
        assert "join --engine codex" in err

    def test_but_creating_that_entry_is_still_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acting as a missing engine is refused; *making* one is how it is made.

        `join` and `config set` must stay permissive here or there would be no way to
        add a second agent to a project.
        """
        self._project(tmp_path, "claude")
        self._shell(tmp_path, monkeypatch)
        assert main(["--engine", "codex", "config", "set", "role", "host"]) == 0
        written = (tmp_path / "agent-mailbox.toml").read_text()
        assert "[agents.codex]" in written
        assert 'role = "host"' in written.split("[agents.codex]")[1]

    def test_onboarding_advice_names_the_engine_when_one_must_be_chosen(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec edge case: a hub, no entries, no marker.

        A bare `join` would refuse for the same reason everything else does, so
        suggesting it would send the reader in a circle.
        """
        (tmp_path / "agent-mailbox.toml").write_text(
            'hub = "http://hub.invalid:8081"\n'
        )
        self._shell(tmp_path, monkeypatch)

        class Reachable:
            """Answers as a live hub would, so doctor reaches the advice it gives."""

            def __init__(self, config: Config) -> None:
                self.config = config

            def hub_info(self) -> dict[str, Any]:
                return {"name": "hub", "version": "test", "authenticated": False}

            def remote_doctor(self) -> dict[str, Any]:
                return {"you": {"token": "not presented"}, "verdict": "no token needed"}

        monkeypatch.setattr("agent_mailbox.cli.HubClient", Reachable)
        main(["doctor"])
        assert "join --engine <engine>" in capsys.readouterr().out
