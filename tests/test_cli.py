"""The command line's own surface.

Only what something else depends on. `--version` is here because the onboarding prompt
tells every arriving agent to run it before installing: if the flag ever stops working,
the check silently becomes "not a command" and every agent reinstalls unconditionally —
harmless the first time, wrong as a diagnosis, and invisible without this test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_mailbox import __version__
from agent_mailbox.cli import main


def test_version_is_asked_for_without_a_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reader runs it before they have any idea what the subcommands are.

    Subcommands are `required=True`, so this pins that `--version` still answers
    without one — the whole point being that a copy too old to know today's
    subcommands can still say how old it is.
    """
    with pytest.raises(SystemExit) as exit_:
        main(["--version"])
    assert exit_.value.code == 0
    out = capsys.readouterr().out
    # Compared against the package version, not a literal: a number typed into the
    # parser would stop being true at the next release without anything failing. The
    # program name is whichever of the two commands was invoked, so only the version
    # itself is pinned here.
    assert out.strip().endswith(__version__)
    assert out.split()[0] in {"agent-mailbox", "agent-inbox", "pytest"}


def test_doctor_is_a_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """The onboarding prompt tells every arriving agent to run it.

    Only that it exists and is wired up — what it reports needs a hub, which the live
    smoke tests have and this file does not.
    """
    from agent_mailbox.cli import build_parser

    args = build_parser().parse_args(["doctor"])
    assert args.func.__name__ == "cmd_doctor"


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


class TestConfigure:
    """The tool owns its configuration; nobody should be editing these files."""

    def _run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("AGENT_MAILBOX_HUB", raising=False)
        monkeypatch.delenv("AGENT_MAILBOX_NAME", raising=False)
        monkeypatch.chdir(tmp_path)
        return main(["configure", *args])

    def test_a_shared_token_goes_machine_wide_and_stays_private(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A credential admits the machine, so it is written once — and 0600.

        The default umask would leave it world-readable, which for a token that admits
        every agent on the box is the whole security of the thing.
        """
        assert self._run(tmp_path, monkeypatch, "--global", "token=sekrit") == 0
        written = tmp_path / "xdg" / "agent-inbox" / "config.toml"
        assert 'token = "sekrit"' in written.read_text()
        assert written.stat().st_mode & 0o077 == 0, "readable by others"

    def test_set_may_lead_and_is_optional(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`configure set role=host` reads naturally; insisting on it would trap
        anyone who wrote the shorter form, and vice versa."""
        assert self._run(tmp_path, monkeypatch, "set", "role=host") == 0
        assert 'role = "host"' in (tmp_path / "agent-mailbox.toml").read_text()

    def test_identity_is_refused_machine_wide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same engine in two repositories is two correspondents.

        A machine-wide name would quietly merge them into one inbox — the exact
        failure hub-issued names exist to prevent.
        """
        assert self._run(tmp_path, monkeypatch, "--global", "name=someone") == 2

    def test_an_unknown_setting_is_refused_rather_than_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A silently accepted typo leaves a file that reads correct and is not."""
        assert self._run(tmp_path, monkeypatch, "tokne=sekrit") == 2
