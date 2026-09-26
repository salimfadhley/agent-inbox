"""Saved hooks survive upgrades; diagnose the saved commands without rewriting them."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_inbox import hookconfig
from agent_inbox.cli import main
from agent_inbox.client import ClientError, Config, HubClient
from agent_inbox.prompts import onboarding


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(
        "agent_inbox.cli.load_config",
        lambda **kwargs: Config(hub="http://hub.example", name="test", engine="codex"),
    )

    def offline(self: HubClient) -> dict[str, Any]:
        raise ClientError("offline for test")

    monkeypatch.setattr(HubClient, "hub_info", offline)
    return tmp_path


def diagnose(root: Path, settings: object, capsys: pytest.CaptureFixture[str]) -> str:
    path = root / ".codex" / "hooks.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(settings))
    before = path.read_bytes()
    assert json.loads(before) == settings
    # Check outside git, and survive a later connectivity failure.
    assert main(["--engine", "codex", "doctor"]) == 1
    output = capsys.readouterr().out
    assert "codex hooks" in output
    assert path.read_bytes() == before
    return output


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (
            "python -m agent_inbox wake-check --event Stop "
            "--wait --wait-timeout 570 --no-rearm",
            "obsolete blocking waiter",
        ),
        (
            r"'C:\Users\example\python.exe' -m agent_inbox wake-check "
            "--event UserPromptSubmit",
            "Windows executable is single-quoted",
        ),
        (
            r"'\\server\tools\python.exe' -m agent_inbox wake-check "
            "--event SessionStart",
            "Windows executable is single-quoted",
        ),
    ],
)
def test_doctor_warns_about_legacy_commands(
    project: Path, capsys: pytest.CaptureFixture[str], command: str, reason: str
) -> None:
    settings = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": command, "timeout": 600}]}
            ]
        }
    }
    out = diagnose(project, settings, capsys)
    assert reason in out
    assert "agent-inbox install-hook --engine codex" in out
    assert "re-trust" in out
    assert "ok   codex hooks" not in out


@pytest.mark.parametrize(
    "command",
    [
        "python -m agent_inbox wake-check",
        r'"C:\Program Files\Python\python.exe" -m agent_inbox wake-check',
        "'/opt/with spaces/python' -m agent_inbox wake-check",
    ],
)
def test_current_hooks_and_unrelated_commands_are_not_flagged(
    project: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    settings = hookconfig.codex_apply({}, command, rewake=True)
    settings["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "other-tool --wait"}]}
    )
    out = diagnose(project, settings, capsys)
    assert "ok   codex hooks" in out
    assert "trust and activation are unverified" in out
    assert "obsolete commands" not in out


def test_reinstall_repairs_legacy_hooks_and_preserves_other_hooks(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unrelated = {"type": "command", "command": "other-tool --wait"}
    settings = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        unrelated,
                        {
                            "type": "command",
                            "command": "python -m agent_inbox wake-check --wait",
                        },
                    ]
                }
            ]
        }
    }
    assert "obsolete blocking waiter" in diagnose(project, settings, capsys)
    path = hookconfig.install_codex(project, "python -m agent_inbox wake-check")
    repaired = json.loads(path.read_text())
    assert unrelated in repaired["hooks"]["Stop"][0]["hooks"]
    assert "ok   codex hooks" in diagnose(project, repaired, capsys)
    hookconfig.install_codex(project, "python -m agent_inbox wake-check")
    before = path.read_bytes()
    hookconfig.install_codex(project, "python -m agent_inbox wake-check")
    assert path.read_bytes() == before


def test_served_prompt_explains_limits_without_naming_a_harness() -> None:
    text = onboarding("http://hub.example", version="1.7.0")
    section = text.split("## 6.", 1)[1].split("## 7.", 1)[0]
    assert "agent-inbox install-hook --rewake" in section
    assert "cannot wake an idle session" in section
    assert "Others can hold the event stream and wake an idle session" in section
    assert "`doctor` reports" in section
    assert "approve changed entries" in section
    assert "absolute path to uv" in section
