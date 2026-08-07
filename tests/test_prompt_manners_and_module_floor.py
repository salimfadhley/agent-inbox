"""Two prompt corrections that came out of the same afternoon (2026-08-07).

**The module floor.** The MCP registration invokes `python -m agent_inbox` while asking
the resolver for `>=0.35.0` — and `__main__.py` did not exist until 0.72.0. It never
bit, because `>=` resolves to the newest release and that one has it. That is luck,
not correctness: a lowest-resolution install, a constrained index or a lagging mirror
would all have produced `No module named agent_inbox.__main__`. The owner met exactly
that error by a different route, omitting `--python` so uv settled on 0.34.0.

**Manners.** Owner's request, same day. Almost every complaint on the hub has been
somebody left guessing, and an agent cannot cheaply ask another what is happening.
"""

import re

import pytest

from agent_inbox.prompts import onboarding
from agent_inbox.staleness import INSTALL_FLOOR, MODULE_FLOOR


@pytest.fixture
def prompt() -> str:
    return onboarding("https://hub.example", version="1.2.3")


class TestTheModuleCommandAsksForAVersionThatHasOne:
    def test_the_floor_is_at_least_where_main_appeared(self) -> None:
        """Asserted against the package rather than a literal: `__main__.py` is the
        thing being depended on, so its presence is what the number has to track."""
        import importlib.util

        assert importlib.util.find_spec("agent_inbox.__main__") is not None
        assert MODULE_FLOOR >= "0.72.0"

    def test_it_is_higher_than_the_install_floor(self) -> None:
        """The two answer different questions — "old enough to be a known-bad silent
        downgrade" and "new enough to be runnable as a module". Collapsing them back
        into one number is how this was wrong by 37 releases."""
        assert MODULE_FLOOR > INSTALL_FLOOR

    def test_every_module_invocation_carries_it(self, prompt: str) -> None:
        """The bug, stated. A registration that runs `python -m agent_inbox` while
        naming a floor without `__main__` is asking for a version that cannot do what
        it is about to be asked to do."""
        registrations = [
            block
            for block in re.findall(r"```[a-z]*\n(.*?)```", prompt, re.S)
            if "-m" in block and "agent_inbox" in block
        ]

        assert registrations, "precondition: the prompt registers the module somewhere"
        for block in registrations:
            assert MODULE_FLOOR in block, block

    def test_the_error_it_produces_is_explained(self, prompt: str) -> None:
        """It names no version, so a reader has no reason to suspect one. Recognising
        it is the whole value — the install is old, not broken."""
        assert "No module named agent_inbox.__main__" in prompt
        assert "It is an **old** one" in prompt


class TestManners:
    """Asserted on the substance, not the wording — each of these is a distinct thing
    an agent is being asked to do, and a section that lost one would still read fine."""

    def test_it_exists(self, prompt: str) -> None:
        assert "## Manners" in prompt

    def test_an_acknowledgement_must_carry_a_next_step(self, prompt: str) -> None:
        """The owner's call, 2026-08-07, resolving a real tension: rule one says always
        acknowledge, and the rest of this page says every message costs a recipient a
        turn. Requiring a next step bans the empty "ok" without permitting silence."""
        manners = prompt.split("## Manners", 1)[1]

        assert "Answer every request, and say what happens next" in manners
        assert '"ok"' in manners

    def test_it_asks_for_completion_to_be_reported(self, prompt: str) -> None:
        manners = prompt.split("## Manners", 1)[1]
        assert "Say when it is done" in manners

    def test_it_prefers_the_existing_thread(self, prompt: str) -> None:
        manners = prompt.split("## Manners", 1)[1]
        assert "Reply on the thread" in manners

    def test_it_says_a_refusal_beats_silence(self, prompt: str) -> None:
        """The rule that makes the other three safe to follow: without it, "answer
        every request" is a trap for anything an agent cannot or should not do."""
        manners = prompt.split("## Manners", 1)[1]
        assert "A refusal is an answer; silence is not" in manners

    def test_it_does_not_contradict_the_broadcast_advice(self, prompt: str) -> None:
        """Manners that told an agent to reply to everything, everywhere, would fight
        the standing rule that a broadcast costs every recipient a turn they cannot
        decline. Both must be in there, agreeing."""
        manners = prompt.split("## Manners", 1)[1]

        assert "not everyone" in manners
        assert "none of them can decline" in manners


class TestTheRegistrationIgnoresTheSurroundingProject:
    """`uv run` adopts the `requires-python` of whatever project it stands in, and an
    MCP server is launched from the directory the client happens to be working in.

    A project pinned to `>=3.11, <3.13` therefore refuses the interpreter we asked for,
    with an error naming the *project's* constraint — so it reads as the agent's machine
    being wrong when nothing about it is. Reported by the owner on 2026-08-07 and
    reproduced exactly: without the flag it fails, with it the module runs.

    This is the one of these three corrections that stops a working setup dead, rather
    than merely misleading somebody.
    """

    def test_every_uv_run_in_the_prompt_declines_the_project(self, prompt: str) -> None:
        """Asserted across all of them, not just the two registrations. A `uv run` added
        later without the flag would be broken in exactly the same way, and only on
        somebody else's machine."""
        invocations = [
            block
            for block in re.findall(r"```[a-z]*\n(.*?)```", prompt, re.S)
            if "uv run" in block
        ]

        assert invocations, "precondition: the prompt runs uv somewhere"
        for block in invocations:
            assert "--no-project" in block, block

    def test_the_codex_form_carries_it_too(self, prompt: str) -> None:
        """A separate assertion because it is a separate syntax — a TOML args array,
        which is exactly the kind of second spelling that gets updated late."""
        toml = prompt.split("[mcp_servers.agent-inbox]", 1)[1]

        assert '"--no-project"' in toml.split("```", 1)[0]

    def test_the_error_is_explained(self, prompt: str) -> None:
        """It names the project's own constraint and never mentions us, so a reader has
        no reason to connect it to the mailbox at all."""
        assert "incompatible" in prompt
        assert "nothing to do with us" in prompt
