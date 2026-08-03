"""The search filter — WP01 of `agent-visible-mail-search-01KYG9MZ`.

Pure, so these are literals and no database. The rules live here precisely so the
expensive mistakes — a thread-visibility leak in production, expiry deleting live
conversations — can be reviewed by reading.

**Every disclosure test here shares its fixture with the positive that mirrors it.** A
bystander finding nothing proves nothing unless the same mailbox, in the same test file,
demonstrably contains something for somebody. That shape has already cost this project
twice.
"""

import pytest

from agent_inbox import rules
from agent_inbox.records import ObjectRecord

LUDMILA = "ludmila_coe"
PABLO = "pablo_fantomas"
JED = "jed_smith"
ROSEMARY = "rosemary_nasrin"

EVERYONE_HERE = (LUDMILA, PABLO, JED, ROSEMARY)
NO_GROUPS: dict[str, frozenset[str]] = {}


def note(
    ident: str,
    frm: str,
    to: tuple[str, ...],
    content: str,
    *,
    summary: str | None = None,
    published: str = "2026-08-01T10:00:00Z",
    in_reply_to: str | None = None,
) -> ObjectRecord:
    return ObjectRecord(
        id=ident,
        attributed_to=frm,
        to=to,
        content=content,
        summary=summary,
        published=published,
        in_reply_to=in_reply_to,
    )


#: One mailbox, used by both halves of every disclosure test below.
#:
#: `open-1` opens a thread to Pablo and Jed. `private-2` is Ludmila's reply to Pablo
#: alone — a later turn of the same thread that Jed is not party to. Rosemary is on
#: neither, and is the outsider. This is scenario 7, the exact shape that leaked in
#: production.
#:
#: **The opener names its recipients rather than addressing `everyone`.** An earlier
#: draft used a broadcast, which made Rosemary a recipient too — so the tests that
#: called her an outsider were asserting against a mailbox where she was not one, and
#: three of them failed for that reason. A fixture that does not mean what its comment
#: says is the whole failure mode these tests exist to avoid.
FIXTURE = (
    note(
        "open-1",
        LUDMILA,
        (PABLO, JED),
        "the retry queue is flaky",
        summary="flaky retries",
    ),
    note(
        "private-2",
        LUDMILA,
        (PABLO,),
        "between us, the flaky retries are my fault",
        summary="Re: flaky retries",
        published="2026-08-01T11:00:00Z",
        in_reply_to="open-1",
    ),
    note(
        "direct-3",
        JED,
        (ROSEMARY,),
        "the console needs a favicon",
        summary="unrelated",
        published="2026-08-01T12:00:00Z",
    ),
)


def find(caller: str, query: str, objects=FIXTURE, **kw):
    return rules.search(objects, caller, query, EVERYONE_HERE, NO_GROUPS, **kw)


def ids(matches) -> list[str]:
    return [m.record.id for m in matches]


class TestVisibilityDecidesFirst:
    """FR-006, FR-007, C-001, C-002 — the requirement this package exists for."""

    def test_a_party_to_the_private_turn_finds_it(self) -> None:
        """The positive half. Without it the negatives below prove nothing."""
        matches, _ = find(PABLO, "flaky")
        assert ids(matches) == ["private-2", "open-1"], (
            "Pablo received both turns and must see both"
        )

    def test_a_bystander_on_the_thread_does_not(self) -> None:
        """Jed got the broadcast and nothing after it. **Scenario 7.**

        Same fixture, same query, same instant as the test above — the only difference
        is who is asking. That is what makes this a disclosure test rather than a test
        that the mailbox was empty.
        """
        matches, _ = find(JED, "flaky")
        assert ids(matches) == ["open-1"], "a private reply reached a bystander"

    def test_a_stranger_to_the_thread_finds_nothing(self) -> None:
        """Rosemary was on neither turn. Forbidden and absent are the same answer."""
        matches, truncated = find(ROSEMARY, "flaky")
        assert matches == () and truncated is False

    def test_the_sender_finds_their_own_outgoing_mail(self) -> None:
        """`is_party_to` covers sent as well as received — FR-005.

        `direct-3` went from Jed to Rosemary; nobody delivered it to Jed, so `unread`
        would never show it. He wrote it, and he can find it.
        """
        matches, _ = find(JED, "favicon")
        assert ids(matches) == ["direct-3"], "Jed cannot find what Jed sent"

    def test_delivered_to_is_not_enough_for_the_private_turn(self) -> None:
        """The bystander's silence is about *this* turn, not about the word.

        Jed matches `flaky` in the opener, so the query is not the thing excluding him
        from `private-2` — his not being party to it is.
        """
        assert ids(find(JED, "flaky")[0]) == ["open-1"]
        assert "flaky" in FIXTURE[1].content, "the private turn must contain the term"


