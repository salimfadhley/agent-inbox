"""Release checks for package requirements involved in a live release.

The hub and the Python package are released from the same source, but they reach
users through different channels. A tagged Docker image can therefore serve a prompt
before the package index can satisfy the requirement that prompt names; a PyPI
publish can also half succeed such that metadata exists before the resolver surface
agents use can install the exact released version. This module is intentionally small
and stdlib-only so release workflows can gate both questions.
"""

import argparse
import json
import logging
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agent_inbox import __version__
from agent_inbox.exceptions import ReleaseGateError
from agent_inbox.prompts import onboarding
from agent_inbox.staleness import INSTALL_FLOOR, interpreter_pin

LOGGER = logging.getLogger(__name__)

PROMPT_HUB_URL = "https://hub.example.invalid"
PROMPT_URL = f"{PROMPT_HUB_URL}/prompts/agent"
PACKAGE_REQUIREMENT = "agent-inbox[clients]"
CHECK_PROMPT_FLOOR = "prompt-floor"
CHECK_RELEASE_ARTIFACT = "release-artifact"
DEFAULT_CHECKS = (CHECK_PROMPT_FLOOR, CHECK_RELEASE_ARTIFACT)

PROMPT_INSTALL_RE = re.compile(
    r"uv tool install --python (?P<python>[0-9.]+) --refresh --no-cache --force "
    r'"(?P<requirement>agent-inbox\[clients\]>=(?P<version>[^"\s]+))"'
)

Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class PromptInstall:
    """The executable package floor found in the onboarding prompt."""

    version: str
    requirement: str
    command: tuple[str, ...]


def install_command(requirement: str, python: str = "") -> tuple[str, ...]:
    """Return the exact clean install shape agents are told to use.

    ``python`` pins the interpreter. It is part of the command rather than an optional
    extra because **uv will not change the interpreter for you**: asked for a release
    that needs a newer Python than the tool is currently installed under, it resolves
    to an older release that fits and reports success. The pin is what turns that into
    a failure somebody can see (owner, 2026-08-05).
    """
    pin = ("--python", python) if python else ()
    return (
        "uv",
        "tool",
        "install",
        *pin,
        "--refresh",
        "--no-cache",
        "--force",
        requirement,
    )


def extract_prompt_install(prompt: str) -> PromptInstall:
    """Find the single versioned ``uv tool install`` command in a rendered prompt."""
    matches = list(PROMPT_INSTALL_RE.finditer(prompt))
    if len(matches) != 1:
        raise ReleaseGateError(
            "expected exactly one prompt install command for "
            f"{PACKAGE_REQUIREMENT}>=<version>, found {len(matches)}"
        )
    match = matches[0]
    requirement = match.group("requirement")
    return PromptInstall(
        version=match.group("version"),
        requirement=requirement,
        # The interpreter the prompt itself names, not one chosen here. The gate must
        # run the command agents are actually given — a pin it substituted would verify
        # something nobody was told to type.
        command=install_command(requirement, match.group("python")),
    )


def prompt_install_for_version(version: str) -> PromptInstall:
    """Render the live prompt template and return its advertised package floor."""
    version = version.strip()
    if not version:
        raise ReleaseGateError("release version is empty")
    prompt_install = extract_prompt_install(
        onboarding(PROMPT_HUB_URL, PROMPT_URL, version)
    )
    if prompt_install.version != INSTALL_FLOOR:
        raise ReleaseGateError(
            "prompt package floor does not match INSTALL_FLOOR: "
            f"{prompt_install.version!r} != {INSTALL_FLOOR!r}"
        )
    return prompt_install


def release_artifact_install_for_version(version: str) -> PromptInstall:
    """Return the exact install requirement for a just-published release."""
    version = version.strip()
    if not version:
        raise ReleaseGateError("release version is empty")
    if any(char.isspace() for char in version):
        raise ReleaseGateError(f"release version contains whitespace: {version!r}")
    requirement = f"{PACKAGE_REQUIREMENT}=={version}"
    return PromptInstall(
        version=version,
        requirement=requirement,
        command=install_command(requirement, interpreter_pin()),
    )


