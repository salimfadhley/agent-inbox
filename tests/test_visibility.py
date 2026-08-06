"""How findable an actor is — decided by the actor, and failing towards less exposure.

The asymmetry between writing and reading is the design, and it is what these tests are
mostly about: a *write* is refused by name, because coercing it would weaken a privacy
setting at the moment its owner was paying most attention; a *read* is forgiving,
because refusing to start over one bad row would take the hub down to protect one
actor's listing.
"""

import logging

import pytest

from agent_inbox import visibility
from agent_inbox.exceptions import UnknownActor
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

AGENT = "rosemary_nasrin"


@pytest.fixture
async def mailbox() -> Mailbox:
    made = Mailbox(InMemoryStore(), hub_name="testhub")
    await made.join(AGENT)
    return made


class TestTheDefault:
    def test_an_actor_that_never_set_it_is_normal(self) -> None:
        """Addressable but unlisted — and every actor that predates this field has it
        without doing anything."""
        assert visibility.read({}) is visibility.Visibility.NORMAL

    def test_a_profile_that_is_not_even_a_mapping_is_still_normal(self) -> None:
        assert visibility.read(None) is visibility.Visibility.NORMAL

    async def test_a_freshly_joined_actor_reads_as_normal(
        self, mailbox: Mailbox
    ) -> None:
        who = await mailbox.whois(AGENT)
        assert who is not None
        assert visibility.read(who.profile) is visibility.Visibility.NORMAL


class TestWritingIt:
    @pytest.mark.parametrize("level", ["local", "normal", "discoverable"])
    async def test_each_of_the_three_is_accepted(
        self, mailbox: Mailbox, level: str
    ) -> None:
        updated = await mailbox.update_profile(AGENT, {visibility.KEY: level})

        assert visibility.read(updated.profile).value == level

    async def test_it_round_trips_through_the_store(self, mailbox: Mailbox) -> None:
        """The paired positive for the whole file: a validator that rejected everything
        would satisfy every refusal test below."""
        await mailbox.update_profile(AGENT, {visibility.KEY: "discoverable"})

        who = await mailbox.whois(AGENT)
        assert who is not None
        assert visibility.read(who.profile) is visibility.Visibility.DISCOVERABLE

    @pytest.mark.parametrize("bad", ["public", "", "hidden", "LOCALE", None, 3])
    async def test_an_unknown_value_is_refused(
        self, mailbox: Mailbox, bad: object
    ) -> None:
        with pytest.raises(visibility.BadVisibility):
            await mailbox.update_profile(AGENT, {visibility.KEY: bad})

    async def test_a_refused_write_changes_nothing(self, mailbox: Mailbox) -> None:
        """The assertion that matters: "it raised" is not proof that the stored value
        survived, and a privacy setting silently weakened by a failed write is the worst
        outcome here."""
        await mailbox.update_profile(AGENT, {visibility.KEY: "local"})

        with pytest.raises(visibility.BadVisibility):
            await mailbox.update_profile(AGENT, {visibility.KEY: "public"})

        who = await mailbox.whois(AGENT)
        assert who is not None
        assert visibility.read(who.profile) is visibility.Visibility.LOCAL

    async def test_case_and_spacing_are_forgiven(self, mailbox: Mailbox) -> None:
        """Not a coercion — `  Discoverable ` is unambiguously one of the three, and
        refusing it would be pedantry rather than protection."""
        updated = await mailbox.update_profile(
            AGENT, {visibility.KEY: "  Discoverable "}
        )

        assert visibility.read(updated.profile) is visibility.Visibility.DISCOVERABLE

    async def test_a_profile_without_the_key_is_untouched(
        self, mailbox: Mailbox
    ) -> None:
        """Writing an unrelated profile must not require thinking about visibility."""
        await mailbox.update_profile(AGENT, {"project": "billing"})

        who = await mailbox.whois(AGENT)
        assert who is not None
        assert visibility.read(who.profile) is visibility.Visibility.NORMAL

    async def test_an_unknown_actor_is_still_unknown(self, mailbox: Mailbox) -> None:
        """The validation runs before the actor lookup, so check the lookup still
        happens — otherwise a stranger learns nothing about whether a name exists, but
        a caller with a valid value would get a different error from one without."""
        with pytest.raises(UnknownActor):
            await mailbox.update_profile("nobody_here", {visibility.KEY: "local"})


class TestReadingABadStoredValue:
    """FR-015. A value that should not be in the store is a fact about the store."""

    def test_it_does_not_raise(self) -> None:
        assert visibility.read({visibility.KEY: "nonsense"}) is visibility.FALLBACK

    def test_it_reads_as_the_safest_level_not_the_default(self) -> None:
        """The direction matters more than the behaviour. A value we cannot understand
        must never resolve to something *more* exposed than its owner may have chosen —
        so it is `local`, not `normal`."""
        got = visibility.read({visibility.KEY: "nonsense"})

        assert got is visibility.Visibility.LOCAL
        assert got is not visibility.DEFAULT

    def test_it_is_logged_rather_than_swallowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Silence would leave an operator with an actor quietly less reachable than it
        asked to be, and nothing to find when they went looking."""
        with caplog.at_level(logging.WARNING, logger="agent_inbox.visibility"):
            visibility.read({visibility.KEY: "nonsense"})

        assert any("visibility.unreadable" in r.getMessage() for r in caplog.records)

    def test_a_good_value_is_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """The paired negative: a warning on every read would be noise that hides the
        one that matters."""
        with caplog.at_level(logging.WARNING, logger="agent_inbox.visibility"):
            visibility.read({visibility.KEY: "discoverable"})

        assert not [r for r in caplog.records if "visibility" in r.getMessage()]
