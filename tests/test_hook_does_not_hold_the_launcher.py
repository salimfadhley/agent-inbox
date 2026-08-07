"""The wake hook must not run the `agent-inbox` launcher.

On Windows a running `.exe` cannot be overwritten, and `uv tool install --force` has to
replace the launcher at `~/.local/bin/agent-inbox.exe`. Installing the wake hook as
`agent-inbox wake-check` started that launcher **on every turn of every session**, so
the file was reliably in use and every upgrade ended in `os error 32`.

Reported by the owner on 2026-08-07 upgrading 0.83.0 to 0.87.0, with the observation
that makes it obvious: the launcher never actually changes between releases. It is a
generic stub holding an interpreter path and an entry point, identical from one version
to the next. uv copies it anyway, and the copy is what fails.

The same reasoning had already moved the MCP server to `python -m agent_inbox mcp`. This
was the other invocation made on somebody's behalf, and it was missed because it is
installed once and then never seen again — which is exactly why it is worth a test that
names the shape rather than the spelling.
"""

import json
import sys
from pathlib import Path

from agent_inbox import hookconfig


class TestTheDefaultCommandAvoidsTheLauncher:
    def test_it_does_not_invoke_the_launcher(self) -> None:
        """The bug, stated. Asserted as an absence, because any number of spellings
        would be fine and only one is forbidden."""
        assert "agent-inbox wake-check" not in hookconfig.default_command()

    def test_it_runs_this_interpreter_on_the_module(self) -> None:
        """The paired positive: not running the launcher is worthless if it does not
        run anything that works. `sys.executable` is the environment agent-inbox is
        installed into, so it is the one that can import the package."""
        command = hookconfig.default_command()

        assert "-m agent_inbox wake-check" in command
        assert sys.executable in command

    def test_an_interpreter_path_with_a_space_survives(
        self, monkeypatch: object
    ) -> None:
        """A uv tool directory can sit under a path with a space in it, and an unquoted
        command would then run the wrong program with a stray argument."""
        import shlex

        original = sys.executable
        try:
            sys.executable = "/opt/Program Files/py/python"
            command = hookconfig.default_command()
        finally:
            sys.executable = original

        assert shlex.split(command)[0] == "/opt/Program Files/py/python"


class TestInstallingMigratesTheOldHook:
    """An agent that already has the bad hook is the whole population worth fixing —
    it is installed once at join and never looked at again."""

    def _hooks(self, root: Path) -> list[str]:
        settings = json.loads(hookconfig.settings_path(root).read_text())
        return [
            str(hook.get("command", ""))
            for entries in settings.get("hooks", {}).values()
            for entry in entries
            for hook in entry.get("hooks", [])
        ]

    def test_an_existing_launcher_hook_is_replaced_not_duplicated(
        self, tmp_path: Path
    ) -> None:
        hookconfig.install(tmp_path, command="agent-inbox wake-check")
        before = self._hooks(tmp_path)
        assert before, "precondition: the old-style hook was installed"
        assert any("agent-inbox wake-check" in c for c in before)

        hookconfig.install(tmp_path)

        after = self._hooks(tmp_path)
        assert len(after) == len(before), "the old entries were not removed"
        assert not any(c.startswith("agent-inbox ") for c in after)
        assert all("wake-check" in c for c in after)

    def test_another_tools_hooks_are_left_alone(self, tmp_path: Path) -> None:
        """The migration strips by marker, and the marker is the *subcommand*. That is
        what lets a hook installed under the old program name be recognised — and it
        must not become a licence to remove somebody else's entries."""
        path = hookconfig.settings_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "somebody-else"}]}
                        ]
                    }
                }
            )
        )

        hookconfig.install(tmp_path)

        assert "somebody-else" in self._hooks(tmp_path)


class TestThePromptSaysWhatIsHoldingIt:
    def test_it_no_longer_blames_other_sessions(self) -> None:
        """It used to say *"every other agent session on this machine is holding
        agent-inbox.exe open"*. Since the MCP servers launch the module, they do not —
        so the reader was sent to look at sessions while the hook we installed was the
        holder."""
        from agent_inbox.prompts import onboarding

        text = onboarding("https://hub.example", version="1.2.3")

        assert "every other agent session on this machine is holding" not in text

    def test_it_names_the_hook_and_the_remedy(self) -> None:
        from agent_inbox.prompts import onboarding

        text = onboarding("https://hub.example", version="1.2.3")

        assert "wake hook, not another session" in text
        assert "install-hook" in text
        from agent_inbox.prompts import LAUNCHER_FREE_SINCE

        assert LAUNCHER_FREE_SINCE in text

    def test_it_offers_the_move_aside_workaround(self) -> None:
        """For anyone whose launcher is held by something that is not ours. Renaming a
        file that is in use is permitted on Windows, which is how installers do it."""
        from agent_inbox.prompts import onboarding

        text = onboarding("https://hub.example", version="1.2.3")

        assert "move %USERPROFILE%" in text
