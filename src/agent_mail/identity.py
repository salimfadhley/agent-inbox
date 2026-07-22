"""Per-request agent identity for the hosted MCP server.

When the MCP server runs over HTTP it is multi-tenant: many agents share one URL
*base* but each connects on its own address — ``/<agent>/mcp`` — so the request path
(or an ``?agent=`` query / ``X-Agent-Id`` header) says who is calling. The ASGI
middleware stashes that in a :class:`~contextvars.ContextVar`; the MCP tools read it
back here. Over stdio (single-tenant) the contextvar is unset and identity falls back
to ``AGENT_ID`` from the :class:`~agent_mail.config.Config`.
"""

from __future__ import annotations

from contextvars import ContextVar

from agent_mail.config import Config, validate_agent_id
from agent_mail.exceptions import ConfigError

_current_agent: ContextVar[str | None] = ContextVar(
    "agent_mail_current_agent", default=None
)


def set_current_agent(agent_id: str | None) -> object:
    """Bind the calling agent for the current context; returns a reset token."""
    return _current_agent.set(agent_id)


def reset_current_agent(token: object) -> None:
    """Undo a previous :func:`set_current_agent` using its token."""
    _current_agent.reset(token)  # type: ignore[arg-type]


def resolve_identity(config: Config) -> str:
    """Return the validated identity of the calling agent.

    Prefers the per-request identity (HTTP, multi-tenant); falls back to the
    server's ``AGENT_ID`` (stdio, single-tenant). Raises :class:`ConfigError` if
    neither is set.
    """
    per_request = _current_agent.get()
    if per_request:
        return validate_agent_id(per_request)
    if config.agent_id:
        return validate_agent_id(config.agent_id)
    raise ConfigError(
        "no agent identity for this request: connect on /<agent>/mcp "
        "(or set AGENT_ID for a single-agent server)"
    )
