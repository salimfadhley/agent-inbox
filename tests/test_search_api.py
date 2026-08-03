"""Search over the wire — WP02 of `agent-visible-mail-search-01KYG9MZ`.

`tests/test_search_rules.py` proves the filter against literals. This proves the filter
is *wired in*: that the route calls it, that nothing in the request path widens what it
returned, and that searching leaves the mailbox exactly as it found it.

**The disclosure tests share one fixture with the positives that mirror them.** A
bystander finding nothing proves nothing unless the same hub, in the same test, has
something in it for somebody else. That shape has cost this project more than once, and
`AGENTS.md` records it as the failure mode to design against.
"""

from collections.abc import Iterator

import pytest
from litestar.testing import TestClient

from agent_inbox.api import IDENTITY_HEADER, build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"

LUDMILA = "ludmila_coe"
PABLO = "pablo_fantomas"
JED = "jed_smith"
ROSEMARY = "rosemary_nasrin"


@pytest.fixture
def client() -> Iterator[TestClient]:
    house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
    with TestClient(app=build_api(house, HUB)) as c:
        yield c


def as_(name: str) -> dict[str, str]:
    return {IDENTITY_HEADER: name}


def join(client: TestClient, name: str) -> None:
    assert client.post("/actors", json={"preferredUsername": name}).status_code == 201


def send(client: TestClient, frm: str, to: list[str], body: str, subject: str) -> str:
    r = client.post(
        f"/actors/{frm}/outbox",
        json={"type": "Note", "to": to, "content": body, "summary": subject},
        headers=as_(frm),
    )
    assert r.status_code in (200, 201), r.text
    return str(r.json()["id"]).rsplit("/", 1)[-1]


def find(client: TestClient, who: str, q: str, **params):
    r = client.get(f"/actors/{who}/search", params={"q": q, **params}, headers=as_(who))
    assert r.status_code == 200, r.text
    return r.json()


def ids(body) -> list[str]:
    return [str(x["id"]).rsplit("/", 1)[-1] for x in body["results"]]


@pytest.fixture
def mailbox(client: TestClient) -> dict[str, str]:
    """One hub, four agents, and a thread only two of them are fully in.

    Ludmila opens to Pablo and Jed, then replies to Pablo alone. Jed is the bystander on
    the private turn; Rosemary is a stranger to the whole thread. Every disclosure test
    below and every positive that mirrors it read *this* mailbox.
    """
    for name in (LUDMILA, PABLO, JED, ROSEMARY):
        join(client, name)
    opener = send(
        client, LUDMILA, [PABLO, JED], "the retry queue is flaky", "flaky retries"
    )
    private = send(
        client, LUDMILA, [PABLO], "between us, the flaky retries are my fault", "Re: it"
    )
    other = send(client, JED, [ROSEMARY], "the console needs a favicon", "unrelated")
    return {"opener": opener, "private": private, "other": other}


class TestTheRouteIsTheFilter:
    """FR-001, FR-006 — the wiring, and that nothing in the path widens it."""

    def test_a_party_finds_both_turns(self, client, mailbox) -> None:
        """The positive. Without it every negative below is unfalsifiable."""
        assert ids(find(client, PABLO, "flaky")) == [
            mailbox["private"],
            mailbox["opener"],
        ]

    def test_a_bystander_finds_only_the_turn_they_were_on(
        self, client, mailbox
    ) -> None:
        """Same hub, same query, same instant — only the caller differs."""
        assert ids(find(client, JED, "flaky")) == [mailbox["opener"]], (
            "a private reply reached a bystander over the wire"
        )

    def test_a_stranger_finds_nothing(self, client, mailbox) -> None:
        body = find(client, ROSEMARY, "flaky")
        assert body["results"] == [] and body["truncated"] is False

    def test_the_sender_finds_their_own_mail(self, client, mailbox) -> None:
        assert ids(find(client, JED, "favicon")) == [mailbox["other"]]

    def test_you_cannot_search_somebody_else_s_mailbox(self, client, mailbox) -> None:
        """The `owns` guard, which exists because asking for Alice's inbox as Bob
        once returned Bob's — a bug that read as working."""
        r = client.get(
            f"/actors/{PABLO}/search", params={"q": "flaky"}, headers=as_(JED)
        )
        assert r.status_code >= 400, "Jed searched Pablo's mailbox"


