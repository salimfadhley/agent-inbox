"""A client says when it is older than its hub — issue #14.

`ludmila_coe` ran a command that had shipped and got `No such command`. Its CLI was
0.26.0
against a 0.32.0 hub, and nothing had told it. The error was true and useless: a capable
agent reasonably concluded the feature had not shipped.

The comparison already existed and reached the MCP server only. These tests are about
the
direction of the answer and about **silence**, which is the part easy to get wrong.
"""

from agent_inbox import __version__, staleness


class TestWhichWayRound:
    def test_a_newer_hub_means_this_client_is_behind(self) -> None:
        assert staleness.standing("999.0.0") == "behind"

    def test_an_older_hub_means_the_hub_is_behind(self) -> None:
        """A different problem with a different owner. Upgrading the client fixes
        nothing, so the two cannot share a message."""
        assert staleness.standing("0.0.1") == "ahead"

    def test_the_same_version_is_not_a_finding(self) -> None:
        assert staleness.standing(__version__) is None


class TestSilenceIsTheDefault:
    """FR-007. A line on every healthy run is a line nobody reads, and `doctor` is read
    precisely when something is already wrong."""

    def test_no_version_at_all_says_nothing(self) -> None:
        """Absent is not older. A hub that reports no version is not evidence."""
        assert staleness.standing(None) is None
        assert staleness.standing("") is None

    def test_an_unreadable_version_says_nothing(self) -> None:
        """Rather than guessing, or raising — a staleness check that crashes is worse
        than one that is occasionally quiet."""
        assert staleness.standing("not-a-version") is None

    def test_a_development_version_still_compares(self) -> None:
        """hatch-vcs produces `0.26.1.dev23+g1a4020368` between releases, and a strict
        parser would refuse it."""
        assert staleness.standing("999.0.0.dev1+gabc123") == "behind"


class TestTheNoticeItself:
    def test_it_names_both_versions_and_the_command(self) -> None:
        """FR-002: a warning that does not name the fix leaves the reader where it found
        them."""
        staleness.reset()
        staleness.note_hub_version("999.0.0")
        message = staleness.notice() or ""
        assert "999.0.0" in message
        assert __version__ in message
        assert "uv tool install" in message
        staleness.reset()

    def test_it_explains_the_symptom_the_reader_will_have_seen(self) -> None:
        """The sentence that would have saved the original report: tools added since
        your version *look like they do not exist*."""
        staleness.reset()
        staleness.note_hub_version("999.0.0")
        assert "do not exist" in (staleness.notice() or "")
        staleness.reset()

    def test_it_states_rather_than_instructs(self) -> None:
        """Deliberate: a notice reading "you must upgrade" invites an agent to start
        doing package management in the middle of somebody else's task."""
        staleness.reset()
        staleness.note_hub_version("999.0.0")
        message = (staleness.notice() or "").lower()
        assert "you must" not in message
        assert "you should" not in message
        staleness.reset()

    def test_nothing_to_say_when_level(self) -> None:
        staleness.reset()
        staleness.note_hub_version(__version__)
        assert staleness.notice() is None
