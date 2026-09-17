"""Waking, for Codex (issue #71).

Codex has Claude Code's lifecycle hooks, on by default, and its Stop hook takes exit 2
with a continuation prompt exactly as Claude Code does — so this is a third renderer of
the same three hooks, into `<project>/.codex/hooks.json`. Two things are Codex's own and
shape everything here:

**Trust.** Codex runs only hooks a person has approved in its `/hooks` screen, by a hash
of the hook's identity. So "waking installed" would be a false success, and a reinstall
that rendered anything differently would un-trust the hook silently.

**Synchrony.** Codex's Stop hook blocks the turn while it runs — only a synchronous hook
may continue the turn — so the held waiter is bounded and told not to re-arm.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_inbox import hookconfig, ignores
from agent_inbox.cli import main


class TestCodexGetsHooks:
    def test_they_land_in_codexs_project_hook_file(self, tmp_path: Path) -> None:
        path = hookconfig.install_for("codex", tmp_path)

        assert path == tmp_path / ".codex" / "hooks.json"
        data = json.loads(path.read_text())
        assert set(data["hooks"]) == {"SessionStart", "UserPromptSubmit", "Stop"}

    def test_the_shape_is_codexs(self, tmp_path: Path) -> None:
        """`hooks` → event → groups → `hooks` list of `{type, command, timeout,
        statusMessage}` — read from `core/tests/suite/hooks.rs`."""
        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())

        stop = data["hooks"]["Stop"][0]["hooks"][0]
        assert stop["type"] == "command"
        assert "wake-check --event Stop" in stop["command"]
        assert isinstance(stop["timeout"], int)
        assert stop["statusMessage"]

    def test_it_merges_with_hooks_that_are_not_ours(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir()
        theirs = {"type": "command", "command": "lint --fix", "timeout": 5}
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [theirs]}]}}))

        hookconfig.install_for("codex", tmp_path)

        data = json.loads(path.read_text())
        commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        assert "lint --fix" in commands
        assert any("wake-check" in c for c in commands)

    def test_the_default_stop_hook_is_a_quick_check(self, tmp_path: Path) -> None:
        """Without --rewake the Stop hook looks once and returns, as on Claude Code:
        a synchronous hook that held would block the prompt."""
        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())
        stop = data["hooks"]["Stop"][0]["hooks"][0]

        assert "--wait" not in stop["command"]
        assert stop["timeout"] == hookconfig._TIMEOUT

    def test_rewake_holds_bounded_and_does_not_rearm(self, tmp_path: Path) -> None:
        """Codex's Stop hook is synchronous. An eight-hour hold would freeze the
        prompt; a re-arm would spend a model turn every window on an idle session."""
        data = json.loads(
            hookconfig.install_for("codex", tmp_path, rewake=True).read_text()
        )
        stop = data["hooks"]["Stop"][0]["hooks"][0]

        assert "--wait" in stop["command"]
        assert "--no-rearm" in stop["command"]
        assert stop["timeout"] == hookconfig.CODEX_HOLD_SECONDS
        assert f"--wait-timeout {hookconfig.CODEX_HOLD_SECONDS - 30}" in stop["command"]
        assert "async" not in stop  # an async hook cannot continue the turn


class TestTrustSurvivesReinstall:
    """Codex trusts a hook by a hash of event, command and timeout, recorded when a
    person approves it. Anything that changes the bytes changes the hash."""

    def test_reinstall_is_byte_identical(self, tmp_path: Path) -> None:
        path = hookconfig.install_for("codex", tmp_path)
        first = path.read_bytes()

        hookconfig.install_for("codex", tmp_path)

        assert path.read_bytes() == first

    def test_reinstall_over_foreign_hooks_is_byte_identical_too(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [{"hooks": [{"type": "command", "command": "x"}]}]
                    }
                }
            )
        )
        hookconfig.install_for("codex", tmp_path)
        first = path.read_bytes()

        hookconfig.install_for("codex", tmp_path)

        assert path.read_bytes() == first

    def test_uninstall_removes_only_ours(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [{"hooks": [{"type": "command", "command": "lint"}]}]
                    }
                }
            )
        )
        hookconfig.install_for("codex", tmp_path)

        hookconfig.uninstall_codex(tmp_path)

        data = json.loads(path.read_text())
        commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        assert commands == ["lint"]


class TestInstallHookSaysWrittenNotRunning:
    def _project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

    def test_the_trust_step_is_stated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """**The false success this must never print.** On Codex a written hook is
        not a running hook; the line every other harness gets would be untrue."""
        self._project(tmp_path, monkeypatch)

        assert main(["install-hook", "--engine", "codex"]) == 0

        out = capsys.readouterr().out
        assert "not yet running" in out
        assert "/hooks" in out and "trust" in out
        assert "waking installed" not in out

    def test_rewake_explains_the_hold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._project(tmp_path, monkeypatch)

        assert main(["install-hook", "--engine", "codex", "--rewake"]) == 0

        out = capsys.readouterr().out
        assert "10 minutes" in out and "Esc" in out


class TestTheFileIsKeptOutOfGit:
    def test_the_installer_adds_the_narrow_rule(self, tmp_path: Path) -> None:
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # noqa: S603, S607
        hookconfig.install_for("codex", tmp_path)

        assert "/.codex/hooks.json" in (tmp_path / ".gitignore").read_text()

    def test_doctors_hook_check_recognises_the_merged_file_as_ours(
        self, tmp_path: Path
    ) -> None:
        """Unlike the plugin and extension files, `hooks.json` has no marker on its
        first line — it is Codex's file with our entries in it."""
        path = hookconfig.install_for("codex", tmp_path)

        assert ignores.is_our_hook(path)
        assert ".codex/hooks.json" in ignores.HOOK_FILES

    def test_a_hooks_json_without_our_entries_is_not_ours(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [{"hooks": [{"type": "command", "command": "lint"}]}]
                    }
                }
            )
        )

        assert not ignores.is_our_hook(path)


