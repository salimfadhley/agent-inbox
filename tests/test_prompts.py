"""Unit tests for the prompt catalog (discovery + live rendering)."""

from __future__ import annotations

from agent_inbox import prompts
from agent_inbox.config import Config


def _config() -> Config:
    return Config().model_copy(
        update={
            "hub_name": "homelab",
            "transport": "http",
            "public_url": "http://halob:8080",
            "host_agent": "agent-inbox/host",
            "admin_agent": "agent-inbox/admin",
        }
    )


def test_catalog_lists_the_shipped_prompts() -> None:
    names = {p["name"] for p in prompts.list_prompts()}
    assert {"onboarding", "host"} <= names
    for entry in prompts.list_prompts():
        assert entry["description"]  # frontmatter parsed


def test_render_fills_live_coordinates() -> None:
    body = prompts.render_prompt("onboarding", _config())
    assert body is not None
    assert "homelab" in body  # $hub_name
    assert "http://halob:8080/<project>/<agent>/mcp" in body  # $hub_url used
    assert "$hub_url" not in body and "$host_agent" not in body  # no stray templates


def test_host_prompt_mentions_its_identity_and_onboarding_url() -> None:
    body = prompts.render_prompt("host", _config())
    assert body is not None
    assert "agent-inbox/host" in body  # $host_agent
    assert "http://halob:8080/prompts/onboarding" in body  # $prompts_url


def test_unknown_prompt_is_none_and_traversal_is_blocked() -> None:
    cfg = _config()
    assert prompts.render_prompt("does-not-exist", cfg) is None
    assert prompts.render_prompt("../config", cfg) is None
    assert prompts.render_prompt("", cfg) is None


def test_index_links_each_prompt() -> None:
    index = prompts.render_index(_config())
    assert "# homelab — prompt catalog" in index
    assert "http://halob:8080/prompts/onboarding" in index
    assert "http://halob:8080/prompts/host" in index
