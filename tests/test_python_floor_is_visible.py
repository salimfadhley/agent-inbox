"""The prerequisite that fails quietly.

`uv tool install "agent-inbox[clients]>=0.17.1"` on an interpreter older than our floor
does **not** fail. The resolver finds the newest release that interpreter supports,
installs it, prints `Installed 2 executables`, and says nothing. So the version floor —
which exists precisely so an unreachable version *"fails and tells you, instead of
quietly settling on an old release"* — does the exact thing it was written to prevent.

Reported by `igor_laszlo` on 2026-08-05, who caught it only by diffing `--version`
against what he had asked for. Two agents on one machine sat on 0.34.0 and could not be
woken: the feature added by the release they had silently missed.

Nothing in the codebase could have caught this. It is a property of a resolver on
somebody else's machine. What these tests hold in place is that we *say so* — in the
page an agent reads before installing, and in the command it runs when confused.
"""

import pytest

from agent_inbox import staleness
from agent_inbox.prompts import onboarding

HUB = "https://api.hub.invalid"
PROMPT = "https://hub.invalid/prompts/agent"


def test_the_floor_is_read_from_metadata_not_typed() -> None:
    """Typed twice is drifted twice. It must come from `pyproject.toml`'s own value."""
    assert staleness.python_floor() == "3.14"


def test_the_prompt_names_the_python_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = onboarding(HUB, PROMPT, "0.59.0", True)

    assert "Python 3.14" in page, "the page never states the one prerequisite"


def test_the_prompt_says_the_failure_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Naming the version is not enough.

    A reader who sees "needs 3.14" and whose install *succeeded* concludes they have it.
    The page has to say that success is not evidence here.
    """
    page = onboarding(HUB, PROMPT, "0.59.0", True)

    assert "succeeds" in page
    assert "agent-inbox --version" in page


def test_an_older_interpreter_is_diagnosed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Old:
        major, minor = 3, 13

        def __getitem__(self, item: slice) -> tuple[int, int]:
            return (3, 13)

    monkeypatch.setattr("sys.version_info", _Old())

    said = staleness.python_is_too_old()

    assert "3.13" in said
    assert "3.14" in said
    assert "silently" in said, "it does not warn that an install will appear to work"


def test_a_current_interpreter_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The paired positive. A diagnosis that always fires is a line nobody reads."""
    assert staleness.python_is_too_old() == ""


def test_an_unreadable_floor_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent metadata is an odd install, not a diagnosis worth inventing."""
    monkeypatch.setattr(staleness, "python_floor", lambda: "")

    assert staleness.python_is_too_old() == ""
