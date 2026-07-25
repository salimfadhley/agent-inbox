"""The wake is a client-side concern; the hub must not know it exists.

NFR-001 / SC-006 (mission 0017) and ADR 0011: every wake mechanism is a client-side
adapter. The hub and the messaging engine stay harness-agnostic — no code there may name
a hook, a wake, a Claude Code event, or a push channel. This is the same discipline the
auth boundary uses (see ``test_auth_api.py``): a structural test, so a well-meaning edit
that leaks a harness concept into the hub fails loudly instead of eroding ADR 0005.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_mailbox import api as api_module

#: Hub / engine modules — the harness-agnostic core. None of these may mention the wake.
_HUB_MODULES = (
    "rules",
    "mailbox",
    "house",
    "store",
    "sqlite_store",
    "records",
    "serve",
    "api",
    "prompts",
)

#: Tokens that betray a harness/wake concept. Word-bounded so a token won't match a
#: substring in an unrelated identifier by accident.
_FORBIDDEN = re.compile(
    r"\b("
    r"wake[_-]?check|wake_response|hookconfig|"
    r"SessionStart|UserPromptSubmit|"
    r"claude[_ -]?code|asyncRewake|additionalContext"
    r")\b",
    re.IGNORECASE,
)


def test_the_hub_never_names_the_wake() -> None:
    src = Path(api_module.__file__).parent
    offenders: dict[str, list[str]] = {}
    for name in _HUB_MODULES:
        path = src / f"{name}.py"
        hits = sorted({m.group(0) for m in _FORBIDDEN.finditer(path.read_text())})
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"hub/engine modules mention a harness/wake concept (ADR 0011): {offenders}"
    )


def test_the_wake_lives_only_client_side() -> None:
    # Sanity check the other direction: the wake code exists where it belongs, so the
    # test above guards something real rather than passing because no name is in use.
    src = Path(api_module.__file__).parent
    assert (src / "wake.py").exists()
    assert (src / "hookconfig.py").exists()
