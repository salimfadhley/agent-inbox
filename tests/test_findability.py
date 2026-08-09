"""A description exists so somebody can find you, and the prompt has to say so.

The owner's problem, in his words: an issued name is *literally just an address* that
happens to be rendered in human-sounding words, and no human remembers one. So when a
human wants to reach an agent they do not say its name — they say "ask whoever does the
deployments", and the agent they said it to has to work out who that is.

It works out who by reading self-descriptions. That makes `purpose` the load-bearing
field on this hub, because it is what `Renderer.actor` renders as an actor's `summary`
— the one line a searcher sees.

**And the prompt used to teach every field except that one.** Its example set `project`,
`engine`, `host`, `offers` and `needs`, and never mentioned `purpose`. An agent that
followed it exactly ended up unfindable while believing it had described itself, which
is worse than an empty profile: it looks done.

The second half is newer and is the owner's addition. An agent that has just been
pointed at a project may genuinely not know what it is for, and a guess written on day
one is a description that persists and misdirects. Asking the human is the correct
first move, and the prompt now says so in words the agent can use.
"""

import pytest

from agent_inbox.prompts import onboarding


@pytest.fixture
def prompt() -> str:
    """The rendered prompt, with line wrapping flattened.

    Asserted against normalised whitespace because the source wraps at 88 columns:
    "worse than\nnone" is the same sentence as "worse than none", and a test that
    could not see that would break every time somebody reflowed a paragraph — which
    teaches people to delete the test rather than read it.
    """
    return " ".join(onboarding("https://hub.example", version="1.2.3").split())


class TestThePromptTeachesTheFieldThatMakesYouFindable:
    def test_it_names_purpose(self, prompt: str) -> None:
        """The bug, stated. The example taught five fields and omitted the one that
        becomes your summary."""
        assert '"purpose"' in prompt

    def test_purpose_is_actually_what_a_searcher_reads(self) -> None:
        """The reason this matters, asserted against the renderer rather than trusted.

        If `summary` ever stops coming from `purpose`, the prompt above is teaching the
        wrong field again and this is what says so.
        """
        import asyncio

        from agent_inbox.mailbox import Mailbox
        from agent_inbox.store import InMemoryStore
        from agent_inbox.wire import Renderer

        async def described() -> str | None:
            mailbox = Mailbox(InMemoryStore(), hub_name="testhub")
            await mailbox.join("someone_here")
            await mailbox.update_profile(
                "someone_here", {"purpose": "I run the deployments"}
            )
            actor = await mailbox.whois("someone_here")
            assert actor is not None
            return Renderer("https://hub.example").actor(actor).summary

        assert asyncio.run(described()) == "I run the deployments"

    def test_it_explains_the_mechanism_rather_than_just_asking(
        self, prompt: str
    ) -> None:
        """ "Fill in your profile" is an instruction nobody prioritises. "This is how
        somebody reaches you when they cannot remember your name" is a reason."""
        section = prompt.split("## 5.", 1)[1]

        assert "cannot remember your name" in section or "remember your name" in section
        assert "reads these descriptions" in section

    def test_it_asks_for_words_a_human_would_use(self, prompt: str) -> None:
        """Resolution is a reader matching a request against descriptions, so a
        description phrased in job-title abstractions matches nothing anybody asks
        for."""
        section = prompt.split("## 5.", 1)[1]

        assert "findable" in section
        assert "nobody asks for one of those" in section


class TestAnAgentThatDoesNotKnowIsToldToAsk:
    def test_it_says_to_ask_the_human(self, prompt: str) -> None:
        """The owner's addition. An agent pointed at a project it has not worked in
        cannot describe itself honestly, and the prompt previously left it to guess."""
        section = prompt.split("## 5.", 1)[1]

        assert "If you do not know what you are for, ask" in section

    def test_it_supplies_the_question_to_ask(self, prompt: str) -> None:
        """A instruction to "ask your human" without the words is a instruction to
        compose something, which is where an agent invents a placeholder instead."""
        section = prompt.split("## 5.", 1)[1]

        assert "What sort of work am I here for" in section

    def test_it_says_why_guessing_is_worse_than_silence(self, prompt: str) -> None:
        """The load-bearing reason, and the one an agent needs in order to choose
        asking over filling something in: a wrong description does not fail quietly,
        it routes somebody's request to the wrong agent."""
        section = prompt.split("## 5.", 1)[1]

        assert "wrong description is worse than none" in section
        assert (
            "findable *as the wrong thing*" in section or "the wrong thing" in section
        )


class _Hub:
    """A hub answering the one question `_report_profile` asks."""

    def __init__(self, profile: object) -> None:
        self._profile = profile

    def whois(self, name: str) -> dict[str, object]:
        return {"preferredUsername": name, "profile": self._profile}


@pytest.fixture
def undescribed(capsys: pytest.CaptureFixture[str]) -> str:
    """What `doctor` actually prints to an agent with no description.

    Rendered rather than read out of the source: the note is built from adjacent
    string literals, so `inspect.getsource` sees the sentences broken at arbitrary
    points and a test reading it would fail on reformatting alone.
    """
    from agent_inbox.cli import _Notes, _report_profile

    notes = _Notes("note")
    _report_profile(_Hub({}), "igor_laszlo", "ok", notes)  # type: ignore[arg-type]
    notes.flush()
    return " ".join(capsys.readouterr().out.split())


class TestDoctorSaysTheSameThing:
    """Two surfaces telling an agent different things about the same field is how one
    of them ends up ignored. `doctor` is what an already-running agent sees; the prompt
    is what a new one reads."""

    def test_the_note_explains_findability_not_just_absence(
        self, undescribed: str
    ) -> None:
        assert "nobody can find you" in undescribed
        assert "an address, not a description" in undescribed

    def test_the_note_also_says_to_ask_rather_than_guess(
        self, undescribed: str
    ) -> None:
        assert "ask your human rather than guessing" in undescribed

    def test_it_still_says_staying_quiet_is_allowed(self, undescribed: str) -> None:
        """The paired positive, and the property #61 shipped with: this is a note, not
        a demand. An agent that has decided to say little has decided, and the point of
        the note is that the decision was made rather than defaulted into."""
        assert "legitimate" in undescribed
