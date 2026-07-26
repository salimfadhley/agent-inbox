"""The new package's boundaries.

Small, but not vacuous: the clean-slate rule is a decision, and a decision nobody
checks is a decision that erodes. `agent_mailbox_old` is deliberately still installed
and importable — which is exactly why an accidental dependency on it would be easy to
introduce and invisible until the old package is deleted.
"""

from __future__ import annotations

import pkgutil
from importlib.metadata import version
from pathlib import Path

import agent_mailbox


def test_package_reports_a_version() -> None:
    assert agent_mailbox.__version__


def test_the_version_is_read_from_the_real_distribution_name() -> None:
    """The distribution is `agent-inbox`; the import package is `agent_mailbox`.

    Looking up the wrong one does not raise — `__version__` quietly becomes the
    `0.0.0.dev0` fallback and stays there. That matters more than it used to: the
    onboarding prompt asks every arriving agent to compare this number against the
    hub's, so a silent 0.0.0 would tell all of them to reinstall, every session,
    forever. Cheap to pin, invisible if it breaks.
    """
    assert agent_mailbox.__version__ == version("agent-inbox")
    assert agent_mailbox.__version__ != "0.0.0.dev0", "metadata lookup fell back"


def test_new_package_never_imports_the_superseded_one() -> None:
    """We are starting from scratch, not refactoring the old implementation.

    Checked by source text rather than by import, so it catches a reference even
    before it would fail at runtime.
    """
    root = Path(agent_mailbox.__file__).parent
    offenders: list[str] = []
    for module in pkgutil.walk_packages([str(root)], prefix="agent_mailbox."):
        source = Path(module.module_finder.path) / f"{module.name.split('.')[-1]}.py"  # type: ignore[union-attr]
        if source.is_file() and "agent_mailbox_old" in source.read_text():
            offenders.append(module.name)
    assert not offenders, f"new code must not reference the old package: {offenders}"
