"""Where the onboarding prompt is served, and who has to sign in to see it.

Owner, 2026-08-05: *"I notice you can see the prompt when not logged in; I don't think
it's necessary to see the page. Wouldn't a simpler way be to have the API serve the
prompt, and not the UI?"*

It is simpler, and it puts each document on the surface that suits it. The prompt is
**unauthenticated by necessity** — an agent needs it before it has a credential, since
the prompt is what tells it how to get one — so it belongs on the unauthenticated
surface. The console is a human's window and can then gate everything it shows.
"""

from typing import Any

import pytest
from litestar.testing import TestClient

from agent_inbox.api import build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"


@pytest.fixture
def api() -> TestClient:
    house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
    return TestClient(app=build_api(house, HUB))


class TestTheApiServesThePrompt:
    def test_it_is_there_at_all(self, api: TestClient) -> None:
        """It was not, before this. `curl <api>/prompts/agent` answered 404 on the
        reference hub while the console answered 200 — which is why the console had a
        page anyone could read."""
        with api as client:
            answer = client.get("/prompts/agent")

        assert answer.status_code == 200
        assert answer.text.strip(), "an empty prompt is not a prompt"

    def test_no_credential_is_needed(self, api: TestClient) -> None:
        """The one route where that is not a hole. Gating it would be a lock whose key
        is inside — an agent fetches this *in order to* obtain a credential."""
        with api as client:
            assert client.get("/prompts/agent").status_code == 200

    def test_every_role_name_returns_the_same_document(self, api: TestClient) -> None:
        """Roles are configuration; what one *means* is fetched at runtime. Three pages
        would be three things to drift apart, and the names exist only so that pasted
        instructions and old bookmarks keep working."""
        with api as client:
            texts = {
                role: client.get(f"/prompts/{role}").text
                for role in ("agent", "host", "admin")
            }

        assert len(set(texts.values())) == 1, "the role names have drifted apart"

    def test_it_names_the_hub_it_was_served_by(self, api: TestClient) -> None:
        """A prompt that names somewhere else is worse than none: the reader will join
        the wrong hub and every later symptom will point away from the cause."""
        with api as client:
            text = client.get("/prompts/agent").text

        assert HUB in text

    def test_it_is_plain_text_rather_than_a_page(self, api: TestClient) -> None:
        """It is read by `curl` and pasted into a terminal. HTML would arrive as markup
        in somebody's instructions."""
        with api as client:
            answer = client.get("/prompts/agent")

        assert answer.headers["content-type"].startswith("text/plain")
        assert "<html" not in answer.text.lower()


class TestTheConsolePageNeedsASignIn:
    """The other half of the same decision. Once the API serves the document, there is
    no reason for the console to show a page to somebody who has not signed in."""

    @staticmethod
    def _console(authenticated: bool) -> TestClient:
        from agent_inbox.client import Config, HubClient
        from agent_inbox.console import build_console

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub=HUB, name="console"))

            def hub_info(self) -> dict[str, Any]:
                return {
                    "name": "testhub",
                    "version": "1.0.0",
                    "authenticated": authenticated,
                }

        return TestClient(app=build_console(Stub()))

    def test_the_page_is_gated_on_an_authenticating_hub(self) -> None:
        with self._console(authenticated=True) as console:
            answer = console.get("/prompts", follow_redirects=False)

        assert answer.status_code in (302, 303, 307), (
            "the console still shows its prompt page to somebody not signed in"
        )

    def test_the_plain_text_route_is_not_gated(self) -> None:
        """The paired positive, and the one that must not break. Agents already point
        at this address — the project's own instructions say to read it — and an agent
        fetching it has no session by definition."""
        with self._console(authenticated=True) as console:
            answer = console.get("/prompts/agent", follow_redirects=False)

        assert answer.status_code == 200
        assert answer.text.strip()

    def test_the_curl_shaped_name_is_not_gated_either(self) -> None:
        with self._console(authenticated=True) as console:
            assert (
                console.get("/prompts.txt", follow_redirects=False).status_code == 200
            )

    def test_an_open_hub_still_shows_everything(self) -> None:
        """A hub that does not authenticate has no sign-in to demand. Gating the page
        there would lock a LAN deployment out of its own console."""
        with self._console(authenticated=False) as console:
            assert console.get("/prompts", follow_redirects=False).status_code == 200


class TestAnExpiredSessionSaysSo:
    """Owner, 2026-08-05: Maintenance and Settings showed *"present a device token or
    log in at the console"* to somebody sitting in the console, logged in, with the
    other tabs working. Logging out and back in fixed it — the session had expired.

    That sentence is correct for the audience the hub is answering: an agent calling the
    API with no credential. It is useless to a human already inside, and it sent one
    debugging a hub that was working perfectly.

    Only the console can tell the two apart, because only it can see whether the browser
    is carrying a cookie at all. From the hub, an expired session and never having had
    one are the same nothing.
    """

    @staticmethod
    def _console(status: int) -> TestClient:
        from agent_inbox.client import Config, HubClient
        from agent_inbox.console import build_console

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub=HUB, name="console"))

            def hub_info(self) -> dict[str, Any]:
                return {"name": "testhub", "version": "1.0.0", "authenticated": True}

            def auth_call(self, *a: Any, **kw: Any) -> tuple[int, Any, Any]:
                return (
                    status,
                    {
                        "detail": "this hub requires authentication for this route — "
                        "present a device token or log in at the console"
                    },
                    None,
                )

        return TestClient(app=build_console(Stub()))

    @pytest.mark.parametrize("page", ["/maintenance", "/settings"])
    def test_a_stale_cookie_is_told_to_sign_in_again(self, page: str) -> None:
        from agent_inbox.console import SESSION_COOKIE

        with self._console(401) as console:
            text = console.get(
                page, cookies={SESSION_COOKIE: "expired-but-present"}
            ).text

        assert "expired" in text.lower(), (
            "the reader is not told what actually happened"
        )
        assert "device token" not in text, (
            "the hub's wording for an agent reached a human — the reported bug"
        )

    @pytest.mark.parametrize("page", ["/maintenance", "/settings"])
    def test_it_offers_the_way_out(self, page: str) -> None:
        """A diagnosis with nothing to click is half a fix; the remedy is one link."""
        from agent_inbox.console import SESSION_COOKIE

        with self._console(401) as console:
            text = console.get(page, cookies={SESSION_COOKIE: "stale"}).text

        assert "/login" in text

    @pytest.mark.parametrize("page", ["/maintenance", "/settings"])
    def test_a_refusal_that_is_not_about_auth_still_says_what_it_was(
        self, page: str
    ) -> None:
        """The paired negative. Rewriting *every* refusal as "sign in again" would hide
        real faults behind a wrong diagnosis — which is the same mistake in the other
        direction."""
        from agent_inbox.console import SESSION_COOKIE

        with self._console(503) as console:
            text = console.get(page, cookies={SESSION_COOKIE: "fine"}).text

        assert "expired" not in text.lower()
        assert "device token" in text, "the hub's own detail was discarded"


