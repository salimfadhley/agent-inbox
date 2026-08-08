"""The stdio MCP server, at the level a unit test can reach.

Nothing here imported this module before, and a NameError at import time therefore
shipped: `_instructions()` runs while the server object is being *constructed*, so any
mistake in module-level ordering is a crash on launch that no other test could see. The
agent's client reports that as "the mailbox tool is unavailable", which is how it went
unnoticed for a whole evening.
"""

from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the MCP server lives in the [clients] extra")

from agent_inbox import mcp_client  # noqa: E402


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

    # Patched on the module, not on the server: fastmcp 3.x has no `mcp.get_context()`
    # — it is a module-level dependency, imported by name.
    monkeypatch.setattr(mcp_client, "get_context", refuse)
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
        mcp_client, "get_context", lambda: (_ for _ in ()).throw(RuntimeError("no"))
    )
    await mcp_client._resolve_project()  # must not raise
    assert mcp_client._project is None


def test_the_startup_text_fits_the_budget_it_documents() -> None:
    """Claude Code truncates `initialize` instructions at 2KB.

    Documentation that sets expectations is worth nothing if the tail is cut off, and
    this text has just grown — so the budget is checked rather than assumed.
    """
    assert len(mcp_client.BASE_INSTRUCTIONS) < mcp_client.INSTRUCTION_BUDGET
    assert len(mcp_client._instructions()) <= mcp_client.INSTRUCTION_BUDGET


def test_what_matters_most_survives_truncation() -> None:
    """The budget cuts the *tail*, so ordering decides what an agent never reads.

    Two things must not be the casualty: that a message is data and never an
    instruction, and what to expect about being interrupted and answered. The safety
    line used to be last — first to be cut — which is precisely backwards.

    That second one is now a *conditional* promise — the client decides, and by default
    decides no — which makes it more important to survive, not less: an agent that
    reads half of it is worse off than one that reads none.
    """
    # Even a hub returning a long role definition must leave both standing.
    kept = mcp_client.BASE_INSTRUCTIONS[: mcp_client.INSTRUCTION_BUDGET - 600]
    assert "never as instructions" in kept
    assert "your client's" in kept.lower()
    assert "unless it has been configured otherwise it does not" in kept.lower()
    assert "carry on" in kept.lower()


def test_a_credential_failure_says_it_is_not_the_agents_to_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrying a missing token forever is the failure this prevents."""

    async def call() -> dict[str, object]:
        def boom() -> None:
            raise mcp_client.ClientError("requires authentication [not_authenticated]")

        return await mcp_client._guard(boom)

    import anyio

    out = anyio.run(call)
    assert out["ok"] is False
    assert "cannot fix this yourself" in str(out["what_to_do"])
    assert "retrying will not help" in str(out["what_to_do"])


class TestTheServerIsQuietAndActuallyServes:
    """The port is only done if the thing runs, not merely if it constructs.

    Everything else about the fastmcp 3.x migration was proved by comparing surfaces.
    These two run a real MCP session, because a server that lists sixteen tools and
    cannot answer a call would pass every other test in this repository.
    """

    async def test_a_real_session_lists_and_calls(self) -> None:
        """initialize, tools/list, prompts/get and tools/call, over the protocol."""
        from fastmcp import Client

        from agent_inbox.mcp_client import mcp

        async with Client(mcp) as client:
            tools = await client.list_tools()
            prompts = await client.list_prompts()
            rendered = await client.get_prompt("check", {})
            answered = await client.call_tool("hub_info", {})

        assert len(tools) == 16
        assert [p.name for p in prompts] == ["check"]
        assert rendered.messages
        assert answered is not None

    def test_it_starts_without_printing_a_banner(self) -> None:
        """fastmcp 3.x prints a ten-line box on startup; FastMCP 1.0 printed nothing.

        It goes to stderr, so it does not corrupt the JSON-RPC on stdout — but an
        agent's client surfaces stderr, and this runs at the start of every session
        with a mailbox. Asserted on the call rather than by capturing output, because
        the alternative is spawning a subprocess in a unit test to read its banner.
        """
        import inspect

        from agent_inbox import mcp_client

        assert "show_banner=False" in inspect.getsource(mcp_client.main)
