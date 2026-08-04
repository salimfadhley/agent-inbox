"""The live pages, asserted against what the browser is actually sent.

**Against the rendered page, never against a helper.** A console test in this repository
once exercised a helper rather than the page, and so could not tell a working guard from
a missing call — it was green and worthless. So every test here fetches a URL and reads
the HTML that came back.

The two things most likely to be lost quietly:

* the **two panels** collapsing into one, which would let a self-declared hostname
  borrow the credibility of a recorded join date;
* `/mailbox/{name}` disappearing when the agent page absorbed it, which would break
  every link and bookmark already written down.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from litestar.testing import TestClient

from agent_inbox.client import Config, HubClient
from agent_inbox.console import build_console

HUB = "http://hub.invalid"
ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"


def note(oid: str, frm: str, to: list[str], subject: str, when: str) -> dict[str, Any]:
    return {
        "id": f"{HUB}/objects/{oid}",
        "attributedTo": f"{HUB}/actors/{frm}",
        "to": [f"{HUB}/actors/x" for x in to],
        "summary": subject,
        "published": when,
    }


class StubHub(HubClient):
    """Answers from memory. Every console read is stubbed, so nothing leaves."""

    def __init__(self) -> None:
        super().__init__(Config(hub=HUB, name="console"))
        self.profile: dict[str, Any] = {
            "engine": "claude",
            "model": "a-model",
            "host": "somebox.invalid",
            "project": "billing",
            "root": "workspace/billing",
        }
        self.received = [note("r1", TREVOR, [ROSEMARY], "inbound one", "2026-08-01")]
        self.sent = [note("s1", ROSEMARY, [TREVOR], "outbound one", "2026-08-02")]
        self.known = True

    def hub_info(self) -> dict[str, Any]:
        return {
            "id": HUB,
            "name": "testhub",
            "version": "1.2.3",
            "authenticated": False,
        }

    def whoami(self) -> str | None:
        return "console"

    def whois(self, name: str) -> dict[str, Any]:
        if not self.known:
            return {}
        return {
            "preferredUsername": name,
            "summary": "a test agent",
            "profile": dict(self.profile),
            "lastSeen": "2026-08-03T10:00:00Z",
        }

    def observe_mailbox(self, name: str) -> dict[str, Any]:
        return {"items": list(self.received)}

    def observe_outbox(self, name: str) -> dict[str, Any]:
        return {"items": list(self.sent)}

    def observe_recent(self, limit: int | None = None) -> dict[str, Any]:
        return {"items": [*self.received, *self.sent]}

    def survey(self, since: str = "") -> dict[str, Any]:
        return {"listeningBy": {ROSEMARY: 1}, "listeningSessions": 1}

    def list_agents(self) -> dict[str, Any]:
        return {"items": [{"preferredUsername": ROSEMARY, "profile": {}}]}


@pytest.fixture
def hub() -> StubHub:
    return StubHub()


@pytest.fixture
def console(hub: StubHub) -> Iterator[TestClient]:
    with TestClient(app=build_console(hub)) as client:
        yield client


class TestTheAgentPage:
    def test_it_renders(self, console: TestClient) -> None:
        page = console.get(f"/agent/{ROSEMARY}")
        assert page.status_code == 200
        assert ROSEMARY in page.text

    def test_an_unknown_agent_is_a_404(self, console: TestClient, hub: StubHub) -> None:
        hub.known = False
        assert console.get("/agent/nobody_here").status_code == 404

    def test_the_two_panels_are_distinguishable(self, console: TestClient) -> None:
        """A claim must not be able to pass as a record.

        #22 named this exactly: without the labelling it is "a status page that looks
        authoritative while reporting whatever the agent claimed".
        """
        text = console.get(f"/agent/{ROSEMARY}").text

        assert "Known to the hub" in text
        assert "Says of itself" in text
        assert "Self-declared, unverified" in text
        assert 'class="panel claimed"' in text

    def test_the_claimed_facts_are_in_the_claimed_panel(
        self, console: TestClient
    ) -> None:
        """The paired positive, and the one that stops the labelling being decorative.

        Two labelled panels prove nothing if the self-declared hostname is rendered in
        the observed one.
        """
        text = console.get(f"/agent/{ROSEMARY}").text
        claimed = text.split('class="panel claimed"', 1)[1]
        observed = text.split('class="panel claimed"', 1)[0]

        assert "somebox.invalid" in claimed, "a claimed fact is missing from its panel"
        assert "somebox.invalid" not in observed, "a claim reached the observed panel"

    def test_last_seen_is_never_presented_as_presence(
        self, console: TestClient
    ) -> None:
        """There is no heartbeat, and a page is where somebody starts reading one in."""
        text = console.get(f"/agent/{ROSEMARY}").text

        assert "recency, not presence" in text

    def test_an_agent_with_no_profile_says_so(
        self, console: TestClient, hub: StubHub
    ) -> None:
        hub.profile = {}

        text = console.get(f"/agent/{ROSEMARY}").text

        assert "Nothing declared" in text

    def test_an_agent_with_a_profile_shows_it(self, console: TestClient) -> None:
        """The paired positive. Without it, a page that rendered nothing for everybody
        would satisfy the test above."""
        text = console.get(f"/agent/{ROSEMARY}").text

        assert "Nothing declared" not in text
        assert "workspace/billing" in text

    def test_both_directions_appear(self, console: TestClient) -> None:
        text = console.get(f"/agent/{ROSEMARY}").text

        assert "inbound one" in text
        assert "outbound one" in text

    def test_direction_is_written_in_words(self, console: TestClient) -> None:
        """FR-013. Colour is never the only cue."""
        text = console.get(f"/agent/{ROSEMARY}").text

        assert '<span class="dir out">to</span>' in text
        assert '<span class="dir in">from</span>' in text

    def test_the_feed_is_told_whose_page_this_is(self, console: TestClient) -> None:
        """Direction is per viewer, so the page has to say who the viewer is."""
        text = console.get(f"/agent/{ROSEMARY}").text

        assert f'data-subject="{ROSEMARY}"' in text

    def test_it_offers_the_filter_pills(self, console: TestClient) -> None:
        text = console.get(f"/agent/{ROSEMARY}").text

        assert 'data-f="in"' in text
        assert 'data-f="out"' in text


class TestTheRealtimeTab:
    def test_it_renders_and_is_in_the_nav(self, console: TestClient) -> None:
        page = console.get("/realtime")

        assert page.status_code == 200
        assert "href='/realtime'" in console.get("/").text

    def test_it_opens_full_rather_than_blank(self, console: TestClient) -> None:
        """A live view that starts empty cannot be told from one that is broken.

        Filled server-side from `/observe/recent`, so it is useful before the stream
        says anything and useful with no JavaScript at all.
        """
        text = console.get("/realtime").text

        assert "inbound one" in text
        assert "outbound one" in text

    def test_it_carries_no_subject_so_rows_render_plain(
        self, console: TestClient
    ) -> None:
        """On a hub-wide view there is no "us" for a message to be to or from."""
        text = console.get("/realtime").text

        assert 'data-subject=""' in text

    def test_the_head_row_does_not_open_optimistically(
        self, console: TestClient
    ) -> None:
        """Until the relay says otherwise, "connected" is a guess.

        A page that opens by guessing right is one that will open by guessing wrong.
        """
        text = console.get("/realtime").text

        assert 'data-state="reconnecting"' in text
        assert 'data-state="open"' not in text


class TestTheMailboxSurvives:
    def test_the_old_route_still_answers(self, console: TestClient) -> None:
        """Absorbed, not deleted — every link already written keeps working."""
        page = console.get(f"/mailbox/{ROSEMARY}")

        assert page.status_code == 200
        assert "inbound one" in page.text

    def test_the_agent_page_links_to_it(self, console: TestClient) -> None:
        text = console.get(f"/agent/{ROSEMARY}").text

        assert f'href="/mailbox/{ROSEMARY}"' in text

    def test_agent_names_now_lead_to_the_agent_page(self, console: TestClient) -> None:
        """Every table builds its links through one helper, so this is one assertion."""
        text = console.get("/agents").text

        assert f'href="/agent/{ROSEMARY}"' in text


class TestTheAssetsAndTheCsp:
    def test_the_feed_assets_are_referenced(self, console: TestClient) -> None:
        text = console.get("/realtime").text

        assert "/static/feed.css" in text
        assert "/static/feed.js" in text

    def test_the_csp_is_unchanged(self, console: TestClient) -> None:
        """The relay exists so that this can stay true."""
        csp = console.get("/realtime").headers["content-security-policy"]

        assert "script-src 'self'" in csp
        assert "default-src 'self'" in csp
