"""Deprecated alias for :mod:`agent_inbox`.

The package was renamed when the project finished becoming ``agent-inbox``. This exists
so that ``import agent_mailbox``, and any submodule beneath it, keeps working for code
written before the move.

**A genuine alias, not a copy.** ``agent_mailbox.cli`` and ``agent_inbox.cli`` are
the same module object, so there is one copy of every module-level value. The obvious
one-liner — assigning this module to :mod:`agent_inbox` in ``sys.modules`` — aliases
only the top level: a later ``import agent_mailbox.cli`` finds ``cli.py`` through the
parent's path and imports it *again* under the old name, leaving two module objects
with separate state. Measured before this was written: ``agent_mailbox.cli.main is
agent_inbox.cli.main`` was ``False``. For a compatibility shim that is worse than no
shim, because the duplication is invisible.

So a finder maps the whole namespace instead, and every alias resolves to the module
already imported under the current name.

No deprecation warning is raised. The rename is ours, the caller did nothing wrong,
and a warning on every import of a working program is a cost with no action attached —
the prompt and the documentation already say which name is current.
"""

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from types import ModuleType
from typing import Any

_OLD = "agent_mailbox"
_NEW = "agent_inbox"


def _current_name(fullname: str) -> str:
    """``agent_mailbox.auth.totp`` → ``agent_inbox.auth.totp``."""
    return _NEW + fullname[len(_OLD) :]


class _AliasLoader(importlib.abc.Loader):
    """Hands back the module that already exists under the current name."""

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        return importlib.import_module(_current_name(spec.name))

    def exec_module(self, module: ModuleType) -> None:
        """Nothing to execute: the real module ran when it was first imported."""


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self, fullname: str, path: Any = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == _OLD or fullname.startswith(_OLD + "."):
            return importlib.util.spec_from_loader(fullname, _AliasLoader())
        return None


# Installed once. Re-importing this module must not stack finders.
if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())

import agent_inbox  # noqa: E402 - after the finder, so submodules resolve through it

sys.modules[__name__] = agent_inbox
