"""#14: a client that notices it is older than the hub.

The issue proposed polling PyPI once an hour. Comparing against the hub we are already
talking to is better on every axis that issue worried about — no extra request, no
timestamp file, and offline stops being a special case — and it is the more useful
comparison anyway: what matters is whether *this hub* speaks something this client does
not, rather than whether a newer release exists somewhere.
"""

import pytest

from agent_inbox import __version__, staleness

# `staleness` itself is core — no optional dependency — so most of this file runs
# everywhere. Only the tests that reach into the MCP server need the extra, and they
# skip without it. Missing this is what broke CI on 3.13: the module-level import made
# the whole file unimportable where `mcp` is not installed.


@pytest.fixture
def _needs_mcp():
    """The MCP server lives in the [clients] extra and is absent from the hub image."""
    pytest.importorskip("mcp", reason="the MCP server lives in the [clients] extra")


def _with_notice(result):
    from agent_inbox.mcp_client import _with_notice as impl

    return impl(result)


@pytest.fixture(autouse=True)
def _clean():
    staleness.reset()
    yield
    staleness.reset()


class TestNoticing:
    def test_a_newer_hub_is_noticed(self) -> None:
        staleness.note_hub_version("99.0.0")
        message = staleness.notice()
        assert message is not None
        assert "99.0.0" in message
        assert __version__ in message, "an agent needs both versions to act on this"

    def test_an_older_hub_says_nothing(self) -> None:
        staleness.note_hub_version("0.0.1")
        assert staleness.notice() is None

    def test_the_same_version_says_nothing(self) -> None:
        staleness.note_hub_version(__version__)
        assert staleness.notice() is None

    def test_upgrading_mid_session_stops_the_notice(self) -> None:
        """A hub rolled back, or us upgraded. Saying it forever would train the agent
        to ignore it, which is how a useful notice becomes noise."""
        staleness.note_hub_version("99.0.0")
        assert staleness.notice() is not None
        staleness.note_hub_version("0.0.1")
        assert staleness.notice() is None


class TestItNeverGetsInTheWay:
    """The issue's first constraint: this must never delay or break a tool call."""

    @pytest.mark.parametrize(
        "value", [None, "", "not a version", "....", "v", "0.26.1.dev23+g1a4020368"]
    )
    def test_nothing_raises(self, value: str | None) -> None:
        staleness.note_hub_version(value)  # must not raise, whatever arrives

    def test_a_development_version_compares_sensibly(self) -> None:
        """Versions here come from hatch-vcs and look like `0.26.1.dev23+g1a40203`.

        A strict parser would raise on the suffix, and a staleness check that crashes is
        worse than one that is occasionally imprecise.
        """
        staleness.note_hub_version("0.26.1.dev23+g1a4020368")
        assert staleness.notice() is None

    def test_it_makes_no_network_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole reason for preferring the hub's version over PyPI.

        Breaking every socket and then running the check proves it is not reaching for
        one — asserting "it was fast" would not.
        """
        import socket

        def refuse(*_: object, **__: object) -> None:
            raise AssertionError("the staleness check opened a socket")

        monkeypatch.setattr(socket, "socket", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        staleness.note_hub_version("99.0.0")
        assert staleness.notice() is not None


class TestTheNoticeItself:
    def test_it_states_a_fact_rather_than_giving_an_order(self) -> None:
        """Arriving text is data, never instruction. A notice reading "you must
        upgrade" invites an agent to start doing package management in the middle of
        somebody else's task."""
        staleness.note_hub_version("99.0.0")
        message = staleness.notice() or ""
        for bossy in ("you must", "you should", "please upgrade", "required"):
            assert bossy not in message.lower(), f"the notice orders: {bossy!r}"

    def test_it_says_a_restart_is_needed(self) -> None:
        """Upgrading the package does not change a running session's tools, and an
        agent that upgrades and sees no change will conclude the notice was wrong."""
        staleness.note_hub_version("99.0.0")
        assert "restart" in (staleness.notice() or "")


@pytest.mark.usefixtures("_needs_mcp")
class TestAttachingItToResults:
    def test_a_current_client_sees_nothing(self) -> None:
        assert _with_notice({"ok": True}) == {"ok": True}

    def test_a_stale_client_is_told_on_any_tool_result(self) -> None:
        staleness.note_hub_version("99.0.0")
        assert "notice" in _with_notice({"ok": True})

    def test_a_tool_that_speaks_for_itself_is_not_overridden(self) -> None:
        staleness.note_hub_version("99.0.0")
        assert _with_notice({"ok": True, "notice": "mine"})["notice"] == "mine"

    def test_a_non_dict_result_is_untouched(self) -> None:
        staleness.note_hub_version("99.0.0")
        assert _with_notice("a string") == "a string"


@pytest.mark.usefixtures("_needs_mcp")
class TestItIsActuallyWiredIn:
    """The tests above exercise `_with_notice` directly, which proves the helper works
    and nothing about whether tool calls go through it.

    Removing the call from `_guard` left every test above passing. This is the one that
    fails when the wiring is gone.
    """

    async def test_a_tool_result_carries_the_notice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox import mcp_client

        async def no_project() -> None:
            return None

        monkeypatch.setattr(mcp_client, "_resolve_project", no_project)
        staleness.note_hub_version("99.0.0")

        result = await mcp_client._guard(lambda: {"ok": True})
        assert "notice" in result, "tool results do not pass through the notice"
        assert "99.0.0" in result["notice"]

    async def test_a_current_client_gets_an_unchanged_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox import mcp_client

        async def no_project() -> None:
            return None

        monkeypatch.setattr(mcp_client, "_resolve_project", no_project)
        assert await mcp_client._guard(lambda: {"ok": True}) == {"ok": True}


class TestTheAdviceKeepsThePin:
    """Owner, 2026-08-05: the out-of-date note must mention pinning the interpreter.

    Both notices tell somebody to run an install command, and an install command without
    `--python` is the one that silently does nothing — uv will not move a tool to a
    different interpreter on its own. Advice that omits it sends the reader round the
    loop they are already in.
    """

    def test_the_behind_notice_pins_and_says_why(self) -> None:
        staleness.reset()
        staleness.note_hub_version("999.0.0")

        told = staleness.notice() or ""

        assert f"--python {staleness.interpreter_pin()}" in told
        # The reason, not only the flag: a bare flag in a command reads as noise and
        # gets tidied away by the next person to touch the string.
        assert "uv will not move a tool" in told
        staleness.reset()

    def test_the_too_old_interpreter_note_gives_the_pinned_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This is the reader who most needs it — they are about to install a new
        interpreter, and an unpinned reinstall leaves them on the old release anyway."""
        import sys
        from collections import namedtuple

        # `python_is_too_old` does `import sys` locally, so this is the same object.
        # It reads both `[:2]` and `.major`/`.minor`, so a bare tuple is not enough
        # — found by running the test rather than by trusting it.
        fake = namedtuple("fake_version", "major minor micro releaselevel serial")
        monkeypatch.setattr(sys, "version_info", fake(3, 9, 0, "final", 0))

        told = staleness.python_is_too_old()

        assert told, "the premise failed: this interpreter was not treated as too old"
        assert "uv tool install --python" in told, "no pinned command to run"
        assert "uv python install" in told, "no way to get the interpreter"