class TestItDisclosesNothingElse:
    """FR-007, and issue #45's leak that this route must not spread."""

    def test_a_snippet_never_carries_an_invisible_turn(self, client, mailbox) -> None:
        results = find(client, JED, "flaky")["results"]
        assert len(results) == 1
        assert "my fault" not in results[0]["snippet"], (
            "a snippet carried text from a turn the caller cannot see"
        )

    def test_a_result_does_not_name_the_parent_it_replies_to(
        self, client, mailbox
    ) -> None:
        """**Issue #45.** `_summary` emits `inReplyTo`; a search result must not.

        A caller party to a reply but not to its parent would otherwise learn the
        parent exists — the one place "real but not yours" is still distinguishable
        from "no such thing". Dropped, not nulled: a field that is null exactly when a
        thread is private says the same thing more quietly.
        """
        for result in find(client, PABLO, "flaky")["results"]:
            assert "inReplyTo" not in result, (
                "a search result named a parent message (issue #45)"
            )

    def test_truncated_counts_only_what_the_caller_may_see(self, client) -> None:
        """A hidden match must not make `truncated` true."""
        for name in (LUDMILA, PABLO, ROSEMARY):
            join(client, name)
        for i in range(30):
            send(client, LUDMILA, [PABLO], f"widget {i}", "many")
        assert find(client, ROSEMARY, "widget")["truncated"] is False
        assert find(client, PABLO, "widget")["truncated"] is True


class TestSearchingChangesNothing:
    """FR-004 — the guarantee that makes search safe to call speculatively."""

    def test_the_inbox_is_byte_identical_before_and_after(
        self, client, mailbox
    ) -> None:
        before = client.get(f"/actors/{PABLO}/inbox", headers=as_(PABLO)).text
        find(client, PABLO, "flaky")
        after = client.get(f"/actors/{PABLO}/inbox", headers=as_(PABLO)).text
        assert before == after, "searching changed what was waiting"

    def test_a_searched_message_is_still_unread(self, client, mailbox) -> None:
        find(client, PABLO, "flaky")
        waiting = client.get(
            f"/actors/{PABLO}/inbox", params={"view": "count"}, headers=as_(PABLO)
        ).json()
        assert waiting["unread"] == 2, "search consumed something"


class TestReachBack:
    """FR-005 — the point of the mission."""

    def test_a_message_already_read_is_still_findable(self, client, mailbox) -> None:
        """The case the whole mission exists for.

        Reading consumes — the message leaves the inbox — but it does not destroy, and
        until its conversation expires it stays findable.
        """
        read = client.post(f"/objects/{mailbox['opener']}/read", headers=as_(PABLO))
        assert read.status_code == 200, read.text
        assert (
            client.get(
                f"/actors/{PABLO}/inbox", params={"view": "count"}, headers=as_(PABLO)
            ).json()["unread"]
            == 1
        ), "the premise failed: reading did not consume"

        assert mailbox["opener"] in ids(find(client, PABLO, "flaky")), (
            "a message that was read became unfindable"
        )

    def test_reading_does_not_make_it_findable_to_others(self, client, mailbox) -> None:
        """Consumption is per-reader; so is search. Rosemary still sees nothing."""
        client.post(f"/objects/{mailbox['opener']}/read", headers=as_(PABLO))
        assert find(client, ROSEMARY, "flaky")["results"] == []


class TestQueryHandling:
    """FR-008, FR-009, NFR-001 over the wire."""

    def test_an_empty_query_returns_nothing(self, client, mailbox) -> None:
        body = find(client, PABLO, "")
        assert body["results"] == [], "an empty query returned the mailbox"

    def test_filters_narrow(self, client, mailbox) -> None:
        assert ids(find(client, PABLO, "flaky", sender=LUDMILA)) == [
            mailbox["private"],
            mailbox["opener"],
        ]
        assert ids(find(client, PABLO, "flaky", sender=JED)) == []

    def test_an_over_large_limit_is_capped_not_refused(self, client) -> None:
        for name in (LUDMILA, PABLO):
            join(client, name)
        for i in range(40):
            send(client, LUDMILA, [PABLO], f"widget {i}", "many")
        body = find(client, PABLO, "widget", limit=500)
        assert len(body["results"]) == 25 and body["truncated"] is True

    def test_a_result_carries_what_you_decide_from(self, client, mailbox) -> None:
        """FR-003 — and the AS2 names, not invented ones."""
        result = find(client, JED, "favicon")["results"][0]
        assert result["attributedTo"].endswith(f"/actors/{JED}")
        assert result["summary"] == "unrelated"
        assert result["published"] and result["snippet"]
        assert result["type"] == "Note"
