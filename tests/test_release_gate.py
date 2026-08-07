import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_inbox.exceptions import ReleaseGateError
from agent_inbox.release_gate import (
    extract_prompt_install,
    install_command,
    main,
    prompt_install_for_version,
    release_artifact_install_for_version,
    verify_hub_version,
    verify_resolver,
)
from agent_inbox.staleness import INSTALL_FLOOR, interpreter_pin


def test_release_prompt_advertises_the_minimum_client_floor() -> None:
    install = prompt_install_for_version("1.2.3")

    assert install.version == INSTALL_FLOOR
    assert install.requirement == f"agent-inbox[clients]>={INSTALL_FLOOR}"
    assert install.command == install_command(
        f"agent-inbox[clients]>={INSTALL_FLOOR}", interpreter_pin()
    ), "the gate must run the pinned command the prompt actually gives agents"


def test_release_artifact_check_pins_the_exact_release_version() -> None:
    install = release_artifact_install_for_version("1.2.3")

    assert install.version == "1.2.3"
    assert install.requirement == "agent-inbox[clients]==1.2.3"
    assert install.command == install_command(
        "agent-inbox[clients]==1.2.3", interpreter_pin()
    )


def test_prompt_install_extraction_rejects_a_prompt_that_advertises_none() -> None:
    with pytest.raises(ReleaseGateError, match="advertises no install command"):
        extract_prompt_install("uv tool install agent-inbox")


def test_the_same_command_twice_is_fine() -> None:
    """Changed on 2026-08-07, when the prompt grew a second legitimate place to show
    it: the Windows recovery path, where somebody who has just killed a process needs
    to be told what to run rather than sent back up the page.

    One *command* was always the rule; one *occurrence* was how it happened to be
    spelled. Every copy renders from `staleness.upgrade_command`, so identical
    repetitions are guaranteed rather than hoped for."""
    line = (
        "uv tool install --upgrade --python 3.14 --refresh --no-cache "
        '"agent-inbox[clients]>=1.2.3"'
    )

    found = extract_prompt_install(f"{line}\nblah blah\n{line}")

    assert found.version == "1.2.3"


def test_two_different_commands_are_still_refused() -> None:
    """The drift this gate exists for: `doctor` once gave the unpinned form while the
    prompt gave the pinned one, so the advice an agent met when it was already confused
    was the wrong one."""
    pinned = (
        "uv tool install --upgrade --python 3.14 --refresh --no-cache "
        '"agent-inbox[clients]>=1.2.3"'
    )
    other = (
        "uv tool install --upgrade --python 3.13 --refresh --no-cache "
        '"agent-inbox[clients]>=1.2.3"'
    )

    with pytest.raises(ReleaseGateError, match="different install commands"):
        extract_prompt_install(f"{pinned}\n{other}")


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
                "--upgrade",
                "--refresh",
                "--no-cache",
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
        "uv tool install --upgrade --refresh --no-cache "
        "'agent-inbox[clients]>=9.9.9'" in problem
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

    monkeypatch.setattr("agent_inbox.release_gate.urllib.request.urlopen", urlopen)

    verify_hub_version("https://hub.example.invalid", "1.2.3", timeout=4.0)
    with pytest.raises(ReleaseGateError, match="reports version"):
        verify_hub_version("https://hub.example.invalid", "1.2.4", timeout=4.0)


def test_release_workflows_gate_the_prompt_floor_before_live_release() -> None:
    root = Path(__file__).resolve().parents[1]
    release = (root / ".github/workflows/release.yaml").read_text()
    docker = (root / ".github/workflows/docker.yml").read_text()

    assert "Verify PyPI can satisfy the exact release artifact" in release
    assert "python -m agent_inbox.release_gate" in release
    assert "--check release-artifact" in release
    assert "uvx --with hatch-vcs hatch version" in release
    assert release.index("Publish to PyPI") < release.index(
        "Verify PyPI can satisfy the exact release artifact"
    )

    assert "Verify PyPI can satisfy the prompt floor" in docker
    assert "if: steps.kind.outputs.release == 'true'" in docker
    assert "python -m agent_inbox.release_gate" in docker
    assert "--check prompt-floor" in docker
    assert "uvx --with hatch-vcs hatch version" in docker
    assert docker.index("Verify PyPI can satisfy the prompt floor") < docker.index(
        "Build and push"
    )
