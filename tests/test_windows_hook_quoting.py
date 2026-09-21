"""The generated hook command must be valid for the shell that runs it (#71).

Reported 2026-09-21 from a live Codex session on Windows: `Hook failed`, exit code 1,
before Python ever started. `default_command` quoted the interpreter path with
`shlex.quote` — single quotes, POSIX — and Codex on Windows hands a hook to
`cmd.exe /C` (`COMSPEC`; `hooks/src/engine/command_runner.rs`, `default_shell_command`),
where a single quote is an ordinary character. The mailbox send had succeeded; the
recipient's hook then looked for a program named `'C:\\...\\python.exe'`.

Two kinds of test here, because string assertions alone were what let this ship: the
quoting rules per platform, and an **actual launch** of the rendered command through
`sh -lc`, the way Codex runs it on this platform.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_inbox import hookconfig
from agent_inbox.hookconfig import quote_for_shell, split_command

WIN_BARE = r"C:\Users\someone\AppData\Roaming\uv\tools\agent-inbox\Scripts\python.exe"
WIN_SPACED = (
    r"C:\Users\some one\AppData\Roaming\uv\tools\agent-inbox\Scripts\python.exe"
)


class TestWindowsQuoting:
    def test_an_ordinary_path_goes_bare(self) -> None:
        """The one form cmd.exe, PowerShell and a bash on Windows all accept."""
        assert quote_for_shell(WIN_BARE, windows=True) == WIN_BARE

    def test_a_path_with_a_space_gets_double_quotes(self) -> None:
        assert quote_for_shell(WIN_SPACED, windows=True) == f'"{WIN_SPACED}"'

    def test_never_single_quotes_on_windows(self) -> None:
        """The bug, stated."""
        for path in (WIN_BARE, WIN_SPACED, r"C:\odd&name\python.exe"):
            assert "'" not in quote_for_shell(path, windows=True)

    def test_posix_keeps_shlex(self) -> None:
        assert quote_for_shell("/opt/Program Files/py/python", windows=False) == (
            "'/opt/Program Files/py/python'"
        )


class TestSplittingRoundTrips:
    """omp is handed argv, not a string, so the split must undo the quoting exactly."""

    @pytest.mark.parametrize("path", [WIN_BARE, WIN_SPACED])
    def test_windows_split_recovers_the_path_with_backslashes(self, path: str) -> None:
        command = f"{quote_for_shell(path, windows=True)} -m agent_inbox wake-check"

        assert split_command(command, windows=True) == [
            path,
            "-m",
            "agent_inbox",
            "wake-check",
        ]

    def test_posix_split_of_a_windows_path_would_have_eaten_the_backslashes(
        self,
    ) -> None:
        """Why the split is platform-aware and not merely shlex."""
        assert split_command(f"{WIN_BARE} -m x", windows=False)[0] != WIN_BARE

    def test_posix_split_still_handles_spaces(self) -> None:
        assert split_command("'/a dir/python' -m agent_inbox", windows=False)[0] == (
            "/a dir/python"
        )


class TestTheRenderedCommandOnThisPlatform:
    def test_all_three_codex_hooks_share_the_prefix(self, tmp_path: Path) -> None:
        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())
        prefix = quote_for_shell(sys.executable) + " -m agent_inbox wake-check"

        for event in ("SessionStart", "UserPromptSubmit", "Stop"):
            assert data["hooks"][event][0]["hooks"][0]["command"].startswith(prefix)

    def test_the_windows_form_is_what_the_report_asked_for(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Render as Windows would, from the reported path: no single quotes, and the
        command line the report pasted comes out runnable under cmd.exe."""
        monkeypatch.setattr(hookconfig.os, "name", "nt")
        monkeypatch.setattr(hookconfig.sys, "executable", WIN_BARE)

        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())
        stop = data["hooks"]["Stop"][0]["hooks"][0]["command"]

        assert stop.startswith(WIN_BARE + " -m agent_inbox wake-check --event Stop")
        assert "'" not in stop


@pytest.mark.skipif(os.name == "nt", reason="the POSIX launch path")
class TestAnActualLaunch:
    """Run the rendered command the way Codex does here: `$SHELL -lc <command>` — or
    `/bin/sh -lc`, the fallback — and require a clean exit. A string that parses is
    not a hook that runs; this is the test the Windows report said was missing."""

    def test_the_real_stop_hook_launches_and_exits_zero(self, tmp_path: Path) -> None:
        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())
        command = data["hooks"]["Stop"][0]["hooks"][0]["command"]

        done = subprocess.run(  # noqa: S603
            ["/bin/sh", "-lc", command],  # noqa: S607
            cwd=tmp_path,  # unconfigured project: wake-check is silent and exits 0
            capture_output=True,
            text=True,
            timeout=60,
            input="{}",  # the harness's JSON on stdin, which the hook drains
        )

        assert done.returncode == 0, done.stderr
        assert done.stdout == "" and done.stderr == ""

    def test_a_spaced_interpreter_path_reaches_the_program_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fake interpreter in a directory with a space records the argv it was
        given; the shell must deliver the path as one argument."""
        fake_dir = tmp_path / "a dir"
        fake_dir.mkdir()
        fake = fake_dir / "python"
        record = tmp_path / "argv.txt"
        fake.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$0" "$@" > "{record}"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setattr(hookconfig.sys, "executable", str(fake))

        data = json.loads(hookconfig.install_for("codex", tmp_path).read_text())
        command = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        subprocess.run(
            ["/bin/sh", "-lc", command], cwd=tmp_path, check=True, timeout=30
        )  # noqa: S603, S607

        assert record.read_text().splitlines() == [
            str(fake),
            "-m",
            "agent_inbox",
            "wake-check",
            "--event",
            "SessionStart",
        ]
