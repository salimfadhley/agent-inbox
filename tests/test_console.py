"""The console's prompt page.

What is worth testing here is not the HTML. It is that the page hands out a prompt
carrying **this** hub's address, because the whole reason the page exists is that a
placeholder is something a human gets wrong. A page that renders beautifully with
`localhost` in the commands has failed at its only job.
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
    """A hub that answers without a network, so the page can be rendered alone."""

    def __init__(self) -> None:
        super().__init__(Config(hub=HUB, name="operator"))

    def hub_info(self) -> dict[str, Any]:
        return {
            "id": HUB,
            "name": "testhub",
            "version": "1.2.3",
            "authenticated": False,
        }

    def list_agents(self) -> dict[str, Any]:
        return {"items": []}


@pytest.fixture
def console() -> Iterator[TestClient]:
    with TestClient(app=build_console(StubHub())) as c:
        yield c


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

    class Sidecar(StubHub):
        def __init__(self) -> None:
            HubClient.__init__(self, Config(hub="http://agent-mailbox:8080", name="c"))

    with TestClient(app=build_console(Sidecar())) as c:
        text = c.get("/prompts.txt").text
    assert HUB in text
    assert "agent-mailbox:8080" not in text


def test_the_plain_text_form_is_the_same_prompt(console: TestClient) -> None:
    """`/prompts.txt` exists so it can be curled; it must not drift from the page."""
    page = console.get("/prompts")
    text = console.get("/prompts.txt")
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    # Every line of the prompt appears in the page, escaped but intact.
    assert "uv tool install" in text.text
    assert "uv tool install" in page.text


def test_there_is_exactly_one_prompt(console: TestClient) -> None:
    """No per-role pages. Three prompts drifted apart last time; one cannot.

    Role is configuration, so a page offering a choice of prompt would be the bug.
    """
    body = console.get("/prompts").text
    for role in ("agent", "host", "admin"):
        assert f'href="/prompts/{role}"' not in body
    assert "agent-mailbox.toml" in body


def test_the_prompt_says_the_hub_does_not_authenticate(console: TestClient) -> None:
    """An agent must learn this from the prompt, not by being surprised by it."""
    assert "does not authenticate" in console.get("/prompts.txt").text


def test_the_prompt_names_the_command_that_exists(console: TestClient) -> None:
    """`agent-mailbox mcp` — one binary, modes. The old name was a separate script."""
    text = console.get("/prompts.txt").text
    assert "agent-mailbox mcp" in text
    assert "agent-mailbox-mcp" not in text


def test_the_prompt_page_is_reachable_from_every_page(console: TestClient) -> None:
    """An operator who does not know the page exists cannot use it."""
    assert 'href="/prompts"' in console.get("/").text
