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
        self.token_items: list[dict[str, Any]] = []
        self.token_status = 200

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
        return {
            "listeningBy": {ROSEMARY: 1},
            "listeningSessions": 1,
            "flow": [[ROSEMARY, TREVOR, 3]],
            "actors": 2,
        }

    def auth_call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        session: str | None = None,
        **_: Any,
    ) -> tuple[int, dict[str, Any], Any]:
        if method == "POST" and path == "/auth/tokens":
            return 201, {"token": "a-minted-secret"}, None
        return self.token_status, {"items": list(self.token_items)}, None

    def list_agents(self) -> dict[str, Any]:
        return {
            "items": [
                {"preferredUsername": ROSEMARY, "profile": {"project": "billing"}},
                {"preferredUsername": TREVOR, "profile": {}},
            ]
        }

    def survey_flow(self) -> list[tuple[str, str, int]]:
        return [(ROSEMARY, TREVOR, 3)]


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

    def test_the_mail_is_in_the_feed_not_a_second_table(
        self, console: TestClient
    ) -> None:
        feed = console.get(f"/agent/{ROSEMARY}").text.split('class="feed-rows"', 1)[1]

        assert "inbound one" in feed
        assert "outbound one" in feed

    def test_a_seeded_row_carries_its_direction(self, console: TestClient) -> None:
        """Direction is decided per viewer server-side too, not only in the script."""
        feed = console.get(f"/agent/{ROSEMARY}").text.split('class="feed-rows"', 1)[1]

        assert 'data-dir="in"' in feed
        assert 'data-dir="out"' in feed

    def test_direction_is_written_in_words(self, console: TestClient) -> None:
        """FR-013. Colour is never the only cue.

        Asserted on the feed rows, which is where direction now lives — the separate
        table that used to carry it is gone.
        """
        feed = console.get(f"/agent/{ROSEMARY}").text.split('class="feed-rows"', 1)[1]

        assert '<span class="feed-dir">to</span>' in feed
        assert '<span class="feed-dir">from</span>' in feed

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

    def test_the_recent_mail_is_in_the_feed_itself(self, console: TestClient) -> None:
        """One list, not two.

        There used to be a separate "Before you arrived" table beneath the live feed.
        Two lists of the same thing — one live, one not — made a reader hold two ideas
        where one would do, and the static half was the one that looked authoritative
        while being the one that had stopped updating.
        """
        text = console.get("/realtime").text
        feed = text.split('class="feed-rows"', 1)[1]

        assert "inbound one" in feed, "recent mail is not inside the live feed"
        assert "Before you arrived" not in text

    def test_a_seeded_row_matches_the_shape_the_script_builds(
        self, console: TestClient
    ) -> None:
        """Server-rendered and live rows land on one list and must look alike.

        If the two drift, the same page shows two kinds of row and the difference reads
        as a bug in whichever half the reader trusts less.
        """
        feed = console.get("/realtime").text.split('class="feed-rows"', 1)[1]

        for part in (
            "feed-row",
            "feed-rail",
            "feed-body",
            "feed-meta",
            "feed-who",
            "feed-when",
            "feed-subject",
        ):
            assert part in feed, f"a seeded row is missing {part}"

    def test_the_empty_notice_is_hidden_when_there_is_mail(
        self, console: TestClient
    ) -> None:
        """The paired positive for the seeding: "nothing yet" beside rows is a lie."""
        text = console.get("/realtime").text

        assert 'class="feed-empty" hidden' in text or "feed-empty hidden" in text

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


class TestWhichTokenAdmittedIt:
    """The one genuinely new *observed* fact the page gains.

    Derived from `/auth/tokens`, which already reports per token which agents it has
    admitted. Same table, read the other way round — #22 recorded this as blocked on the
    shared-tokens mission, and that mission landed.
    """

    def test_it_names_the_token_that_admitted_this_agent(self, hub: StubHub) -> None:
        hub.token_items = [
            {"id": "t1", "label": "laptop", "admitted": [{"name": ROSEMARY}]},
            {"id": "t2", "label": "other", "admitted": [{"name": TREVOR}]},
        ]
        with TestClient(app=build_console(hub)) as console:
            text = console.get(f"/agent/{ROSEMARY}").text

        assert "Admitted by" in text
        assert "laptop" in text
        # The paired negative: a filter that ignored the name would list both.
        assert "other" not in text

    def test_it_is_an_observed_fact_not_a_claimed_one(self, hub: StubHub) -> None:
        """The hub writes this row itself, so it belongs in the first panel."""
        hub.token_items = [
            {
                "id": "t1",
                "label": "laptop",
                "admitted": [{"name": ROSEMARY, "client": "0.34.0"}],
            }
        ]
        with TestClient(app=build_console(hub)) as console:
            text = console.get(f"/agent/{ROSEMARY}").text

        observed = text.split('class="panel claimed"', 1)[0]
        assert "laptop" in observed, "an observed fact landed in the claimed panel"

    def test_a_viewer_who_may_not_audit_tokens_sees_the_page_anyway(
        self, hub: StubHub
    ) -> None:
        """Tokens are an operator action; this page is not.

        Their inability to audit credentials is not a fault in the agent they were
        looking at, so the row is omitted rather than the page broken.
        """
        hub.token_status = 403
        with TestClient(app=build_console(hub)) as console:
            page = console.get(f"/agent/{ROSEMARY}")

        assert page.status_code == 200
        assert "Admitted by" not in page.text


