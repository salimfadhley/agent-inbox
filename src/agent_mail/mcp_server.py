"""FastMCP wrapper exposing the mailbox verbs as MCP tools.

Every tool delegates to :class:`agent_mail.mailbox.Mailbox` — the same core the CLI
uses — so there is no logic duplication.

Two ways to run it:

* **stdio** (local, single agent): identity comes from ``AGENT_ID``. This is how a
  Claude/Codex client spawns the server as a subprocess.
* **http** (hosted, multi-agent): one server serves many agents. Each agent connects
  on its own address — ``http://<host>:<port>/<agent>/mcp`` — and the path names the
  caller. That URL is the agent's entire configuration. ``?agent=`` and an
  ``X-Agent-Id`` header are accepted as alternatives.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP

from agent_mail.config import Config
from agent_mail.identity import (
    reset_current_agent,
    resolve_identity,
    set_current_agent,
)
from agent_mail.mailbox import Mailbox
from agent_mail.models import Intent, Message

logger = logging.getLogger(__name__)

mcp = FastMCP("agent-mail")


def _config() -> Config:
    return Config.from_env()


def _dump(message: Message) -> dict[str, Any]:
    return message.model_dump(by_alias=True, mode="json")


@mcp.tool()
async def send_message(
    to: str,
    subject: str,
    body: str,
    thread: str | None = None,
    intent: str = Intent.message.value,
) -> dict[str, Any]:
    """Send a message to another agent's durable inbox. Returns the sent message."""
    config = _config()
    sender = resolve_identity(config)
    message = Message(
        from_=sender,
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
async def check_inbox() -> list[dict[str, Any]]:
    """List my unread messages without consuming them (peek). Call each turn."""
    config = _config()
    me = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        messages = await mailbox.peek(me)
    return [_dump(m) for m in messages]


@mcp.tool()
async def read_message(message_id: str) -> dict[str, Any]:
    """Read one message by id and ack (consume) it."""
    config = _config()
    me = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        message = await mailbox.read(me, message_id)
    return _dump(message)


@mcp.tool()
async def reply_message(
    message_id: str, body: str, subject: str | None = None
) -> dict[str, Any]:
    """Reply on the same thread and ack the original. Returns the reply message."""
    config = _config()
    me = resolve_identity(config)
    async with Mailbox(config) as mailbox:
        reply = await mailbox.reply(me, message_id, body, subject)
    return _dump(reply)


@mcp.tool()
async def notify_agent(to: str, thread: str | None = None) -> dict[str, Any]:
    """Publish a lightweight 'you have mail' wake signal (non-durable)."""
    config = _config()
    async with Mailbox(config) as mailbox:
        await mailbox.notify(to, thread)
    return {"notified": to, "thread": thread}


# -- HTTP multi-tenant identity middleware --------------------------------------

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class AgentIdentityMiddleware:
    """Resolve the calling agent from the request URL and bind it for the handler.

    Rewrites ``/<agent>/mcp`` to the plain mount path before delegating, so the same
    underlying MCP app serves every agent. Also answers ``GET /health`` directly.
    """

    def __init__(self, app: ASGIApp, mount_path: str) -> None:
        self._app = app
        self._mount = mount_path.rstrip("/") or "/mcp"
        self._pattern = re.compile(
            rf"^/(?P<agent>[^/]+){re.escape(self._mount)}(?P<rest>/.*)?$"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        if scope.get("path") == "/health":
            await self._health(send)
            return
        agent = self._extract(scope)
        token = set_current_agent(agent)
        try:
            await self._app(scope, receive, send)
        finally:
            reset_current_agent(token)

    def _extract(self, scope: Scope) -> str | None:
        match = self._pattern.match(scope.get("path", ""))
        if match:
            rest = match.group("rest") or ""
            new_path = self._mount + rest
            scope["path"] = new_path
            scope["raw_path"] = new_path.encode()
            return match.group("agent")
        query = scope.get("query_string", b"")
        if query:
            values = parse_qs(query.decode())
            if values.get("agent"):
                return values["agent"][0]
        for key, value in scope.get("headers") or []:
            if key == b"x-agent-id" and value:
                return value.decode()
        return None

    @staticmethod
    async def _health(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"status":"ok"}'})


def build_http_app(config: Config) -> ASGIApp:
    """Build the multi-tenant ASGI app for the hosted MCP server."""
    mcp.settings.streamable_http_path = config.path
    return AgentIdentityMiddleware(mcp.streamable_http_app(), config.path)


def serve(config: Config | None = None) -> None:
    """Run the MCP server over the configured transport."""
    config = config or _config()
    if config.transport == "http":
        import uvicorn

        logger.info(
            "serving MCP over http on %s:%s (agents connect on /<agent>%s)",
            config.host,
            config.port,
            config.path,
        )
        uvicorn.run(build_http_app(config), host=config.host, port=config.port)
    else:
        logger.info("serving MCP over stdio as agent %r", config.agent_id)
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    serve()
