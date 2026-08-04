"""A background write must not outrank a human.

`write_config` records the hub machine-wide when a project does not pin one, which is
correct and is the whole point of the machine-wide file. What it must **not** do is
*change* a value already there.

Observed 2026-08-04: a correct hub was set by hand three times and reverted three times
to an address that did not resolve, because a long-lived process still holding the old
value called `join` in the background and won each time. Mail then failed in a different
project, minutes later, with nothing connecting the two.

An empty project hub is not the fault, despite how it looks: it is what this module
writes when the hub lives machine-wide, so every well-behaved project has one.
"""

import logging
from pathlib import Path

import pytest

from agent_inbox.client import load_global, write_config, write_global

GOOD = "https://good.invalid"
STALE = "http://stale.invalid:8080"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.setenv("CLAUDECODE", "1")
    return project


def test_it_records_the_hub_when_there_is_none(home: Path) -> None:
    """The paired positive: a guard that never wrote would otherwise pass every test."""
    write_config(GOOD, "rosemary_nasrin", engine="claude", start=home)

    assert load_global()["hub"] == GOOD


def test_it_does_not_change_a_hub_that_is_already_set(home: Path) -> None:
    """The bug, exactly: a stale background join must not win over a deliberate set."""
    write_global({"hub": GOOD})

    write_config(STALE, "rosemary_nasrin", engine="claude", start=home)

    assert load_global()["hub"] == GOOD, (
        "a background write overwrote the operator's hub"
    )


def test_writing_the_same_hub_again_is_fine(home: Path) -> None:
    """Idempotence: the common case must not warn or refuse."""
    write_global({"hub": GOOD})

    write_config(GOOD, "rosemary_nasrin", engine="claude", start=home)

    assert load_global()["hub"] == GOOD


def test_it_says_so_rather_than_declining_in_silence(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A refusal nobody can see is its own kind of silent failure.

    This took three hand-fixes to diagnose precisely because nothing said anything. The
    log line must name both values, or it does not answer the question it exists for.
    """
    write_global({"hub": GOOD})

    with caplog.at_level(logging.WARNING, logger="agent_inbox.client"):
        write_config(STALE, "rosemary_nasrin", engine="claude", start=home)

    assert GOOD in caplog.text
    assert STALE in caplog.text


def test_a_token_still_pins_the_hub_to_the_project(home: Path) -> None:
    """Unchanged behaviour, asserted so this fix cannot quietly undo it.

    A credential keeps its hub beside it: otherwise the engine loads a new hub with an
    old hub's key, and the refusal points at the one thing that is not wrong.
    """
    write_config(GOOD, "rosemary_nasrin", engine="claude", start=home, token="secret")

    assert "hub" not in load_global()
    assert GOOD in (home / "agent-inbox.toml").read_text()