class TestTheTwoCopiesStayOneDocument:
    """`igor_laszlo` diffed the API and console copies within minutes of the release and
    asked whether they had drifted.

    They had not — the single difference is the address each names, which is the one it
    was fetched from, deliberately: the snippet asks the reader to write that address
    into their project's instructions, where it is re-read for months by a session that
    cannot debug it, so it must name a door that demonstrably opened for them rather
    than one somebody recommended.

    But he had to check by hand, and asked to keep checking. That belongs here instead.
    A *second* difference would be real drift, and the two are generated from one
    function precisely so there is nothing to keep in step.
    """

    @staticmethod
    def _rendered(prompt_url: str) -> list[str]:
        from agent_inbox.prompts import onboarding

        return onboarding(HUB, prompt_url, "1.0.0", True).splitlines()

    def test_only_the_address_they_were_fetched_from_differs(self) -> None:
        api = self._rendered("https://api.example.invalid/prompts/agent")
        console = self._rendered("https://console.example.invalid/prompts/agent")

        assert len(api) == len(console), "the two copies are no longer the same shape"
        differing = [
            (number, a, c)
            for number, (a, c) in enumerate(zip(api, console, strict=True), 1)
            if a != c
        ]

        assert len(differing) == 1, (
            "the copies differ by more than the address they name — that is drift:\n"
            + "\n".join(f"  line {n}: {a!r} vs {c!r}" for n, a, c in differing)
        )

    def test_each_copy_names_the_address_it_was_fetched_from(self) -> None:
        """The paired positive, and the property the difference exists to provide. An
        agent that can reach one surface and not the other must record the one that
        worked."""
        api = "\n".join(self._rendered("https://api.example.invalid/prompts/agent"))
        console = "\n".join(
            self._rendered("https://console.example.invalid/prompts/agent")
        )

        assert "api.example.invalid" in api
        assert "console.example.invalid" not in api
        assert "console.example.invalid" in console
        assert "api.example.invalid" not in console


class TestThePasteableSnippetNamesTheApi:
    """Owner, 2026-08-05, looking at the console's Prompt page: the pasteable snippet
    should point at the hub's API address rather than at the console.

    **This is a change of mind and it is worth recording as one.** Yesterday's reasoning
    — which I gave `igor_laszlo` in writing — was that each copy should name the door
    the reader came through, because a proven address beats a recommended one. That
    still holds for the *document*, which is why the two rendered copies still differ.

    It does not hold for the **pasteable snippet**, and the difference is who is
    reading. The document is read by whoever fetched it. The snippet is written into a
    `CLAUDE.md` and re-read for months by sessions that cannot debug it — and the two
    doors are not equal for that: the API serves the prompt as its own route, while the
    console's page now needs a sign-in and its plain-text route exists for
    compatibility. A pointer that outlives everything should name the durable
    machine-facing address.
    """

    @staticmethod
    def _console(hub_id: str) -> TestClient:
        from agent_inbox.client import Config, HubClient
        from agent_inbox.console import build_console

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub="http://console-reaches-hub", name="c"))

            def hub_info(self) -> dict[str, Any]:
                return {
                    "id": hub_id,
                    "name": "testhub",
                    "version": "1.0.0",
                    "authenticated": False,
                }

        return TestClient(app=build_console(Stub()))

    def test_the_snippet_points_at_the_hubs_own_address(self) -> None:
        with self._console("https://api.example.invalid") as console:
            page = console.get("/prompts").text

        snippet = page.split("<textarea", 1)[1].split("</textarea>", 1)[0]

        assert "https://api.example.invalid/prompts/agent" in snippet

    def test_the_snippet_does_not_point_at_the_console(self) -> None:
        """The paired negative, and the reported bug: the snippet named the console."""
        with self._console("https://api.example.invalid") as console:
            page = console.get("/prompts").text

        snippet = page.split("<textarea", 1)[1].split("</textarea>", 1)[0]

        assert "testserver" not in snippet, "the snippet still names this console"

    def test_the_document_below_still_names_this_console(self) -> None:
        """Unchanged, deliberately. Only the pointer moved; the rendered document still
        names the door its reader came through, which is what `igor_laszlo` and
        `mariana_taphrale` have a baseline for."""
        with self._console("https://api.example.invalid") as console:
            page = console.get("/prompts").text

        below = page.split("</textarea>", 1)[1]

        assert "testserver" in below
