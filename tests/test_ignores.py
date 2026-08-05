"""The config we write must be one git will not commit.

`join` writes a file that may carry a device token. Whether it reaches a shared remote
was left to the reader until now — and a rename made that advice wrong everywhere at
once, because a repository carrying the old `agent-mailbox.toml` line reads as protected
while missing `agent-inbox.toml` by one word.

These tests run real git. The thing under test is *what git actually does*, and a fake
would be a second, worse implementation of exactly the rules that made this subtle.
"""

import subprocess
from pathlib import Path

import pytest

from agent_inbox.ignores import ensure_ignored, is_ignored, is_tracked

CONFIG = "agent-inbox.toml"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "T")
    return tmp_path


@pytest.fixture
def config(repo: Path) -> Path:
    path = repo / CONFIG
    path.write_text('hub = "https://hub.invalid"\n')
    return path


def test_it_adds_the_rule_when_nothing_covers_the_file(
    repo: Path, config: Path
) -> None:
    assert ensure_ignored(config, repo) == "added"

    assert is_ignored(config, repo), "git still does not ignore it"
    assert CONFIG in (repo / ".gitignore").read_text()


def test_the_stale_name_does_not_count_as_covered(repo: Path, config: Path) -> None:
    """The bug, exactly.

    A repository carrying the pre-rename line looks protected: the comment states the
    intent correctly and the pattern misses by one word. That is the worst shape for
    this class of fault, because nobody re-checks something that reads as done.
    """
    (repo / ".gitignore").write_text(
        "# agent-inbox per-project identity/config (never commit)\nagent-mailbox.toml\n"
    )

    assert ensure_ignored(config, repo) == "added"
    assert is_ignored(config, repo)


def test_it_does_nothing_when_already_covered(repo: Path, config: Path) -> None:
    """The paired positive: idempotence, and no duplicate lines."""
    (repo / ".gitignore").write_text(f"{CONFIG}\n")

    assert ensure_ignored(config, repo) == "already"

    assert (repo / ".gitignore").read_text().count(CONFIG) == 1


def test_running_twice_adds_one_rule(repo: Path, config: Path) -> None:
    ensure_ignored(config, repo)
    ensure_ignored(config, repo)

    assert (repo / ".gitignore").read_text().count(f"\n{CONFIG}\n") == 1


def test_it_keeps_whatever_was_already_there(repo: Path, config: Path) -> None:
    """Somebody else's ignore file is not ours to rewrite."""
    (repo / ".gitignore").write_text("__pycache__/\n*.log\n")

    ensure_ignored(config, repo)

    after = (repo / ".gitignore").read_text()
    assert "__pycache__/" in after
    assert "*.log" in after


def test_a_file_already_committed_is_reported_not_papered_over(
    repo: Path, config: Path
) -> None:
    """An ignore rule does nothing for a tracked file.

    Adding one anyway would leave the reader more confident and no safer — and the
    remedy here is different: remove it from git, and revoke any token it carried.
    """
    git(repo, "add", CONFIG)
    git(repo, "commit", "-qm", "oops")

    assert ensure_ignored(config, repo) == "tracked"
    assert is_tracked(config, repo)


def test_outside_a_repository_it_does_nothing_quietly(tmp_path: Path) -> None:
    """Not every checkout is a git repository, and that is not a fault."""
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / CONFIG).write_text("hub = ''\n")

    assert ensure_ignored(loose / CONFIG, loose) == ""
    assert not (loose / ".gitignore").exists()


def test_an_earlier_negation_is_overridden_and_the_result_is_checked(
    repo: Path, config: Path
) -> None:
    """A repository that had explicitly un-ignored the file ends up ignoring it.

    Git resolves by *last matching pattern*, so the line we append wins over an earlier
    `!agent-inbox.toml`. Worth a test because the first version of it asserted the
    opposite — and the function reported the truth anyway, because it re-reads the
    answer from git rather than inferring it from having written a line. That
    re-reading is the point: claiming a protection we have not verified is the failure
    this module exists to prevent.
    """
    (repo / ".gitignore").write_text(f"!{CONFIG}\n")

    assert ensure_ignored(config, repo) == "added"
    assert is_ignored(config, repo)
