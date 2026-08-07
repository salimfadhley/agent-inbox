"""Migrating the config filename on write, and saying so (issue #12).

v0.24.0 renamed the project file to `agent-inbox.toml` and kept reading the old
`agent-mailbox.toml`. Nothing broke and nothing moved, which is the right trade for a
release and the wrong one forever — every project that existed then is still on the old
name, and reading both names indefinitely is a cost that only grows.

The dangerous half is not the rename. It is that a project's `.gitignore` may name the
**old** file, so a silent rename turns an ignored identity file into a committable one
holding a hub address and possibly a device token — quietly undoing a protection the
project already had. `parisa_murthy` demonstrated exactly that failure by watching
`git add -A` stage the file.

So most of this module is about the cases where nothing should move, and about proving
the ignore rule follows the file.
"""

import subprocess
from pathlib import Path

import pytest

from agent_inbox.client import (
    CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    find_config,
    load_config,
    take_migration_notice,
    unset_project,
    write_project,
)

LEGACY_BODY = 'hub = "http://hub:8081"\n\n[agents.claude]\nname = "igor_laszlo"\n'


@pytest.fixture(autouse=True)
def _no_leftover_notice() -> None:
    """Each test starts with the hand-off empty, so no test can inherit another's
    notice and pass on it."""
    take_migration_notice()


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.invalid"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    return tmp_path


class TestALegacyFileMovesOnWrite:
    def test_the_file_is_renamed(self, tmp_path: Path) -> None:
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        write_project({"role": "agent"}, start=tmp_path, engine="claude")

        assert (tmp_path / CONFIG_NAME).is_file()
        assert not (tmp_path / LEGACY_CONFIG_NAME).exists()

    def test_the_agent_that_was_working_keeps_working(self, tmp_path: Path) -> None:
        """The acceptance criterion that matters most: same hub, same name, same engine
        entry. A migration that loses an identity is worse than no migration, because
        names here are permanent and cannot be reclaimed."""
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        write_project({"role": "agent"}, start=tmp_path, engine="claude")
        config = load_config(start=tmp_path, env={"CLAUDECODE": "1"})

        assert config.hub == "http://hub:8081"
        assert config.name == "igor_laszlo"

    def test_it_says_so(self, tmp_path: Path) -> None:
        """Silence is the failure mode. The rename is not what the caller asked for."""
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        write_project({"role": "agent"}, start=tmp_path, engine="claude")

        said = take_migration_notice()
        assert LEGACY_CONFIG_NAME in said and CONFIG_NAME in said

    def test_the_notice_is_reported_once(self, tmp_path: Path) -> None:
        """Reading clears it, so a later unrelated command cannot re-announce a rename
        that happened an hour ago and confuse somebody into looking for it."""
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)
        write_project({"role": "agent"}, start=tmp_path, engine="claude")

        assert take_migration_notice()
        assert take_migration_notice() == ""

    def test_unset_migrates_too(self, tmp_path: Path) -> None:
        """`config unset` rewrites the file, so it is a write like any other. Listing
        the writers by hand is how one of them gets forgotten — this passes because the
        migration sits in the single renderer they all reach."""
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        assert unset_project("name", start=tmp_path, engine="claude")

        assert (tmp_path / CONFIG_NAME).is_file()
        assert not (tmp_path / LEGACY_CONFIG_NAME).exists()


class TestTheIgnoreRuleFollowsTheFile:
    def test_a_rule_naming_the_old_file_is_replaced(self, tmp_path: Path) -> None:
        """`parisa_murthy`'s case, exactly: a `.gitignore` correctly commented and one
        word out of date. Renaming without fixing it would leave the identity file
        committable — the protection undone by the very act of tidying up."""
        root = _repo(tmp_path)
        (root / ".gitignore").write_text(f"# never commit\n{LEGACY_CONFIG_NAME}\n")
        (root / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        write_project({"role": "agent"}, start=root, engine="claude")

        ignored = subprocess.run(
            ["git", "check-ignore", CONFIG_NAME], cwd=root, capture_output=True
        )
        assert ignored.returncode == 0, "the renamed file is committable"

    def test_an_already_correct_rule_is_left_alone(self, tmp_path: Path) -> None:
        """The paired positive. Appending a duplicate line every time somebody set a
        config value would be its own small mess."""
        root = _repo(tmp_path)
        (root / ".gitignore").write_text(f"{CONFIG_NAME}\n")
        (root / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        write_project({"role": "agent"}, start=root, engine="claude")

        assert (root / ".gitignore").read_text().count(CONFIG_NAME) == 1


class TestTheCasesThatMustNotMove:
    def test_a_tracked_legacy_file_is_not_renamed(self, tmp_path: Path) -> None:
        """`agent-mailbox.toml` was tracked in this very repository until 02e5d12. A
        plain rename reads to git as the agent's identity being deleted, with an
        invisible ignored replacement — so it is reported and left where it is."""
        root = _repo(tmp_path)
        (root / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)
        subprocess.run(["git", "add", LEGACY_CONFIG_NAME], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "identity"], cwd=root, check=True)

        write_project({"role": "agent"}, start=root, engine="claude")

        assert (root / LEGACY_CONFIG_NAME).is_file(), "a tracked file was moved"
        assert not (root / CONFIG_NAME).exists()
        said = take_migration_notice()
        assert "git mv" in said, "refusing without saying what to do instead"

    def test_both_present_leaves_the_older_one_alone(self, tmp_path: Path) -> None:
        """`find_config` prefers the current name, so this is a half-finished migration
        rather than a design. Two identity files in one project is a state a human
        should hear about, not have tidied away underneath them."""
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)
        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\nname = "parisa_murthy"\n'
        )

        write_project({"role": "agent"}, start=tmp_path, engine="claude")

        assert (tmp_path / LEGACY_CONFIG_NAME).is_file()
        assert "parisa_murthy" in (tmp_path / CONFIG_NAME).read_text(), "clobbered"
        assert LEGACY_CONFIG_NAME in take_migration_notice()

    def test_an_ordinary_write_says_nothing(self, tmp_path: Path) -> None:
        """The paired positive for the whole file. A migration that announced itself on
        every write would be furniture, and there is no legacy file here to move."""
        (tmp_path / CONFIG_NAME).write_text(LEGACY_BODY)

        write_project({"role": "agent"}, start=tmp_path, engine="claude")

        assert take_migration_notice() == ""


class TestReadingMigratesNothing:
    """A diagnostic that mutates what it is diagnosing is a trap, and `doctor` above all
    — it is run precisely to understand a broken state, which renaming changes."""

    def test_finding_the_config_does_not_move_it(self, tmp_path: Path) -> None:
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        found = find_config(tmp_path)

        assert found is not None and found.name == LEGACY_CONFIG_NAME
        assert (tmp_path / LEGACY_CONFIG_NAME).is_file()
        assert not (tmp_path / CONFIG_NAME).exists()

    def test_loading_the_config_does_not_move_it(self, tmp_path: Path) -> None:
        (tmp_path / LEGACY_CONFIG_NAME).write_text(LEGACY_BODY)

        load_config(start=tmp_path, env={"CLAUDECODE": "1"})

        assert (tmp_path / LEGACY_CONFIG_NAME).is_file()
        assert take_migration_notice() == ""
