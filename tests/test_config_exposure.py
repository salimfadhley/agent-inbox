"""Is the identity file exposed to git? Asked every `doctor` run.

Owner's request, 2026-08-05. `join` adds an ignore rule, but that helps one project at
one moment. A file may predate the rule, sit in a directory it does not reach, or have
been committed before anybody thought about it — and `parisa_murthy` and `igor_laszlo`
each found a repository whose `.gitignore` named the *pre-rename* file, correctly
commented and one word out of date, so it read as protected and was not.

**These tests use real git repositories.** A stubbed `_git` would test the branching
and not the question, and the question is the whole feature: whether git agrees. The
module's own docstring makes the same point about parsing `.gitignore` — a second,
worse implementation of something git answers exactly.
"""

import subprocess
from pathlib import Path

import pytest

from agent_inbox import ignores

CONFIG = "agent-inbox.toml"
BODY = 'hub = "http://hub.invalid:8081"\n\n[agents.claude]\nname = "jed_smith"\n'


def git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "readme.md").write_text("hello\n")
    git(tmp_path, "add", "readme.md")
    git(tmp_path, "commit", "-qm", "first")
    return tmp_path


class TestTheThreeStatesAreDistinguished:
    """Staged, tracked and unignored need different actions. Collapsing them into "a
    problem" leaves the reader to work out which — which is the work the check exists
    to do for them."""

    def test_an_unignored_file_is_reported(self, repo: Path) -> None:
        (repo / CONFIG).write_text(BODY)

        assert ignores.exposed_configs(repo) == [(repo / CONFIG, "unignored")]

    def test_a_staged_file_is_reported_as_staged(self, repo: Path) -> None:
        (repo / CONFIG).write_text(BODY)
        git(repo, "add", "-f", CONFIG)

        assert ignores.exposed_configs(repo) == [(repo / CONFIG, "staged")]

    def test_a_committed_file_is_reported_as_tracked(self, repo: Path) -> None:
        (repo / CONFIG).write_text(BODY)
        git(repo, "add", "-f", CONFIG)
        git(repo, "commit", "-qm", "oops")

        assert ignores.exposed_configs(repo) == [(repo / CONFIG, "tracked")]

    def test_an_ignored_file_is_not_reported(self, repo: Path) -> None:
        """The paired positive. Without it every assertion above would pass on an
        implementation that reported every file it found."""
        (repo / CONFIG).write_text(BODY)
        (repo / ".gitignore").write_text(f"{CONFIG}\n")

        assert ignores.exposed_configs(repo) == []


class TestTheRenameCaseThatStartedThis:
    def test_an_ignore_rule_for_the_old_name_does_not_protect_the_new_one(
        self, repo: Path
    ) -> None:
        """The exact shape both agents found: the comment was updated at the rename and
        the rule was not, so the repository read as done on inspection."""
        (repo / ".gitignore").write_text(
            "# agent-inbox per-project identity/config; never commit\n"
            "agent-mailbox.toml\n"
        )
        (repo / CONFIG).write_text(BODY)

        assert ignores.exposed_configs(repo) == [(repo / CONFIG, "unignored")]

    def test_the_old_name_is_still_checked_too(self, repo: Path) -> None:
        """Already-joined projects still hold `agent-mailbox.toml`, and it carries the
        same token. Checking only the current name would leave them exposed."""
        (repo / "agent-mailbox.toml").write_text(BODY)

        assert ignores.exposed_configs(repo) == [
            (repo / "agent-mailbox.toml", "unignored")
        ]


class TestWhatCountsAsWorthWarningAbout:
    def test_a_file_with_no_hub_or_token_is_left_alone(self, repo: Path) -> None:
        """Crying wolf about a placeholder teaches the reader to skip the line that
        matters. The warning rests on the file actually carrying something."""
        (repo / CONFIG).write_text("# written by hand, nothing in it yet\n")

        assert ignores.exposed_configs(repo) == []

    def test_a_token_alone_is_enough(self, repo: Path) -> None:
        (repo / CONFIG).write_text('token = "secret-xyz"\n')

        assert ignores.exposed_configs(repo) == [(repo / CONFIG, "unignored")]

    def test_a_file_in_a_subdirectory_is_found(self, repo: Path) -> None:
        """An agent may be working several directories into a checkout, so the file is
        not always at the root — and `join`'s ignore rule may not reach it."""
        nested = repo / "services" / "billing"
        nested.mkdir(parents=True)
        (nested / CONFIG).write_text(BODY)

        assert ignores.exposed_configs(repo) == [(nested / CONFIG, "unignored")]


def test_outside_a_repository_it_says_nothing(tmp_path: Path) -> None:
    """An honest "cannot say", not a claim of safety — and not a warning either, since
    there is no git here to expose anything to."""
    (tmp_path / CONFIG).write_text(BODY)

    assert ignores.exposed_configs(tmp_path) == []
