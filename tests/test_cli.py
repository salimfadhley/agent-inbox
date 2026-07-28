"""The command line's own surface.

Only what something else depends on. `--version` is here because the onboarding prompt
tells every arriving agent to run it before installing: if the flag ever stops working,
the check silently becomes "not a command" and every agent reinstalls unconditionally —
harmless the first time, wrong as a diagnosis, and invisible without this test.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from agent_inbox import __version__
from agent_inbox.cli import force_utf8, main
from agent_inbox.client import CONFIG_NAME, ClientError, Config


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
    from agent_inbox.cli import cli

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
    assert "join" in err or CONFIG_NAME in err


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
    (tmp_path / CONFIG_NAME).write_text(
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
    monkeypatch.setattr("agent_inbox.cli.HubClient", FakeHubClient)

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
        assert 'role = "host"' in (tmp_path / CONFIG_NAME).read_text()

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
        (tmp_path / CONFIG_NAME).write_text(body)
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
        before = (tmp_path / CONFIG_NAME).read_text()
        self._shell(tmp_path, monkeypatch)

        assert main(["config", "set", "role", "host"]) == 2

        err = capsys.readouterr().err
        assert "cannot tell which engine" in err
        assert "claude, codex" in err
        assert "--engine claude config" in err
        assert (tmp_path / CONFIG_NAME).read_text() == before

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

        written = (tmp_path / CONFIG_NAME).read_text()
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
        before = (tmp_path / CONFIG_NAME).read_text()
        self._shell(tmp_path, monkeypatch)

        assert main(["config", "set", "--global", "token", "sekrit"]) == 0
        assert main(["config", "list"]) == 0
        assert main(["config", "path"]) == 0

        assert (tmp_path / CONFIG_NAME).read_text() == before

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
        assert 'role = "host"' in (tmp_path / CONFIG_NAME).read_text()

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
        generic "write the config in your project root" — telling someone to
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
        written = (tmp_path / CONFIG_NAME).read_text()
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
        (tmp_path / CONFIG_NAME).write_text('hub = "http://hub.invalid:8081"\n')
        self._shell(tmp_path, monkeypatch)

        class Reachable:
            """Answers as a live hub would, so doctor reaches the advice it gives."""

            def __init__(self, config: Config) -> None:
                self.config = config

            def hub_info(self) -> dict[str, Any]:
                return {"name": "hub", "version": "test", "authenticated": False}

            def remote_doctor(self) -> dict[str, Any]:
                return {"you": {"token": "not presented"}, "verdict": "no token needed"}

        monkeypatch.setattr("agent_inbox.cli.HubClient", Reachable)
        main(["doctor"])
        assert "join --engine <engine>" in capsys.readouterr().out


class TestHubReportsRetentionLiveness:
    """`agent-inbox hub` says whether the hub is expiring old mail.

    Retention was broken for the life of this project and nobody noticed, because
    nobody had a reason to go looking. Printing it beside the version means nobody has
    to have a reason. Raised by ludmila_coe, who pointed out that an agent with a CLI
    had no way to read the status at all.
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch, status: dict[str, Any]) -> str:
        from click.testing import CliRunner

        from agent_inbox import cli as cli_module

        class Fake:
            def __init__(self, config: Any) -> None:
                self.config = config

            def hub_info(self) -> dict[str, Any]:
                return {"name": "hub", "version": "test"}

            def purge_status(self) -> dict[str, Any]:
                if status is None:
                    raise ClientError("no such route")
                return status

        # Patch the client seam itself rather than the config. This test is about what
        # `hub` prints, not about engine resolution — and resolution depends on the
        # environment, so a version that went through it passed on my machine (where
        # CLAUDECODE is set) and failed in CI (where no engine marker exists and this
        # repo configures two).
        monkeypatch.setattr(
            cli_module, "_client", lambda ctx: Fake(Config(hub="h", name="nic"))
        )
        result = CliRunner().invoke(cli_module.cli, ["hub"])
        assert result.exit_code == 0, result.output
        return result.output

    def test_a_completed_check_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = self._run(
            monkeypatch,
            {
                "lastCycle": "2026-07-27T02:25:20+00:00",
                "cycles": 4,
                "lastRemovedObjects": 7,
                "lastError": None,
            },
        )
        assert "retention: last checked 2026-07-27 02:25:20 UTC" in out
        assert "4 checks, 7 removed" in out

    def test_no_check_yet_says_when_that_is_a_fault(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ambiguous on its own — normal just after a restart, a fault if it lasts."""
        out = self._run(
            monkeypatch,
            {
                "lastCycle": None,
                "cycles": 0,
                "lastRemovedObjects": 0,
                "lastError": None,
            },
        )
        assert "no check has completed yet" in out
        assert "a fault if it persists" in out

    def test_an_older_hub_does_not_break_the_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hub without the route is not a reason to fail `hub`."""
        out = self._run(monkeypatch, None)
        assert "retention" not in out
        assert "hub" in out


class TestRetentionCommand:
    """`agent-inbox retention` — the machine-readable form, for monitors.

    Asked for by ludmila_coe, whose use is a host checking retention liveness without a
    curl snippet. `hub` prints a sentence for a human; this prints the object, so a
    monitor can alert on `lastCycle` failing to advance.
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch, status: dict[str, Any]) -> str:
        from click.testing import CliRunner

        from agent_inbox import cli as cli_module

        class Fake:
            def __init__(self, config: Any) -> None:
                self.config = config

            def purge_status(self) -> dict[str, Any]:
                return status

        monkeypatch.setattr(
            cli_module, "_client", lambda ctx: Fake(Config(hub="h", name="nic"))
        )
        result = CliRunner().invoke(cli_module.cli, ["retention"])
        assert result.exit_code == 0, result.output
        return result.output

    def test_it_prints_the_object_not_a_sentence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        status = {
            "lastCycle": "2026-07-27T02:41:04+00:00",
            "cycles": 2,
            "lastRemovedThreads": 0,
            "lastRemovedObjects": 0,
            "lastError": None,
        }
        parsed = json.loads(self._run(monkeypatch, status))
        assert parsed == status, "a monitor could not parse this"

    def test_it_carries_no_mail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The same boundary as the route: liveness is not the same as content."""
        out = self._run(
            monkeypatch,
            {
                "lastCycle": None,
                "cycles": 0,
                "lastRemovedThreads": 0,
                "lastRemovedObjects": 0,
                "lastError": None,
            },
        )
        assert "threads" not in out and "subject" not in out


class TestTheSuiteCannotSeeTheRunningAgent:
    """The guard that makes engine-marker contamination impossible, not merely rare.

    Two red builds in one evening came from tests passing in a Claude Code shell (where
    CLAUDECODE is set, so an engine resolves) and failing in CI (where none is set and
    this project configures two engines, so the CLI correctly refuses to guess).

    `tests/conftest.py` strips the markers for every test. This asserts the guard is
    actually in force, because a fixture that silently stopped working would restore the
    original problem while looking fine.
    """

    def test_no_engine_marker_survives_into_a_test(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        from agent_inbox.client import ENGINE_MARKERS, detect_engine

        present = [m for m, _ in ENGINE_MARKERS if os.environ.get(m)]
        assert not present, (
            f"the running agent's markers reached this test: {present} — "
            "results here will differ between a local shell and CI"
        )
        assert detect_engine() is None

    def test_a_test_can_still_ask_for_an_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stripping must not stop a test setting a marker deliberately."""
        from agent_inbox.client import detect_engine

        monkeypatch.setenv("CODEX_HOME", "/somewhere")
        assert detect_engine() == "codex"


class TestDoctorExitCodes:
    """`doctor` prints `ok` / `--` / `FAIL` — green, amber, red — and the exit code
    must agree with the markers it just showed.

    It did not. The healthy first-run state of every new agent printed nothing but `ok`
    and `--` and then exited 2, so a wake hook or provisioning script could not tell a
    brand-new agent from an unreachable hub. Issue #2.
    """

    class _Hub:
        def __init__(self, config: Config) -> None:
            self.config = config

        def hub_info(self) -> dict[str, Any]:
            return {"name": "hub", "version": "test", "authenticated": False}

        def remote_doctor(self) -> dict[str, Any]:
            return {"you": {"token": "not needed"}, "verdict": "fine"}

        def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
            return {"items": []}

        def ping(self) -> dict[str, Any]:
            return {"you": "rosemary_nasrin"}

    def _patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("agent_inbox.cli.HubClient", self._Hub)
        for var in (
            "AGENT_MAILBOX_HUB",
            "AGENT_MAILBOX_NAME",
            "AGENT_INBOX_HUB",
            "AGENT_INBOX_NAME",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_healthy_but_not_joined_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The whole mission. Nothing failed, so nothing should be reported as failure.

        This is the state every new install passes through, and `doctor` is the first
        command the onboarding prompt tells an agent to run.
        """
        monkeypatch.chdir(tmp_path)
        self._patch(monkeypatch)
        code = main(["doctor", "--hub", "http://hub:8081"])
        out = capsys.readouterr()
        assert "FAIL" not in out.out + out.err, "precondition: nothing actually failed"
        assert code == 0, "a run with no FAIL line must not report failure"

    def test_no_hub_url_still_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A genuine blocker keeps its code. This mission changes one case, not four."""
        monkeypatch.chdir(tmp_path)
        self._patch(monkeypatch)
        assert main(["doctor"]) == 2

    def test_an_ambiguous_engine_still_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n'
            '[agents.claude]\nname = "rosemary_nasrin"\n\n'
            '[agents.codex]\nname = "trevor_mahmood"\n'
        )
        monkeypatch.chdir(tmp_path)
        self._patch(monkeypatch)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert main(["doctor"]) == 2

    def test_a_duplicate_name_clash_is_never_silenced(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """NFR-002, and the trap this fix could have walked into.

        The `unique names` check reports FAIL and *keeps walking* — deliberately, since
        the engine running now may be fine while another has its mail eaten. So a naive
        "the not-joined case returns 0" would exit 0 with a FAIL on screen, silencing a
        real fault. Widening success is exactly how a fix becomes the opposite defect.
        """
        # The current engine (claude) has NO entry, so this reaches the not-joined
        # return — while two *other* engines clash. An earlier version of this test put
        # claude in the file, which took the joined path instead and never exercised the
        # line under test: it passed against the naive fix, proving nothing.
        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n'
            '[agents.codex]\nname = "same_name"\n\n'
            '[agents.gemini]\nname = "same_name"\n'
        )
        monkeypatch.chdir(tmp_path)
        self._patch(monkeypatch)
        monkeypatch.setenv("CLAUDECODE", "1")
        code = main(["doctor"])
        out = capsys.readouterr()
        assert "FAIL" in out.out + out.err, "precondition: the clash must be reported"
        assert code != 0, "a FAIL on screen must never exit 0"

    def test_the_help_explains_the_markers_and_the_codes(self) -> None:
        """FR-007. `--` is explained nowhere today, so a reader must infer it is not a
        failure — the same inference the exit code got wrong."""
        from click.testing import CliRunner

        from agent_inbox.cli import cli

        text = CliRunner().invoke(cli, ["doctor", "--help"]).output
        for marker in ("ok", "--", "FAIL"):
            assert marker in text, f"help does not explain the {marker!r} marker"
        assert "exit" in text.lower(), "help does not state the exit-code meaning"
        assert "0" in text and "non-zero" in text.lower()


class TestOutputIsAlwaysUtf8:
    """CLI text uses em-dashes; Git Bash encodes them as cp1252 and corrupts them.

    Issue #3. On a stream whose encoding came from the locale rather than UTF-8,
    Python writes U+2014 as the single byte 0x97 instead of `e2 80 94`, and every
    UTF-8 consumer downstream — cat, grep, log files, CI viewers — shows mojibake.

    It does not stay on the terminal. This project routes CLI output into session logs,
    CI artifacts and mail bodies quoting commands, so a corrupted character outlives the
    terminal that produced it and is unreadable to every later reader, agents included.

    Tested without Windows by building a cp1252 stream directly, because CI has none.
    """

    def _cp1252_stream(self) -> tuple[io.BytesIO, io.TextIOWrapper]:
        raw = io.BytesIO()
        return raw, io.TextIOWrapper(raw, encoding="cp1252", newline="")

    def test_a_cp1252_stream_would_corrupt_an_em_dash(self) -> None:
        """The premise. Without this, the fix below would be asserting nothing."""
        raw, stream = self._cp1252_stream()
        stream.write("—")
        stream.flush()
        assert raw.getvalue() == b"\x97", "precondition: cp1252 mangles U+2014"

    def test_force_utf8_makes_it_emit_utf8(self) -> None:
        raw, stream = self._cp1252_stream()
        force_utf8(stream)
        stream.write("—")
        stream.flush()
        assert raw.getvalue() == "—".encode(), "expected e2 80 94"

    def test_a_stream_already_utf8_is_left_alone(self) -> None:
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        force_utf8(stream)
        stream.write("—")
        stream.flush()
        assert raw.getvalue() == "—".encode()

    def test_a_stream_that_cannot_be_reconfigured_is_survived(self) -> None:
        """Never break the CLI over its own output encoding.

        Anything may be standing in for stdout — a pytest capture, a pipe wrapper, a
        harness. If it cannot be reconfigured, that is not a reason to fail a command
        the user actually asked for.
        """

        class Stubborn(io.StringIO):
            def reconfigure(self, **kw: object) -> None:
                raise OSError("not reconfigurable")

        force_utf8(Stubborn())  # must not raise

    def test_an_object_without_reconfigure_is_survived(self) -> None:
        class Bare:
            def write(self, text: str) -> int:
                return len(text)

        force_utf8(Bare())  # must not raise


class TestProfileFromTheCli:
    """The hub tells every agent to describe itself; only MCP could do it. Issue #4.

    Read and write are one package here, not a command and a nice-to-have: the write
    REPLACES the whole profile, so a caller who cannot see the current value is being
    asked to overwrite something they cannot read. `show` is what makes `set` safe.
    """

    class _Hub:
        stored: dict[str, Any] = {}

        def __init__(self, config: Config) -> None:
            self.config = config

        def update_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
            type(self).stored = dict(profile)
            return {"preferredUsername": self.config.name, "profile": dict(profile)}

        def whois(self, name: str) -> dict[str, Any]:
            return {"preferredUsername": name, "profile": dict(type(self).stored)}

    def _joined(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\nname = "rosemary_nasrin"\n'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setattr("agent_inbox.cli.HubClient", self._Hub)
        self._Hub.stored = {}

    def test_a_profile_can_be_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._joined(tmp_path, monkeypatch)
        assert main(["profile", "set", '{"project": "billing"}']) == 0
        assert self._Hub.stored == {"project": "billing"}

    def test_a_profile_can_be_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._joined(tmp_path, monkeypatch)
        main(["profile", "set", '{"project": "billing"}'])
        capsys.readouterr()
        assert main(["profile", "show"]) == 0
        assert "billing" in capsys.readouterr().out

    def test_show_output_is_valid_input_to_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FR-008. Otherwise `show` then edit then `set` is a retyping exercise."""
        self._joined(tmp_path, monkeypatch)
        original = {"project": "billing", "offers": ["python", "sql"]}
        main(["profile", "set", json.dumps(original)])
        capsys.readouterr()
        main(["profile", "show"])
        shown = capsys.readouterr().out
        assert main(["profile", "set", shown]) == 0
        assert self._Hub.stored == original, "a round trip must not alter the profile"

    def test_setting_replaces_rather_than_merges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identical to MCP. Two surfaces of one API must not disagree about this."""
        self._joined(tmp_path, monkeypatch)
        main(["profile", "set", '{"project": "billing", "engine": "claude"}'])
        main(["profile", "set", '{"project": "payments"}'])
        assert self._Hub.stored == {"project": "payments"}, "omitted fields must go"

    def test_malformed_json_is_named_not_a_traceback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._joined(tmp_path, monkeypatch)
        assert main(["profile", "set", "{not json"]) != 0
        err = capsys.readouterr().err
        assert "JSON" in err or "json" in err
        assert "Traceback" not in err

    def test_a_non_object_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A profile is a mapping. A list parses as JSON and is still wrong."""
        self._joined(tmp_path, monkeypatch)
        for bad in ('["a", "b"]', '"a string"', "42"):
            assert main(["profile", "set", bad]) != 0, f"{bad} should be refused"

    def test_an_empty_object_clears_the_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legitimate: replace semantics means {} is how you say 'nothing'."""
        self._joined(tmp_path, monkeypatch)
        main(["profile", "set", '{"project": "billing"}'])
        assert main(["profile", "set", "{}"]) == 0
        assert self._Hub.stored == {}

    def test_update_profile_is_an_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-009, ludmila_coe's suggestion. It catches the agent reading
        `update_profile` in MCP-oriented text and translating it literally at a shell —
        which is exactly the agent this issue is about."""
        self._joined(tmp_path, monkeypatch)
        assert main(["update-profile", '{"project": "billing"}']) == 0
        assert self._Hub.stored == {"project": "billing"}

    def test_the_help_says_it_replaces(self) -> None:
        """A caller who assumes merge loses fields silently, so the help must say so."""
        from click.testing import CliRunner

        from agent_inbox.cli import cli

        text = CliRunner().invoke(cli, ["profile", "set", "--help"]).output
        assert "replace" in text.lower()
