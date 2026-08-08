"""A dependency we import a *removed* API from must be bounded (found 2026-08-08).

`mcp` 2.0.0 deleted `mcp.server.fastmcp`. Not renamed, not deprecated — `FastMCP`
appears nowhere in the distribution. Our declared range was `>=1.12` with no upper
bound, so `uv tool install "agent-inbox[clients]"` — the command in our own onboarding
prompt — began resolving to it, and produced a client whose MCP server raised on import.

The suite could not see it, and that is the part worth a test rather than a comment.
`uv.lock` pins the working version, so every gate passed against 1.28.1 while a fresh
install from PyPI got 2.0.0. **A lockfile makes a project immune to the break it is
shipping**, which is a category of defect this repository is otherwise good at catching.

So this asserts the *declaration*, never the installed version. Checking what is
installed would pass for the same reason the rest of the suite did.
"""

import tomllib
from pathlib import Path

import pytest

#: Imports whose module was removed by a later major of the distribution providing it.
#: Each entry is (distribution, module we import, the major that removed it).
#:
#: Deliberately hand-written and short. This is not a general dependency auditor — it is
#: the list of places where we depend on something a maintainer has already deleted, and
#: it should stay small enough that adding to it feels like an event.
FRAGILE = ((("mcp"), "mcp.server.fastmcp", 2),)


def _requirements() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    extras = data["project"].get("optional-dependencies", {})
    return [
        *data["project"].get("dependencies", []),
        *(r for v in extras.values() for r in v),
    ]


@pytest.mark.parametrize(("distribution", "module", "removed_in"), FRAGILE)
def test_a_removed_api_is_bounded_below_the_major_that_removed_it(
    distribution: str, module: str, removed_in: int
) -> None:
    """The bug, as a rule. We import `module`; the distribution deleted it in
    `removed_in`; therefore the declared range must exclude that major."""
    named = [
        r for r in _requirements() if r.split("[")[0].split(">")[0] == distribution
    ]

    assert named, f"nothing declares {distribution}, but something imports {module}"
    for requirement in named:
        assert f"<{removed_in}" in requirement, (
            f"{requirement!r} permits {distribution} {removed_in}.x, which removed "
            f"{module}. An install resolving there gets a client that raises on import."
        )


def test_we_still_import_the_thing_the_bound_exists_for() -> None:
    """The paired positive, and the removal condition made executable.

    The cap is debt. When `mcp_client` is ported to the 2.x server API this import
    disappears, and at that moment this test fails and says so — which is the signal to
    drop the bound rather than leave it sitting there as a resting place, which the
    charter forbids.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "agent_inbox" / "mcp_client.py"
    ).read_text()

    assert "from mcp.server.fastmcp import" in source, (
        "mcp_client no longer imports the removed API — drop the `<2` bound on "
        "mcp[cli] in pyproject.toml, and this test with it"
    )