class TestTheWaiterCanBeToldNotToRearm:
    def test_no_rearm_ends_the_hold_quietly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """A re-arm is a turn. On a synchronous Stop hook, an idle session must not
        spend one every window."""
        from agent_inbox import wake

        monkeypatch.setattr(wake, "_fetch_unread", lambda root, engine=None: [])
        monkeypatch.setattr(wake, "_stream_for", lambda root, engine=None: None)
        clock = {"t": 0.0}
        monkeypatch.setattr(wake.time, "monotonic", lambda: clock["t"])

        def sleep(seconds: float) -> None:
            clock["t"] += seconds

        code = wake.run(
            "Stop",
            root=tmp_path,
            wait=True,
            poll_interval=1,
            wait_timeout=3,
            sleep=sleep,
            rearm=False,
        )

        assert code == 0
        assert capsys.readouterr().err == ""

    def test_the_flag_reaches_the_waiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from click.testing import CliRunner

        from agent_inbox import cli as cli_module
        from agent_inbox import wake

        seen: dict[str, Any] = {}
        monkeypatch.setattr(wake, "run", lambda event, **kw: seen.update(kw) or 0)

        CliRunner().invoke(
            cli_module.cli, ["wake-check", "--event", "Stop", "--no-rearm"]
        )

        assert seen.get("rearm") is False


class TestTheNoticeIsNeverAMessageBody:
    """On Codex the notice becomes a continuation prompt — the model's own next input.
    A body there would be an instruction from whoever wrote the mail (ADR 0008)."""

    def test_the_hook_runs_our_waiter_and_composes_nothing(
        self, tmp_path: Path
    ) -> None:
        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())
        commands = [
            h["command"]
            for event in data["hooks"].values()
            for g in event
            for h in g["hooks"]
        ]

        assert all("wake-check" in c for c in commands)

    def test_the_waiter_it_calls_never_emits_a_body(self) -> None:
        from agent_inbox.wake import _notice

        notice = _notice(
            [
                {
                    "id": "u/1",
                    "attributedTo": "u/pablo_fantomas",
                    "summary": "a subject",
                    "content": "SECRET BODY THAT MUST NOT TRAVEL",
                }
            ]
        )

        assert "pablo_fantomas" in notice and "a subject" in notice
        assert "SECRET BODY" not in notice


class TestTheOtherHarnessesAreUnaffected:
    def test_claude_opencode_and_omp_still_write_their_own_files(
        self, tmp_path: Path
    ) -> None:
        hookconfig.install_for("claude", tmp_path)
        hookconfig.install_for("opencode", tmp_path)
        hookconfig.install_for("omp", tmp_path)

        assert not hookconfig.codex_hooks_path(tmp_path).exists()

    def test_an_unknown_harness_is_still_refused(self, tmp_path: Path) -> None:
        with pytest.raises(hookconfig.NoWakingHere):
            hookconfig.install_for("some-future-harness", tmp_path)
