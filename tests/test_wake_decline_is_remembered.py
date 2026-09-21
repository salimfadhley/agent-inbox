"""Removing the wake hooks is a decision, and `join` must not undo it (#73).

A Codex user deleted the generated `.codex/hooks.json` because its Stop hook held
their session for five minutes after every answer. `join` installs waking by default,
so the next join would have put it back — and on Codex what came back was the blocking
hook again. A choice made by hand has to survive the tool's next opinion.

`uninstall-hook` records the refusal against the engine's own entry; `join` reads it
before writing anything; an explicit `install-hook` is a change of mind and clears it.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_inbox import cli, hookconfig
from agent_inbox.client import CONFIG_NAME, wake_declined


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / CONFIG_NAME).write_text(
        'hub = "http://hub:8081"\n\n[agents.codex]\nname = "pablo_fantomas"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    for var in ("CLAUDECODE", "OMPCODE", "OPENCODE", "AGENT_INBOX_NAME"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


class TestTheRefusalIsRecorded:
    def test_uninstall_records_it_and_says_so(self, project: Path, capsys: Any) -> None:
        hookconfig.install_for("codex", project)

        assert cli.main(["uninstall-hook"]) == 0

        assert wake_declined("codex", project) is True
        out = capsys.readouterr().out
        assert "will not have them reinstalled" in out
        assert "install-hook" in out  # how to ask for them back

    def test_a_fresh_project_has_declined_nothing(self, project: Path) -> None:
        assert wake_declined("codex", project) is False

    def test_it_is_recorded_per_engine(self, project: Path) -> None:
        cli.main(["uninstall-hook"])

        assert wake_declined("codex", project) is True
        assert wake_declined("claude", project) is False

    def test_an_unresolvable_engine_records_nothing_and_says_so(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """Writing the refusal into somebody else's entry would be worse than not
        recording it."""
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        (project / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n[agents.codex]\nname = "a"\n\n'
            '[agents.claude]\nname = "b"\n'
        )

        assert cli.main(["uninstall-hook"]) == 0

        out = capsys.readouterr().out
        assert "nothing was recorded" in out
        assert wake_declined("codex", project) is False


class TestJoinHonoursIt:
    def test_join_does_not_reinstall_after_a_refusal(self, project: Path) -> None:
        """The bug: the hooks came back, uninvited, blocking the session again."""
        cli.main(["uninstall-hook"])

        assert cli._install_wake_hook("codex") is None
        assert not hookconfig.codex_hooks_path(project).exists()

    def test_join_installs_when_nothing_was_refused(self, project: Path) -> None:
        """The paired positive — without it this proves only that nothing happens."""
        assert cli._install_wake_hook("codex") is not None
        assert hookconfig.codex_hooks_path(project).exists()


class TestAskingForThemBackClearsIt:
    def test_install_hook_clears_the_refusal(self, project: Path) -> None:
        cli.main(["uninstall-hook"])

        assert cli.main(["install-hook"]) == 0

        assert wake_declined("codex", project) is False
        assert hookconfig.codex_hooks_path(project).exists()

    def test_and_then_join_installs_again(self, project: Path) -> None:
        cli.main(["uninstall-hook"])
        cli.main(["install-hook"])
        hookconfig.uninstall_codex(project)

        assert cli._install_wake_hook("codex") is not None