def fetch_hub_info(hub_url: str, *, timeout: float) -> dict[str, object]:
    """Fetch the hub descriptor used by the console prompt."""
    url = hub_url.rstrip("/") + "/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ReleaseGateError(
            f"could not read hub descriptor from {url}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ReleaseGateError(f"hub descriptor at {url} was not a JSON object")
    return payload


def verify_hub_version(hub_url: str, version: str, *, timeout: float) -> None:
    """Verify an already-running hub reports the same version as the release."""
    hub = fetch_hub_info(hub_url, timeout=timeout)
    advertised = str(hub.get("version") or "").strip()
    if advertised != version:
        raise ReleaseGateError(
            f"hub at {hub_url} reports version {advertised!r}, expected {version!r}"
        )


def run_command(
    command: Sequence[str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run one release-gate subprocess with captured output."""
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def verify_resolver(
    requirement: str,
    *,
    runner: Runner = run_command,
    attempts: int = 20,
    delay: float = 15.0,
    timeout: float = 180.0,
    sleep: Sleeper = time.sleep,
) -> None:
    """Verify a clean uv tool install can resolve the prompt's requirement."""
    if attempts < 1:
        raise ReleaseGateError("resolver attempts must be at least 1")
    if delay < 0:
        raise ReleaseGateError("resolver delay must not be negative")
    if timeout <= 0:
        raise ReleaseGateError("resolver timeout must be positive")

    command = install_command(requirement)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            result = runner(command, timeout)
        except FileNotFoundError as exc:
            raise ReleaseGateError("uv is not installed or is not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            last_error = f"timed out after {exc.timeout} seconds"
        else:
            if result.returncode == 0:
                LOGGER.info("resolver accepted %s", requirement)
                return
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            last_error = output.strip() or f"uv exited with status {result.returncode}"

        if attempt < attempts:
            LOGGER.info(
                "resolver attempt %s/%s failed for %s; retrying in %.1fs",
                attempt,
                attempts,
                requirement,
                delay,
            )
            sleep(delay)

    raise ReleaseGateError(
        "clean resolver could not install "
        f"{requirement!r} with {shlex.join(command)} after {attempts} attempt(s): "
        f"{last_error}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the release-gate CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Fail if the onboarding prompt advertises a package floor that a clean "
            "resolver cannot install."
        )
    )
    parser.add_argument(
        "--version",
        default=__version__,
        help=(
            "release version to verify as an exact artifact; defaults to package "
            "metadata"
        ),
    )
    parser.add_argument(
        "--check",
        choices=DEFAULT_CHECKS,
        action="append",
        help=(
            "check to run; pass more than once. Defaults to prompt-floor and "
            "release-artifact."
        ),
    )
    parser.add_argument(
        "--hub-url",
        help="optional running hub URL whose descriptor version must match --version",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=20,
        help="resolver attempts before failing",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=15.0,
        help="seconds to wait between resolver attempts",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="seconds before one resolver or hub request attempt times out",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="check prompt consistency only; release workflows must not use this",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = run_command,
    sleep: Sleeper = time.sleep,
) -> int:
    """Run the release gate and return a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    checks = tuple(dict.fromkeys(args.check or DEFAULT_CHECKS))
    try:
        if args.hub_url:
            verify_hub_version(args.hub_url, args.version, timeout=args.timeout)
            LOGGER.info("hub descriptor reports %s", args.version)

        if CHECK_PROMPT_FLOOR in checks:
            prompt_install = prompt_install_for_version(args.version)
            LOGGER.info(
                "prompt floor advertises %s via %s",
                prompt_install.requirement,
                shlex.join(prompt_install.command),
            )
            if not args.skip_install:
                verify_resolver(
                    prompt_install.requirement,
                    runner=runner,
                    attempts=args.attempts,
                    delay=args.delay,
                    timeout=args.timeout,
                    sleep=sleep,
                )

        if CHECK_RELEASE_ARTIFACT in checks:
            artifact_install = release_artifact_install_for_version(args.version)
            LOGGER.info(
                "release artifact requires %s via %s",
                artifact_install.requirement,
                shlex.join(artifact_install.command),
            )
            if not args.skip_install:
                verify_resolver(
                    artifact_install.requirement,
                    runner=runner,
                    attempts=args.attempts,
                    delay=args.delay,
                    timeout=args.timeout,
                    sleep=sleep,
                )
    except ReleaseGateError as exc:
        LOGGER.error("release gate failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
