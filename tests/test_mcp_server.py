"""The stdio MCP server, at the level a unit test can reach.

Nothing here imported this module before, and a NameError at import time therefore
shipped: `_instructions()` runs while the server object is being *constructed*, so any
mistake in module-level ordering is a crash on launch that no other test could see. The
agent's client reports that as "the mailbox tool is unavailable", which is how it went
unnoticed for a whole evening.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the MCP server lives in the [clients] extra")

from agent_mailbox import mcp_client  # noqa: E402


def test_the_module_imports_and_builds_its_server() -> None:
    """Importing it is the whole test: construction calls `_instructions()`."""
    assert mcp_client.mcp is not None
    assert mcp_client.mcp.name


def test_startup_instructions_do_not_claim_a_state_they_cannot_know(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`initialize` is answered before the project can be resolved.

    Roots can only be requested once that handshake is done, so a perfectly configured
    session reaches the unconfigured branch. Telling an agent at startup that it has no
    mailbox is a thing it will believe and not check again.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AGENT_MAILBOX_HUB", raising=False)
    monkeypatch.delenv("AGENT_MAILBOX_NAME", raising=False)
    text = mcp_client._instructions()
    assert "not configured" not in text.lower().split("call `ping`")[0]
    assert "ping" in text


async def test_an_explicit_project_is_not_overridden_by_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--project` exists for clients offering neither roots nor a known name.

    Having been told where it is, the server must not then ask — and must certainly not
    overwrite the answer with whatever a client happens to say.
    """

    def refuse() -> None:
        raise AssertionError("asked the client despite being told")

    monkeypatch.setattr(mcp_client.mcp, "get_context", refuse)
    monkeypatch.setattr(mcp_client, "_project", tmp_path)
    monkeypatch.setattr(mcp_client, "_roots_asked", True)

    await mcp_client._resolve_project()

    assert mcp_client._project == tmp_path


async def test_asking_survives_a_client_that_offers_no_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client may decline to answer, and that is not an error.

    Falling back to the working directory is what keeps clients that spawn the server
    in place — which is most of them — working exactly as before.
    """
    monkeypatch.setattr(mcp_client, "_roots_asked", False)
    monkeypatch.setattr(mcp_client, "_project", None)
    monkeypatch.setattr(
        mcp_client.mcp, "get_context", lambda: (_ for _ in ()).throw(RuntimeError("no"))
    )
    await mcp_client._resolve_project()  # must not raise
    assert mcp_client._project is None
