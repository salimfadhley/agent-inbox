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
    # parser would stop being true at the next release without anything failing.
    assert out.strip() == f"agent-mailbox {__version__}"


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
