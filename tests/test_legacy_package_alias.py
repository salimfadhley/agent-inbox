"""`import agent_mailbox` must keep working, and must mean `agent_inbox`.

The package was renamed when the project finished becoming agent-inbox. Code written
before that — other people's scripts, a pinned MCP entry, an old notebook — still says
`agent_mailbox`, and the rename is ours rather than theirs.

The point of these tests is **identity, not merely importability**. A shim returning a
second module object with the same names would pass a naive "does it import" check and
still be wrong: two copies of a module are two copies of its module-level state, and
the divergence is invisible until something depends on it. The first attempt at this
shim had exactly that flaw — `agent_mailbox.cli.main is agent_inbox.cli.main` was
False.
"""

from __future__ import annotations

import sys

import agent_inbox
import agent_mailbox


def test_the_old_name_is_the_new_module() -> None:
    assert agent_mailbox is agent_inbox


def test_a_submodule_is_the_same_object_not_a_copy() -> None:
    from agent_mailbox.cli import main as old

    from agent_inbox.cli import main as new

    assert old is new
    assert sys.modules["agent_mailbox.cli"] is sys.modules["agent_inbox.cli"]


def test_a_nested_submodule_too() -> None:
    """Two levels down, where a naive finder is most likely to give up."""
    from agent_mailbox.auth.totp import current_code as old

    from agent_inbox.auth.totp import current_code as new

    assert old is new


def test_module_level_state_is_shared() -> None:
    """The reason identity matters, asserted directly rather than implied."""
    import agent_mailbox.client as old

    import agent_inbox.client as new

    assert old.CONFIG_NAME is new.CONFIG_NAME
    marker = object()
    old._alias_probe = marker  # type: ignore[attr-defined]
    assert getattr(new, "_alias_probe", None) is marker
    del old._alias_probe  # type: ignore[attr-defined]


def test_the_version_is_the_same_one() -> None:
    assert agent_mailbox.__version__ == agent_inbox.__version__


def test_importing_the_alias_twice_does_not_stack_finders() -> None:
    """A module can be re-imported; the finder must be installed once."""
    import importlib

    before = len(sys.meta_path)
    importlib.import_module("agent_mailbox")
    assert len(sys.meta_path) == before
