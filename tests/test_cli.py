"""The command line's own surface.

Only what something else depends on. `--version` is here because the onboarding prompt
tells every arriving agent to run it before installing: if the flag ever stops working,
the check silently becomes "not a command" and every agent reinstalls unconditionally —
harmless the first time, wrong as a diagnosis, and invisible without this test.
"""

from __future__ import annotations

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
