"""Generated wake hooks are kept out of git, and `doctor` says when they are not (#70).

`install-hook` writes `.omp/extensions/agent-inbox-wake.js` (and opencode's plugin)
containing the installing machine's interpreter path — on Windows, a path under the
user's profile. It added no ignore rule, and `doctor`'s "config safety" line looked only
at identity files, so a Windows omp session saw `?? .omp/` in `git status` beside a
line saying nothing was exposed.

The rule is narrow — the one file, anchored — because `.omp/` may hold extensions a
team shares on purpose. The three states are the identity file's three states, because
they need three different actions.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_inbox import cli, hookconfig, ignores

HOOK = ".omp/extensions/agent-inbox-wake.js"


def git(root: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "readme.md").write_text("hello\n")
    git(tmp_path, "add", "readme.md")
    git(tmp_path, "commit", "-qm", "first")
    return tmp_path


class TestTheInstallerIgnoresWhatItWrites:
    def test_a_fresh_omp_hook_is_ignored_and_broad_staging_skips_it(
        self, repo: Path
    ) -> None:
        """The report's own reproduction: install, then see whether `git add -A`
        would take the file. It must not."""
        hookconfig.install_for("omp", repo)
        git(repo, "add", "-A")

        staged = git(repo, "diff", "--cached", "--name-only")
        assert HOOK not in staged
        assert f"/{HOOK}" in (repo / ".gitignore").read_text()

    def test_the_rule_is_the_one_file_not_the_directory(self, repo: Path) -> None:
        """`.omp/mcp.json` or a shared extension must stay committable."""
        hookconfig.install_for("omp", repo)
        (repo / ".omp" / "mcp.json").write_text("{}\n")
        (repo / ".omp" / "extensions" / "team-thing.js").write_text("// shared\n")
        git(repo, "add", "-A")

        staged = git(repo, "diff", "--cached", "--name-only")
        assert ".omp/mcp.json" in staged
        assert ".omp/extensions/team-thing.js" in staged
        assert HOOK not in staged

    def test_reinstalling_adds_one_rule_and_keeps_the_rest(self, repo: Path) -> None:
        (repo / ".gitignore").write_text("*.log\n# mine\nbuild/\n")
        hookconfig.install_for("omp", repo)
        hookconfig.install_for("omp", repo)

        text = (repo / ".gitignore").read_text()
        assert text.count(f"/{HOOK}") == 1
        assert text.startswith("*.log\n# mine\nbuild/\n")

    def test_the_opencode_plugin_gets_the_same_treatment(self, repo: Path) -> None:
        hookconfig.install_for("opencode", repo)
        git(repo, "add", "-A")

        assert ".opencode/plugins/agent-inbox-wake.js" not in git(
            repo, "diff", "--cached", "--name-only"
        )

    def test_join_goes_through_the_same_installer(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every entry point that writes the hook: join's automatic install is the
        one most people actually hit."""
        monkeypatch.chdir(repo)

        assert cli._install_wake_hook("omp") is not None
        assert f"/{HOOK}" in (repo / ".gitignore").read_text()

    def test_outside_a_repository_the_hook_is_still_written(
        self, tmp_path: Path
    ) -> None:
        path = hookconfig.install_for("omp", tmp_path)

        assert path.exists()
        assert not (tmp_path / ".gitignore").exists()


class TestDoctorSeesAnExposedHook:
    def _hook_without_a_rule(self, repo: Path) -> Path:
        path = repo / HOOK
        path.parent.mkdir(parents=True)
        path.write_text(
            hookconfig.omp_extension("/somebox/python -m agent_inbox wake-check")
        )
        return path

    def test_an_unignored_hook_is_reported(self, repo: Path) -> None:
        """A hook written before the installer added rules — the report's case."""
        path = self._hook_without_a_rule(repo)

        assert ignores.exposed_hooks(repo) == [(path, "unignored")]

    def test_a_staged_hook_is_reported_as_staged(self, repo: Path) -> None:
        path = self._hook_without_a_rule(repo)
        git(repo, "add", "-f", HOOK)

        assert ignores.exposed_hooks(repo) == [(path, "staged")]

    def test_a_tracked_hook_is_reported_even_when_a_rule_exists(
        self, repo: Path
    ) -> None:
        """Git ignore rules do not protect already-tracked content."""
        path = self._hook_without_a_rule(repo)
        git(repo, "add", "-f", HOOK)
        git(repo, "commit", "-qm", "oops")
        (repo / ".gitignore").write_text(f"/{HOOK}\n")

        assert ignores.exposed_hooks(repo) == [(path, "tracked")]

    def test_an_ignored_untracked_hook_is_not_reported(self, repo: Path) -> None:
        hookconfig.install_for("omp", repo)

        assert ignores.exposed_hooks(repo) == []

    def test_somebody_elses_file_at_our_path_is_not_ours_to_report(
        self, repo: Path
    ) -> None:
        path = repo / HOOK
        path.parent.mkdir(parents=True)
        path.write_text("export default function () {}\n")

        assert ignores.exposed_hooks(repo) == []

    def test_outside_a_repository_it_cannot_say(self, tmp_path: Path) -> None:
        hookconfig.install_for("omp", tmp_path)

        assert ignores.exposed_hooks(tmp_path) == []


class TestTheDoctorLine:
    def _report(self, monkeypatch: pytest.MonkeyPatch, root: Path, capsys: Any) -> str:
        monkeypatch.chdir(root)
        notes = cli._Notes("WARN")
        cli._report_exposure("ok", notes)
        notes.flush()
        captured = capsys.readouterr()
        return captured.out + captured.err

    def test_it_distinguishes_a_tracked_hook_from_an_unignored_one(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        path = repo / HOOK
        path.parent.mkdir(parents=True)
        path.write_text(
            hookconfig.omp_extension("/somebox/python -m agent_inbox wake-check")
        )

        unignored = self._report(monkeypatch, repo, capsys)
        git(repo, "add", "-f", HOOK)
        git(repo, "commit", "-qm", "oops")
        tracked = self._report(monkeypatch, repo, capsys)

        assert "NOT IGNORED" in unignored and HOOK in unignored
        assert "TRACKED" in tracked and "git rm --cached" in tracked

    def test_a_protected_hook_gets_a_quiet_ok(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        hookconfig.install_for("omp", repo)

        out = self._report(monkeypatch, repo, capsys)

        assert "hook safety     generated wake hooks are not exposed" in out

    def test_outside_a_repository_it_says_so_rather_than_claiming_safety(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """The line used to read "not exposed to git" on an open field."""
        out = self._report(monkeypatch, tmp_path, capsys)

        assert "not a git repository" in out
        assert "not exposed" not in out
