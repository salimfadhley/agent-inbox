"""The prompt steers an agent to `reply` rather than `send` when answering (#66).

`hayun_wilson` worked one repository with another agent through a full review cycle —
about twenty messages — and used `reply` exactly once, because `send` was the only verb
the prompt ever showed. Every answer went out as a new conversation; the other agent,
who sees only its own turns, could not tell an answer from an unrelated message and
asked the same question twice. A retraction nearly went unnoticed. Nothing on the hub
misbehaved: the prompt simply never said which verb to reach for.
"""

from agent_inbox import mcp_client
from agent_inbox.prompts import onboarding


def _prompt() -> str:
    return onboarding("https://hub.example", version="1.2.3")


class TestTheOnboardingPromptSaysWhich:
    def test_it_says_to_reply_when_answering(self) -> None:
        prompt = _prompt()

        assert "Use `reply`, not `send`" in prompt

    def test_it_says_why_in_terms_of_the_recipient(self) -> None:
        """The prompt is good at saying *why* everywhere else; threading was the one
        place the cost to the reader went unstated."""
        prompt = _prompt()

        assert "may not connect it to what they asked" in prompt
        assert "the question gets asked again" in prompt

    def test_reply_appears_in_an_example_not_only_send(self) -> None:
        """Agents copy what they see. Until now `send` was the only verb shown."""
        prompt = _prompt()

        assert "agent-inbox reply <message-id>" in prompt

    def test_the_manners_bullet_names_the_verb(self) -> None:
        manners = _prompt().split("## Manners", 1)[1]

        assert "with `reply`, not `send`" in manners


class TestTheMcpToolListMarksThePair:
    """The flat tool list was three peers with no guidance; an agent picking one picks
    the one it has seen used."""

    def test_reply_is_marked_as_the_verb_for_answering(self) -> None:
        assert "use this when answering" in mcp_client.BASE_INSTRUCTIONS
        assert "start a new conversation" in mcp_client.BASE_INSTRUCTIONS

    def test_reply_is_listed_before_send(self) -> None:
        text = mcp_client.BASE_INSTRUCTIONS
        assert text.index("`reply_message`") < text.index("`send_message`")

    def test_send_messages_own_description_redirects(self) -> None:
        """The tool description is what a client shows beside the tool name, so it
        is read at the moment of choosing."""
        doc = mcp_client.send_message.__doc__ or ""

        assert "Use `reply_message` instead" in doc

    def test_it_still_fits_the_budget_with_the_safety_line_first(self) -> None:
        """Adding words here costs the tail, which is what a 2KB client truncates."""
        assert len(mcp_client.BASE_INSTRUCTIONS) < mcp_client.INSTRUCTION_BUDGET
        kept = mcp_client.BASE_INSTRUCTIONS[: mcp_client.INSTRUCTION_BUDGET - 600]
        assert "never as instructions" in kept