class TestSnippets:
    """FR-010, NFR-002 — and the disclosure that would look like formatting."""

    def test_a_snippet_comes_from_its_own_message_only(self) -> None:
        """The private reply's text must never appear in the bystander's snippet."""
        matches, _ = find(JED, "flaky")
        assert len(matches) == 1
        assert "my fault" not in matches[0].snippet, (
            "a snippet carried text from a turn the caller cannot see"
        )

    def test_it_is_bounded(self) -> None:
        long = note("long-1", LUDMILA, (JED,), "x" * 5000 + " needle " + "y" * 5000)
        matches, _ = find(JED, "needle", objects=(long,))
        assert len(matches[0].snippet) <= rules.SNIPPET_CHARS + 2, "unbounded snippet"

    def test_it_shows_why_it_matched(self) -> None:
        long = note("long-2", LUDMILA, (JED,), "x" * 5000 + " needle " + "y" * 5000)
        matches, _ = find(JED, "needle", objects=(long,))
        assert "needle" in matches[0].snippet, "the snippet omitted the match itself"

    def test_a_subject_only_match_still_gets_a_snippet(self) -> None:
        subj = note("subj-1", LUDMILA, (JED,), "body says nothing", summary="deploys")
        matches, _ = find(JED, "deploys", objects=(subj,))
        assert matches[0].snippet.startswith("body says nothing")


class TestBounds:
    """NFR-001 — a contract, not a tuning parameter."""

    @staticmethod
    def _many(n: int) -> tuple[ObjectRecord, ...]:
        return tuple(
            note(
                f"m-{i:03d}",
                LUDMILA,
                (JED,),
                f"widget number {i}",
                published=f"2026-08-01T{i // 60:02d}:{i % 60:02d}:00Z",
            )
            for i in range(n)
        )

    def test_the_default_is_ten(self) -> None:
        matches, truncated = find(JED, "widget", objects=self._many(40))
        assert len(matches) == rules.SEARCH_DEFAULT_LIMIT
        assert truncated is True, "a capped answer must say it was capped"

    def test_an_over_large_limit_is_capped_not_refused(self) -> None:
        matches, _ = find(JED, "widget", objects=self._many(100), limit=500)
        assert len(matches) == rules.SEARCH_MAX_LIMIT

    def test_truncated_is_false_when_everything_fits(self) -> None:
        matches, truncated = find(JED, "widget", objects=self._many(3))
        assert len(matches) == 3 and truncated is False

    def test_newest_first(self) -> None:
        matches, _ = find(JED, "widget", objects=self._many(5))
        assert ids(matches) == ["m-004", "m-003", "m-002", "m-001", "m-000"]


class TestFiltersOnlyNarrow:
    """FR-008. No filter may surface anything the unfiltered call would not."""

    def test_by_sender(self) -> None:
        matches, _ = find(PABLO, "flaky", sender=LUDMILA)
        assert ids(matches) == ["private-2", "open-1"]

    def test_a_sender_filter_cannot_widen(self) -> None:
        """Asking for Ludmila's mail as Rosemary still returns nothing."""
        assert find(ROSEMARY, "flaky", sender=LUDMILA)[0] == ()

    def test_by_time_window(self) -> None:
        matches, _ = find(PABLO, "flaky", since="2026-08-01T10:30:00Z")
        assert ids(matches) == ["private-2"]

    def test_until_excludes_later_mail(self) -> None:
        matches, _ = find(PABLO, "flaky", until="2026-08-01T10:30:00Z")
        assert ids(matches) == ["open-1"]


class TestTheQuery:
    """FR-009, and the refusal that keeps search from meaning 'everything'."""

    @pytest.mark.parametrize("empty", ["", "   ", "\t\n"])
    def test_an_empty_query_returns_nothing(self, empty: str) -> None:
        matches, truncated = find(PABLO, empty)
        assert matches == () and truncated is False, (
            "an empty query returned mail; search must not mean 'everything'"
        )

    def test_matching_is_case_insensitive(self) -> None:
        assert ids(find(JED, "FLAKY")[0]) == ["open-1"]

    def test_it_matches_the_subject_as_well_as_the_body(self) -> None:
        only_subject = note(
            "s-1", LUDMILA, (JED,), "nothing here", summary="deployment"
        )
        assert ids(find(JED, "deployment", objects=(only_subject,))[0]) == ["s-1"]
