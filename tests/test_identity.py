"""Unit tests for per-request identity resolution and the ASGI middleware."""

from __future__ import annotations

import pytest

from agent_mail.config import Config
from agent_mail.exceptions import ConfigError
from agent_mail.identity import (
    reset_current_agent,
    resolve_identity,
    set_current_agent,
)
from agent_mail.mcp_server import AgentIdentityMiddleware


def _config(agent: str | None) -> Config:
    return Config().model_copy(update={"agent_id": agent})


def test_per_request_identity_wins_over_env() -> None:
    token = set_current_agent("alice")
    try:
        assert resolve_identity(_config("server-default")) == "alice"
    finally:
        reset_current_agent(token)


def test_falls_back_to_env_identity() -> None:
    assert resolve_identity(_config("bob")) == "bob"


def test_raises_without_any_identity() -> None:
    with pytest.raises(ConfigError):
        resolve_identity(_config(None))


def test_invalid_per_request_identity_rejected() -> None:
    token = set_current_agent("bad id")
    try:
        with pytest.raises(ConfigError):
            resolve_identity(_config(None))
    finally:
        reset_current_agent(token)


def _extract(path: str, query: bytes = b"", headers: list | None = None) -> str | None:
    mw = AgentIdentityMiddleware(app=_noop, mount_path="/mcp")
    scope = {
        "type": "http",
        "path": path,
        "query_string": query,
        "headers": headers or [],
    }
    agent = mw._extract(scope)
    return agent, scope["path"]  # type: ignore[return-value]


async def _noop(scope, receive, send):  # pragma: no cover - not invoked
    return None


def test_path_identity_is_extracted_and_rewritten() -> None:
    agent, rewritten = _extract("/casework/mcp")  # type: ignore[misc]
    assert agent == "casework"
    assert rewritten == "/mcp"


def test_path_identity_preserves_subpath() -> None:
    agent, rewritten = _extract("/casework/mcp/messages")  # type: ignore[misc]
    assert agent == "casework"
    assert rewritten == "/mcp/messages"


def test_query_identity_is_extracted() -> None:
    agent, rewritten = _extract("/mcp", query=b"agent=alice")  # type: ignore[misc]
    assert agent == "alice"
    assert rewritten == "/mcp"


def test_header_identity_is_extracted() -> None:
    agent, _ = _extract("/mcp", headers=[(b"x-agent-id", b"gemini")])  # type: ignore[misc]
    assert agent == "gemini"


def test_plain_mount_has_no_identity() -> None:
    agent, _ = _extract("/mcp")  # type: ignore[misc]
    assert agent is None