def _flow_table(html_text: str) -> str:
    """Just the flow table.

    Scoped to the one table on purpose. The first version of these tests split on the
    heading and kept everything after it — which includes the Agents table below, and
    that table already carries a Project column. So "billing" was always present and the
    assertions passed with the feature removed. Caught by running the removal proof and
    getting no failures at all.
    """
    after = html_text.split("Who is talking to whom", 1)[1]
    return after.split("<h2>", 1)[0]


class TestTheFlowTableNamesTheWork:
    """Issue #18. A flow of bare names says who is busy, not which work is busy."""

    def test_it_shows_the_project_beside_the_name(self, console: TestClient) -> None:
        flow = _flow_table(console.get("/").text)

        assert "billing" in flow, "the flow table does not name the work"

    def test_an_agent_with_no_project_renders_no_placeholder(
        self, console: TestClient
    ) -> None:
        """Most agents have never set one. A column of dashes adds width and says less
        than blank space does — the paired negative for the test above."""
        flow = _flow_table(console.get("/").text)
        row = flow.split(TREVOR, 1)[1][:120]

        assert "—" not in row

    def test_it_costs_no_extra_hub_call(self, console: TestClient) -> None:
        """The roster is already fetched for the Agents table below; naming the work
        must reuse it rather than asking again per row."""
        text = console.get("/").text

        assert "billing" in _flow_table(text)
        assert text.count("Who is talking to whom") == 1


class TestTheSetupPromptPointsSomewhereReal:
    """The token screen hands an agent its last instruction: where to read the rest.

    It used to send them to `<api>/prompts/agent`, which 404s — the API has no such
    route and the console is what renders that page. Two addresses that look
    interchangeable and are not, in the one place a reader cannot check before
    following it.
    """

    def test_it_sends_the_agent_to_the_console_not_the_api(self, hub: StubHub) -> None:
        with TestClient(app=build_console(hub)) as console:
            page = console.post("/tokens/mint", data={"label": "laptop"})

        text = page.text
        assert "/prompts/agent" in text, "the setup prompt names no prompt address"
        # The API base must not be the thing carrying that path.
        assert f"{HUB}/prompts/agent" not in text, (
            "the setup prompt points at the API, which has no /prompts route"
        )

    def test_it_still_joins_against_the_api(self, hub: StubHub) -> None:
        """The paired positive: the *hub* address is still the API's, and must be.

        `join --hub` talks to the API. Repointing everything at the console would swap
        one broken instruction for another.
        """
        with TestClient(app=build_console(hub)) as console:
            text = console.post("/tokens/mint", data={"label": "laptop"}).text

        assert f"join --hub {HUB}" in text


class TestTheClientVersionTheHubSaw:
    """Observed on a request, not written into a profile at join.

    The distinction is the whole value. An install on an interpreter older than our
    floor silently resolves to an old release rather than failing, so the agents worth
    finding are precisely those who joined long ago on a client they did not choose —
    and a profile field records what was true at join, which for them is either absent
    or wrong (`igor_laszlo`, 2026-08-05).
    """

    def test_it_shows_the_version_the_hub_last_saw(self, hub: StubHub) -> None:
        hub.token_items = [
            {
                "id": "t1",
                "label": "laptop",
                "admitted": [{"name": ROSEMARY, "client": "0.34.0"}],
            }
        ]
        with TestClient(app=build_console(hub)) as console:
            text = console.get(f"/agent/{ROSEMARY}").text

        assert "0.34.0" in text, "the page does not say which client this agent runs"

    def test_it_is_observed_not_claimed(self, hub: StubHub) -> None:
        """It must sit with what the hub recorded, never with what the agent said.

        A version in the self-declared panel would be exactly as trustworthy as an agent
        remembering to update it — which is the failure this replaces.
        """
        hub.token_items = [
            {
                "id": "t1",
                "label": "laptop",
                "admitted": [{"name": ROSEMARY, "client": "0.34.0"}],
            }
        ]
        with TestClient(app=build_console(hub)) as console:
            text = console.get(f"/agent/{ROSEMARY}").text

        observed = text.split('class="panel claimed"', 1)[0]
        assert "0.34.0" in observed, "the observed client version fell into claims"

    def test_an_agent_the_hub_has_not_heard_from_shows_nothing(
        self, hub: StubHub
    ) -> None:
        """The paired negative. Blank means "we have not heard", not "it is current",
        and inventing a version would be worse than leaving the row out."""
        hub.token_items = [
            {"id": "t1", "label": "laptop", "admitted": [{"name": ROSEMARY}]}
        ]
        with TestClient(app=build_console(hub)) as console:
            text = console.get(f"/agent/{ROSEMARY}").text

        assert "Client seen" not in text
