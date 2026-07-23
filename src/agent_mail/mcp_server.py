"""FastMCP wrapper exposing the mailbox verbs as MCP tools.

Every tool delegates to :class:`agent_mail.mailbox.Mailbox` — the same core the CLI
uses — so there is no logic duplication.

Two ways to run it:

* **stdio** (local, single agent): identity comes from ``AGENT_MAIL_PROJECT`` +
  ``AGENT_ID``. This is how a Claude/Codex client spawns the server as a subprocess.
* **http** (hosted, multi-agent): one server serves many agents. Each agent connects
  on its own address — ``http://<host>:<port>/<project>/<agent>/mcp`` — and the path
  names the caller. That URL is the agent's entire configuration.
  ``?project=&agent=`` and ``X-Agent-Project`` + ``X-Agent-Id`` headers also work.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from agent_mail.config import Config, format_address, hub_descriptor, hub_version
from agent_mail.identity import (
    reset_current_agent,
    resolve_identity,
    set_current_agent,
)
from agent_mail.mailbox import Mailbox
from agent_mail.models import Intent, Message

logger = logging.getLogger(__name__)

# agent-mail is trusted-network software with no built-in auth (front it with a
# reverse proxy on untrusted networks). MCP's DNS-rebinding protection only allows
# localhost Host headers by default, which makes a hosted server unreachable by
# remote agents — so we disable it and serve any Host.
# The server name clients see. Defaults to "agent-mail" and is overridable via
# MCP_SERVER_NAME — so renaming the project need not force every agent to
# re-register and reconnect.
mcp = FastMCP(
    os.environ.get("MCP_SERVER_NAME", "agent-mail"),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


_STARTED_MONO = time.monotonic()


def _config() -> Config:
    return Config.from_env()


def _dump(message: Message) -> dict[str, Any]:
    return message.model_dump(by_alias=True, mode="json")


def _envelope(config: Config, project: str, agent: str) -> dict[str, Any]:
    """Mailbox context returned alongside inbox responses (an 'envelope').

    Per-message metadata (the sender ``from`` and the sent time ``created``) already
    lives on each message; this adds the mailbox's own context.
    """
    now = datetime.now(tz=UTC)
    return {
        "hub": config.hub_name,
        "version": hub_version(),
        "now": now.isoformat(),
        "timezone": "UTC",
        "uptime_seconds": round(time.monotonic() - _STARTED_MONO, 1),
        "your_address": format_address(project, agent),
    }


@mcp.tool()
async def send_message(
    to: str,
    subject: str,
    body: str,
    thread: str | None = None,
    intent: str = Intent.message.value,
) -> dict[str, Any]:
    """Send a message. ``to`` is ``project/agent`` (direct), ``project`` (any one
    agent), or ``project/*`` (broadcast to all). Returns the sent message."""
    config = _config()
    project, agent = resolve_identity(config)
    message = Message(
        from_=format_address(project, agent),
        to=to,
        subject=subject,
        body=body,
        thread=thread,
        intent=Intent(intent),
    )
    async with Mailbox(config) as mailbox:
        await mailbox.send(message)
    return _dump(message)


@mcp.tool()
async def check_inbox() -> dict[str, Any]:
    """List my unread messages without consuming them (peek). Call each turn.

    Returns an envelope: ``{"mailbox": {hub, version, now, timezone, uptime_seconds,
    your_address}, "messages": [...]}``. Each message carries its sender (``from``)
    and sent time (``created``).
    """
    config = _config()
    project, agent = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        messages = await mailbox.peek(project, agent)
    return {
        "mailbox": _envelope(config, project, agent),
        "messages": [_dump(m) for m in messages],
    }


@mcp.tool()
async def read_message(message_id: str) -> dict[str, Any]:
    """Read one message by id and ack (consume) it.

    Returns ``{"mailbox": {...context...}, "message": {...}}``.
    """
    config = _config()
    project, agent = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        message = await mailbox.read(project, agent, message_id)
    return {
        "mailbox": _envelope(config, project, agent),
        "message": _dump(message),
    }


@mcp.tool()
async def reply_message(
    message_id: str, body: str, subject: str | None = None
) -> dict[str, Any]:
    """Reply directly to the sender and ack the original. Returns the reply message."""
    config = _config()
    project, agent = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        reply = await mailbox.reply(project, agent, message_id, body, subject)
    return _dump(reply)


@mcp.tool()
async def notify_agent(to: str, thread: str | None = None) -> dict[str, Any]:
    """Wake a target (non-durable). ``to`` is ``project/agent``, ``project``, or
    ``project/*``."""
    config = _config()
    async with Mailbox(config) as mailbox:
        await mailbox.notify(to, thread)
    return {"notified": to, "thread": thread}


@mcp.tool()
async def ping() -> dict[str, Any]:
    """Round-trip a message to yourself to confirm agent-mail is operational.

    Good to call once on sign-on: it verifies connectivity, your identity, and that
    send + inbox + read all work. Consumes only its own probe.
    """
    config = _config()
    project, agent = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        received = await mailbox.ping(project, agent)
    return {
        "ok": True,
        "agent": format_address(project, agent),
        "message_id": received.id,
    }


@mcp.tool()
async def hub_info() -> dict[str, Any]:
    """Describe this agent-mail hub: name, version, addressing, limits, and contacts.

    Non-secret. Call on sign-on to learn which hub you reached, the max message size
    (`limits.max_message_bytes`), and who administers it.
    """
    config = _config()
    return hub_descriptor(config, max_message_bytes=config.max_message_bytes)


# -- HTTP multi-tenant identity middleware --------------------------------------

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class AgentIdentityMiddleware:
    """Resolve the calling agent from the request URL and bind it for the handler.

    Rewrites ``/<project>/<agent>/mcp`` to the plain mount path before delegating, so
    the same underlying MCP app serves every agent. Also answers ``GET /health`` and
    serves the hub descriptor at ``GET /`` (and ``/hub``) directly.
    """

    def __init__(self, app: ASGIApp, mount_path: str, hub_json: bytes) -> None:
        self._app = app
        self._mount = mount_path.rstrip("/") or "/mcp"
        self._hub_json = hub_json
        self._pattern = re.compile(
            rf"^/(?P<project>[^/]+)/(?P<agent>[^/]+){re.escape(self._mount)}"
            r"(?P<rest>/.*)?$"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        path = scope.get("path")
        if path == "/health":
            await self._json(send, b'{"status":"ok"}')
            return
        if path in ("/", "/hub"):
            await self._json(send, self._hub_json)
            return
        address = self._extract(scope)
        token = set_current_agent(address)
        try:
            await self._app(scope, receive, send)
        finally:
            reset_current_agent(token)

    def _extract(self, scope: Scope) -> tuple[str, str] | None:
        match = self._pattern.match(scope.get("path", ""))
        if match:
            rest = match.group("rest") or ""
            new_path = self._mount + rest
            scope["path"] = new_path
            scope["raw_path"] = new_path.encode()
            return match.group("project"), match.group("agent")
        query = parse_qs(scope.get("query_string", b"").decode())
        if query.get("project") and query.get("agent"):
            return query["project"][0], query["agent"][0]
        headers = {k: v for k, v in (scope.get("headers") or [])}
        project = headers.get(b"x-agent-project")
        agent = headers.get(b"x-agent-id")
        if project and agent:
            return project.decode(), agent.decode()
        return None

    @staticmethod
    async def _json(send: Send, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_http_app(config: Config, max_message_bytes: int | None = None) -> ASGIApp:
    """Build the multi-tenant ASGI app for the hosted MCP server."""
    mcp.settings.streamable_http_path = config.path
    hub_json = json.dumps(hub_descriptor(config, max_message_bytes)).encode()
    return AgentIdentityMiddleware(mcp.streamable_http_app(), config.path, hub_json)


def serve(config: Config | None = None) -> None:
    """Run the MCP server over the configured transport."""
    config = config or _config()
    if config.transport == "http":
        import uvicorn

        # The hub advertises its configured max message size on GET /.
        max_size = config.max_message_bytes
        logger.info(
            "serving MCP over http on %s:%s (agents connect on /<project>/<agent>%s)",
            config.host,
            config.port,
            config.path,
        )
        uvicorn.run(
            build_http_app(config, max_size), host=config.host, port=config.port
        )
    else:
        logger.info("serving MCP over stdio as %s/%s", config.project, config.agent_id)
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    serve()
