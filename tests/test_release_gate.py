from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_mailbox.exceptions import ReleaseGateError
from agent_mailbox.release_gate import (
    extract_prompt_install,
    install_command,
    main,
    prompt_install_for_version,
    verify_hub_version,
    verify_resolver,
)


def test_release_prompt_advertises_the_release_version() -> None:
    install = prompt_install_for_version("1.2.3")

    assert install.version == "1.2.3"
    assert install.requirement == "agent-inbox[clients]>=1.2.3"
    assert install.command == install_command("agent-inbox[clients]>=1.2.3")


def test_prompt_install_extraction_rejects_missing_or_duplicate_floors() -> None:
    with pytest.raises(ReleaseGateError, match="expected exactly one"):
        extract_prompt_install("uv tool install agent-inbox")

    line = 'uv tool install --refresh --no-cache --force "agent-inbox[clients]>=1.2.3"'
    with pytest.raises(ReleaseGateError, match="expected exactly one"):
        extract_prompt_install(f"{line}\n{line}")


def test_resolver_uses_the_same_clean_install_command_the_prompt_advertises() -> None:
    seen: list[tuple[list[str], float]] = []

    def runner(
        command: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        seen.append((list(command), timeout))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    verify_resolver(
        "agent-inbox[clients]>=1.2.3",
        runner=runner,
        attempts=1,
        timeout=42.0,
    )

    assert seen == [
        (
            [
                "uv",
                "tool",
                "install",
                "--refresh",
                "--no-cache",
                "--force",
                "agent-inbox[clients]>=1.2.3",
            ],
            42.0,
        )
    ]


def test_resolver_blocks_prompt_deploy_when_index_has_not_caught_up() -> None:
    """Rowan's first-contact failure: prompt floor exists in text, not on the index."""
    commands: list[list[str]] = []
    sleeps: list[float] = []

    def runner(
        command: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        return subprocess.CompletedProcess(
            list(command),
            1,
            "",
            "No solution found: agent-inbox 9.9.9 was not found in the package index",
        )

    with pytest.raises(ReleaseGateError) as got:
        verify_resolver(
            "agent-inbox[clients]>=9.9.9",
            runner=runner,
            attempts=3,
            delay=0.5,
            sleep=sleeps.append,
        )

    problem = str(got.value)
    assert "agent-inbox[clients]>=9.9.9" in problem
    assert (
        "uv tool install --refresh --no-cache --force 'agent-inbox[clients]>=9.9.9'"
        in problem
    )
    assert "agent-inbox 9.9.9 was not found" in problem
    assert len(commands) == 3
    assert sleeps == [0.5, 0.5]


def test_release_gate_cli_can_check_prompt_without_installing() -> None:
    assert main(["--version", "1.2.3", "--skip-install"]) == 0


def test_release_gate_cli_fails_when_resolver_cannot_reach_the_floor() -> None:
    def runner(
        command: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(command), 1, "", "no matching version")

    assert (
        main(
            ["--version", "1.2.3", "--attempts", "1", "--delay", "0"],
            runner=runner,
        )
        == 1
    )


def test_hub_descriptor_version_must_match_the_prompt_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"version": "1.2.3"}'

    def urlopen(url: str, timeout: float) -> Response:
        assert url == "https://hub.example.invalid/"
        assert timeout == 4.0
        return Response()

    monkeypatch.setattr("agent_mailbox.release_gate.urllib.request.urlopen", urlopen)

    verify_hub_version("https://hub.example.invalid", "1.2.3", timeout=4.0)
    with pytest.raises(ReleaseGateError, match="reports version"):
        verify_hub_version("https://hub.example.invalid", "1.2.4", timeout=4.0)


def test_release_workflows_gate_the_prompt_floor_before_live_release() -> None:
    root = Path(__file__).resolve().parents[1]
    release = (root / ".github/workflows/release.yaml").read_text()
    docker = (root / ".github/workflows/docker.yml").read_text()

    assert "Verify PyPI can satisfy the prompt floor" in release
    assert "python -m agent_mailbox.release_gate" in release
    assert "uvx --with hatch-vcs hatch version" in release
    assert release.index("Publish to PyPI") < release.index(
        "Verify PyPI can satisfy the prompt floor"
    )

    assert "Verify release prompt floor is on PyPI" in docker
    assert "if: steps.kind.outputs.release == 'true'" in docker
    assert "python -m agent_mailbox.release_gate" in docker
    assert "uvx --with hatch-vcs hatch version" in docker
    assert docker.index("Verify release prompt floor is on PyPI") < docker.index(
        "Build and push"
    )
