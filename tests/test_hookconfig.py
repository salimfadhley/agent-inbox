"""Installing the wake hooks into .claude/settings.json (mission 0017).

The one thing that must never happen is clobbering a user's own config, so the tests
lean on exactly that: an existing hook survives install; re-install is idempotent;
uninstall removes only our own entries.
"""

import json
from pathlib import Path

from agent_inbox import hookconfig


def _count_ours(settings: dict) -> int:
    n = 0
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                if "wake-check" in hook.get("command", ""):
                    n += 1
    return n


class TestApplyStrip:
    def test_apply_adds_three_events(self) -> None:
        out = hookconfig.apply({}, "agent-inbox wake-check")
        assert set(out["hooks"]) == set(hookconfig.EVENTS)
        assert _count_ours(out) == 3

    def test_stop_gets_rewake_when_asked(self) -> None:
        out = hookconfig.apply({}, "agent-inbox wake-check", rewake=True)
        stop = out["hooks"]["Stop"][0]["hooks"][0]
        assert stop.get("asyncRewake") is True and stop.get("async") is True
        assert "--wait" in stop["command"]
        assert "--poll-interval" in stop["command"]
        assert "--wait-timeout" in stop["command"]
        assert stop["timeout"] > 10
        # non-rewake events do not get it
        ss = out["hooks"]["SessionStart"][0]["hooks"][0]
        assert "asyncRewake" not in ss
        assert "--wait" not in ss["command"]

    def test_reinstall_is_idempotent(self) -> None:
        once = hookconfig.apply({}, "agent-inbox wake-check")
        twice = hookconfig.apply(once, "agent-inbox wake-check")
        assert _count_ours(twice) == 3  # not 6

    def test_a_users_existing_hook_survives(self) -> None:
        existing = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "my-linter"}]}],
                "PreToolUse": [{"hooks": [{"type": "command", "command": "guard.sh"}]}],
            }
        }
        out = hookconfig.apply(existing, "agent-inbox wake-check")
        commands = [
            h["command"]
            for groups in out["hooks"].values()
            for g in groups
            for h in g.get("hooks", [])
        ]
        assert "my-linter" in commands  # their Stop hook kept
        assert "guard.sh" in commands  # their PreToolUse untouched
        assert _count_ours(out) == 3

    def test_strip_removes_only_ours(self) -> None:
        installed = hookconfig.apply(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}},
            "agent-inbox wake-check",
        )
        stripped = hookconfig.strip(installed)
        assert _count_ours(stripped) == 0
        commands = [
            h["command"]
            for groups in stripped.get("hooks", {}).values()
            for g in groups
            for h in g.get("hooks", [])
        ]
        assert "mine" in commands  # the user's hook survived the uninstall


class TestFileIO:
    def test_install_creates_and_uninstall_clears(self, tmp_path: Path) -> None:
        path = hookconfig.install(tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert _count_ours(data) == 3

        hookconfig.uninstall(tmp_path)
        after = json.loads(path.read_text())
        assert _count_ours(after) == 0

    def test_install_preserves_other_settings(self, tmp_path: Path) -> None:
        path = hookconfig.settings_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "opus", "hooks": {}}))
        hookconfig.install(tmp_path)
        data = json.loads(path.read_text())
        assert data["model"] == "opus"  # unrelated setting kept
        assert _count_ours(data) == 3

    def test_malformed_settings_is_a_clear_error(self, tmp_path: Path) -> None:
        path = hookconfig.settings_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{ not json")
        try:
            hookconfig.install(tmp_path)
        except ValueError as exc:
            assert "valid JSON" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected a ValueError on malformed settings")
