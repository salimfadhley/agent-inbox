"""The human console.

Two things are worth testing here, and neither is the HTML:

1. The prompt page hands out **this** hub's address, because a placeholder is the thing
   a human gets wrong. A page that renders beautifully with `localhost` in the commands
   has failed at its only job.
2. The observatory screens read the hub *without impersonating anyone*. The old console
   viewed a mailbox by pretending to be its owner; these tests pin that it no longer
   does — it calls the `/observe/*` routes, which take no caller.

The hub is stubbed in-process so the pages render without a network. The stub records
which client methods were called, which is how the no-impersonation property is checked.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from litestar.testing import TestClient

from agent_mailbox.client import Config, HubClient
from agent_mailbox.console import build_console

HUB = "http://mailbox.invalid:8081"


class StubHub(HubClient):
    """A hub that answers from memory and remembers what it was asked.

    Every method the console uses is stubbed so no request leaves the process. The
    ``calls`` list is the point of the fixture: a test can assert that viewing a
    mailbox went through ``observe_*`` and never through ``check_inbox`` as someone
    else — the impersonation the rewrite removed.
    """

    def __init__(self, hub: str = HUB, name: str = "console") -> None:
        super().__init__(Config(hub=hub, name=name))
        self.calls: list[str] = []

    def hub_info(self) -> dict[str, Any]:
        return {
            "id": HUB,
            "name": "testhub",
            "version": "1.2.3",
            "authenticated": False,
        }

    def join(self, name: str | None = None) -> dict[str, Any]:
        self.calls.append("join")
        return {"preferredUsername": self.config.name}

    def list_agents(self) -> dict[str, Any]:
        self.calls.append("list_agents")
        return {
            "items": [
                {
                    "preferredUsername": "rosemary_nasrin",
                    "type": "Service",
                    "summary": "runs the deploys",
                    "profile": {"role": "agent", "project": "billing"},
                    "lastSeen": "2026-07-24T10:00:00Z",
                }
            ]
        }

    def whois(self, name: str) -> dict[str, Any]:
        self.calls.append(f"whois:{name}")
        return {"preferredUsername": name, "summary": "someone"}

    def survey(self, since: str = "") -> dict[str, Any]:
        self.calls.append("survey")
        return {
            "actors": 3,
            "messages": 2,
            "threads": 1,
            "per_day": [["2026-07-24", 2]],
            "flow": [["rosemary_nasrin", "trevor_mahmood", 2]],
            "busiest": [["rosemary_nasrin", 2]],
        }

    def observe_mailbox(self, name: str) -> dict[str, Any]:
        self.calls.append(f"observe_mailbox:{name}")
        return {
            "items": [
                {
                    "id": f"{HUB}/objects/abc123",
                    "attributedTo": f"{HUB}/actors/rosemary_nasrin",
                    "summary": "flaky tests",
                    "content": "one run in five",
                    "published": "2026-07-24T10:00:00Z",
                }
            ]
        }

    def observe_object(self, object_id: str) -> dict[str, Any]:
        self.calls.append(f"observe_object:{object_id}")
        return {
            "id": f"{HUB}/objects/abc123",
            "attributedTo": f"{HUB}/actors/rosemary_nasrin",
            "summary": "flaky tests",
            "content": "one run in five",
            "published": "2026-07-24T10:00:00Z",
            "readBy": ["trevor_mahmood"],
        }

    def observe_thread(self, object_id: str) -> dict[str, Any]:
        self.calls.append(f"observe_thread:{object_id}")
        return self.observe_mailbox("x")

    def check_inbox(self) -> dict[str, Any]:
        self.calls.append("check_inbox")
        return {"items": []}

    def send_message(self, to: Any, body: str, subject: Any = None, **kw: Any) -> dict:
        self.calls.append(f"send:{to}")
        return {"id": f"{HUB}/objects/new"}

    def read_message(self, object_id: str) -> dict[str, Any]:
        self.calls.append(f"read:{object_id}")
        return {}


def make(stub: StubHub | None = None) -> tuple[TestClient, StubHub]:
    hub = stub or StubHub()
    return TestClient(app=build_console(hub)), hub


@pytest.fixture
def console() -> Iterator[TestClient]:
    client, _ = make()
    with client as c:
        yield c


# -- the prompt ------------------------------------------------------------


def test_the_prompt_names_this_hub_not_a_placeholder(console: TestClient) -> None:
    """The address in the pasted text is the one the console is actually talking to."""
    body = console.get("/prompts").text
    assert HUB in body
    assert "&lt;host&gt;" not in body and "localhost" not in body


def test_the_prompt_advertises_the_hub_not_the_sidecar_route_to_it() -> None:
    """The sidecar trap: the console reaches the hub by a name no agent can use.

    Over a container network the console talks to `http://agent-mailbox:8080`. Pasting
    that into a prompt sends an agent nowhere. The hub's published `id` is the address
    it claims as its own, and that is the one a reader needs.
    """
    client, _ = make(StubHub(hub="http://agent-mailbox:8080", name="c"))
    with client as c:
        text = c.get("/prompts.txt").text
    assert HUB in text
    assert "agent-mailbox:8080" not in text


def test_the_plain_text_form_is_the_same_prompt(console: TestClient) -> None:
    """`/prompts.txt` exists so it can be curled; it must not drift from the page."""
    page = console.get("/prompts")
    text = console.get("/prompts.txt")
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    assert "uv tool install" in text.text
    assert "uv tool install" in page.text


def test_there_is_exactly_one_prompt(console: TestClient) -> None:
    """No per-role pages. Three prompts drifted apart last time; one cannot."""
    body = console.get("/prompts").text
    for role in ("agent", "host", "admin"):
        assert f'href="/prompts/{role}"' not in body
    assert "agent-mailbox.toml" in body


def test_the_prompt_says_the_hub_does_not_authenticate(console: TestClient) -> None:
    assert "does not authenticate" in console.get("/prompts.txt").text


def test_the_prompt_names_the_command_that_exists(console: TestClient) -> None:
    text = console.get("/prompts.txt").text
    assert "agent-mailbox mcp" in text
    assert "agent-mailbox-mcp" not in text


# -- the observatory -------------------------------------------------------


def test_every_page_links_to_the_others(console: TestClient) -> None:
    body = console.get("/").text
    for href in ("/agents", "/inbox", "/compose", "/prompts"):
        assert f"'{href}'" in body or f'"{href}"' in body


def test_the_dashboard_shows_traffic(console: TestClient) -> None:
    body = console.get("/").text
    assert "messages" in body
    # the flow edge from the stub survey
    assert "rosemary_nasrin" in body and "trevor_mahmood" in body


def test_viewing_a_mailbox_observes_it_and_never_impersonates(
    console: TestClient,
) -> None:
    """The property the whole rewrite is for.

    Looking at trevor's mailbox must go through `observe_mailbox`, and must NOT call
    `check_inbox` as trevor — the old console did exactly that, and it worked only
    because nothing authenticates.
    """
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.get("/mailbox/trevor_mahmood")
    assert r.status_code == 200
    assert "observe_mailbox:trevor_mahmood" in hub.calls
    assert not any(call.startswith("check_inbox") for call in hub.calls), (
        "the console impersonated the agent instead of observing"
    )


def test_a_message_shows_the_whole_thread_and_who_read_it(
    console: TestClient,
) -> None:
    body = console.get("/message/abc123").text
    assert "flaky tests" in body
    assert "trevor_mahmood" in body  # from readBy


def test_the_inbox_is_the_consoles_own(console: TestClient) -> None:
    """The one place it acts as a participant — its own mail, via the agent route."""
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.get("/inbox")
    assert r.status_code == 200
    assert "check_inbox" in hub.calls


def test_composing_sends_as_the_console(console: TestClient) -> None:
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.post(
            "/compose/send",
            data={"to": "rosemary_nasrin", "subject": "hi", "body": "there"},
        )
    assert r.status_code == 200
    assert any(call.startswith("send:") for call in hub.calls)


def test_the_compose_form_renders(console: TestClient) -> None:
    """The GET form, not just the POST. A Litestar quirk 500s a sync GET when it shares
    an exact path with a sync POST; this pins that the form actually loads."""
    r = console.get("/compose")
    assert r.status_code == 200
    assert 'action="/compose/send"' in r.text


def test_compose_refuses_an_empty_message(console: TestClient) -> None:
    r = console.post("/compose/send", data={"to": "", "body": ""})
    assert r.status_code == 200
    assert "needs at least one recipient" in r.text


def test_the_console_claims_its_own_mailbox_at_startup() -> None:
    """Compose and inbox need somewhere to work, so the console joins on boot."""
    _, hub = make()
    with TestClient(app=build_console(hub)):
        pass
    assert "join" in hub.calls
