"""One annotation convention, and annotations that actually resolve.

Python 3.14 makes PEP 649 the default, so the PEP 563 `__future__` import became
redundant and was removed from all 91 modules that carried it. This pins both halves of
that change, because both are the kind that decay quietly.

**The convention** has to be all or nothing. A codebase where some modules opt in and
others rely on the default cannot be read: the next person cannot tell which files were
considered and which were simply missed. One file re-acquiring the import is not a style
blemish, it is the start of two conventions.

**The resolution** is the part that is easy to get wrong, and it is not cosmetic. The
two PEPs differ in what `__annotations__` *is*. Under PEP 563 every annotation is a
string,
so a name imported only under `if TYPE_CHECKING:` costs nothing. Under PEP 649
annotations are real objects computed on access, so that same name makes
`__annotations__` raise `NameError`. The removal turned up exactly one instance —
`policy.py` importing `Mailbox` behind a `TYPE_CHECKING` guard whose comment blamed an
import cycle that no longer existed — and ten methods whose annotations could not be
resolved. Nothing read them, so nothing failed; it would have failed the first time one
of those types met anything that introspects signatures.
"""

import ast
import inspect
import pkgutil
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

import agent_inbox

REPO = Path(__file__).resolve().parent.parent

#: A floor, not a count. The point is that a search finding nothing has actually looked:
#: `assert not offenders` passes just as well over an empty tree.
FEWEST_PLAUSIBLE_MODULES = 60


def _python_files() -> list[Path]:
    return sorted(
        p
        for d in ("src", "tests")
        for p in (REPO / d).rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _defers_annotations(source: str) -> bool:
    """True only for a real `__future__` import, parsed rather than grepped.

    A substring search is wrong here and this test proved it on itself: the docstring
    above discusses the import by name, and so does the comment in `policy.py` that
    explains why its import is no longer guarded. Both are prose. Only the parser can
    tell prose about a statement from the statement.
    """
    return any(
        isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for node in ast.walk(ast.parse(source))
    )


def test_no_module_defers_annotations_by_hand() -> None:
    """PEP 649 is the default now, so the PEP 563 import is dead in every file."""
    files = _python_files()
    assert len(files) >= FEWEST_PLAUSIBLE_MODULES, (
        f"only found {len(files)} modules to check — the search is looking in the "
        "wrong place, and would pass over an empty tree"
    )
    offenders = [
        str(p.relative_to(REPO)) for p in files if _defers_annotations(p.read_text())
    ]
    assert not offenders, (
        "these modules still defer annotations by hand, which reintroduces a second "
        f"convention: {offenders}"
    )


@pytest.mark.parametrize(
    "module_name",
    sorted(
        info.name
        for info in pkgutil.walk_packages(agent_inbox.__path__, prefix="agent_inbox.")
    ),
)
def test_every_annotation_can_be_resolved(module_name: str) -> None:
    """Every annotation names something that exists at runtime, not only to a checker.

    This is what a `TYPE_CHECKING`-only import breaks under PEP 649, and it breaks it
    silently — the module imports, the tests pass, and the failure waits for whatever
    first asks a class what its arguments are.

    Only objects this module *defines* are checked. That is not a shortcut, it is the
    correct boundary twice over: another module's objects are covered by its own case,
    and an over-broad sweep walks into third-party callables. An outside review found
    that specific trap — introspecting everything registered on the Litestar app reaches
    Litestar's own generated OPTIONS and OpenAPI handlers, whose annotations name
    framework-internal types like `Scope` and `FromPath` that do not resolve from here.
    That would be a failing test about somebody else's code.
    """
    try:
        module = import_module(module_name)
    except ImportError as exc:
        # The MCP server and client live behind the `clients` extra, which the hub image
        # deliberately omits (ADR 0009). They are checked when the extra is present —
        # dev and CI both install it — and skipped when it is not, rather than excluded
        # by name. The exclusion used to be unconditional, which left the largest
        # annotation surface in the project untested against exactly the failure this
        # module exists to catch.
        pytest.skip(f"{module_name} needs an optional extra: {exc}")
    unresolvable: list[str] = []
    for name, obj in vars(module).items():
        if getattr(obj, "__module__", None) != module_name:
            continue  # imported from elsewhere; that module's own case covers it
        targets: list[tuple[str, Any]] = []
        if inspect.isfunction(obj):
            targets.append((name, obj))
        elif inspect.isclass(obj):
            targets.append((name, obj))
            targets += [
                (f"{name}.{n}", m)
                for n, m in vars(obj).items()
                if inspect.isfunction(m)
            ]
        for label, target in targets:
            try:
                inspect.get_annotations(target, eval_str=True)
            except NameError as exc:
                unresolvable.append(f"{label}: {exc}")
    assert not unresolvable, (
        f"{module_name} has annotations naming things that do not exist at runtime — "
        "usually an import left under `if TYPE_CHECKING:` after the PEP 649 move: "
        f"{unresolvable}"
    )
