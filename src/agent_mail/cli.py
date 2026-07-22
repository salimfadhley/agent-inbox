"""The ``agent-mail`` command-line primitive."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Sequence

import click

from agent_mail.config import Config
from agent_mail.exceptions import ConfigError, MailboxError
from agent_mail.mailbox import Mailbox
from agent_mail.models import Intent, Message

logger = logging.getLogger(__name__)


def _run[T](coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _fail(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    raise SystemExit(1)


async def _with_mailbox[T](
    config: Config, action: Callable[[Mailbox], Awaitable[T]]
) -> T:
    async with Mailbox(config) as mailbox:
        return await action(mailbox)


def _message_dict(message: Message) -> dict[str, object]:
    return message.model_dump(by_alias=True, mode="json")


def _print_message_human(message: Message, *, full: bool) -> None:
    click.echo(f"[{message.id}] {message.intent.value}")
    click.echo(f"  from:    {message.from_}")
    click.echo(f"  to:      {message.to}")
    click.echo(f"  thread:  {message.thread}")
    click.echo(f"  subject: {message.subject}")
    click.echo(f"  created: {message.created.isoformat()}")
    if full:
        click.echo("  ---")
        for line in message.body.splitlines() or [""]:
            click.echo(f"  {line}")


def _emit(payload: object, *, as_json: bool, human: Callable[[], None]) -> None:
    if as_json:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        human()


@click.group()
@click.option(
    "--from",
    "from_",
    default=None,
    help="Your agent identity (overrides AGENT_ID).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON instead of human text.",
)
@click.pass_context
def cli(ctx: click.Context, from_: str | None, as_json: bool) -> None:
    """A NATS JetStream mailbox for local LLM agents."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.from_env(agent_override=from_)
    ctx.obj["as_json"] = as_json


@cli.command()
@click.option("--to", required=True, help="Recipient agent id.")
@click.option("--subject", required=True, help="Message subject.")
@click.option("--body", required=True, help="Message body.")
@click.option("--thread", default=None, help="Thread id to attach to (optional).")
@click.option(
    "--intent",
    type=click.Choice([i.value for i in Intent]),
    default=Intent.message.value,
    help="Message intent.",
)
@click.pass_context
def send(
    ctx: click.Context,
    to: str,
    subject: str,
    body: str,
    thread: str | None,
    intent: str,
) -> None:
    """Send a message to another agent."""
    config: Config = ctx.obj["config"]
    as_json: bool = ctx.obj["as_json"]
    try:
        sender = config.require_identity()
        message = Message(
            from_=sender,
            to=to,
            subject=subject,
            body=body,
            thread=thread,
            intent=Intent(intent),
        )
        _run(_with_mailbox(config, lambda mb: mb.send(message)))
    except (ConfigError, MailboxError) as exc:
        _fail(str(exc))
    logger.info("sent %s to %s", message.id, message.to)
    _emit(
        _message_dict(message),
        as_json=as_json,
        human=lambda: click.echo(f"sent [{message.id}] to {message.to}"),
    )


@cli.command()
@click.pass_context
def inbox(ctx: click.Context) -> None:
    """List unread messages addressed to me (peek — does not ack)."""
    config: Config = ctx.obj["config"]
    as_json: bool = ctx.obj["as_json"]
    try:
        me = config.require_identity()
        messages = _run(_with_mailbox(config, lambda mb: mb.peek(me)))
    except (ConfigError, MailboxError) as exc:
        _fail(str(exc))
        return

    logger.info("inbox for %s: %d unread", config.agent_id, len(messages))

    def human() -> None:
        if not messages:
            click.echo("inbox empty")
            return
        click.echo(f"{len(messages)} unread message(s):")
        for message in messages:
            _print_message_human(message, full=False)

    _emit([_message_dict(m) for m in messages], as_json=as_json, human=human)


@cli.command()
@click.argument("message_id")
@click.pass_context
def read(ctx: click.Context, message_id: str) -> None:
    """Show a message and ack it (consume)."""
    config: Config = ctx.obj["config"]
    as_json: bool = ctx.obj["as_json"]
    try:
        me = config.require_identity()
        message = _run(_with_mailbox(config, lambda mb: mb.read(me, message_id)))
    except (ConfigError, MailboxError) as exc:
        _fail(str(exc))
        return
    logger.info("read %s", message_id)
    _emit(
        _message_dict(message),
        as_json=as_json,
        human=lambda: _print_message_human(message, full=True),
    )


@cli.command()
@click.argument("message_id")
@click.option("--body", required=True, help="Reply body.")
@click.option("--subject", default=None, help="Override the reply subject.")
@click.pass_context
def reply(ctx: click.Context, message_id: str, body: str, subject: str | None) -> None:
    """Reply on the same thread and ack the original."""
    config: Config = ctx.obj["config"]
    as_json: bool = ctx.obj["as_json"]
    try:
        me = config.require_identity()
        message = _run(
            _with_mailbox(config, lambda mb: mb.reply(me, message_id, body, subject))
        )
    except (ConfigError, MailboxError) as exc:
        _fail(str(exc))
        return
    logger.info("replied %s on thread %s", message.id, message.thread)
    _emit(
        _message_dict(message),
        as_json=as_json,
        human=lambda: click.echo(
            f"replied [{message.id}] to {message.to} on thread {message.thread}"
        ),
    )


@cli.command()
@click.option("--to", required=True, help="Recipient agent id.")
@click.option("--thread", default=None, help="Thread the wake refers to (optional).")
@click.pass_context
def notify(ctx: click.Context, to: str, thread: str | None) -> None:
    """Publish a lightweight 'you have mail' wake signal (non-durable)."""
    config: Config = ctx.obj["config"]
    as_json: bool = ctx.obj["as_json"]
    try:
        _run(_with_mailbox(config, lambda mb: mb.notify(to, thread)))
    except (ConfigError, MailboxError) as exc:
        _fail(str(exc))
    logger.info("notified %s", to)
    _emit(
        {"notified": to, "thread": thread},
        as_json=as_json,
        human=lambda: click.echo(f"notified {to}"),
    )


@cli.command(name="mcp-serve")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default=None,
    envvar="AGENT_MAIL_TRANSPORT",
    help="MCP transport: stdio (local, single agent) or http (hosted, multi-agent).",
)
@click.option(
    "--host",
    default=None,
    envvar="AGENT_MAIL_HOST",
    help="Bind host for http transport (default 127.0.0.1).",
)
@click.option(
    "--port",
    type=int,
    default=None,
    envvar="AGENT_MAIL_PORT",
    help="Bind port for http transport (default 8080).",
)
@click.option(
    "--path",
    "path_",
    default=None,
    envvar="AGENT_MAIL_PATH",
    help="Mount path for http transport (default /mcp).",
)
@click.pass_context
def mcp_serve(
    ctx: click.Context,
    transport: str | None,
    host: str | None,
    port: int | None,
    path_: str | None,
) -> None:
    """Run the MCP server exposing the same verbs as tools.

    Over http the server is multi-agent: each agent connects on its own address,
    ``http://<host>:<port>/<agent>/mcp``, which is its whole configuration.
    """
    from agent_mail.mcp_server import serve

    base: Config = ctx.obj["config"]
    updates: dict[str, object] = {}
    if transport:
        updates["transport"] = transport
    if host:
        updates["host"] = host
    if port is not None:
        updates["port"] = port
    if path_:
        updates["path"] = path_
    config = base.model_copy(update=updates) if updates else base
    serve(config)


def _setup_logging() -> None:
    level = os.environ.get("AGENT_MAIL_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Console entry point."""
    _setup_logging()
    cli.main(args=list(argv) if argv is not None else None, standalone_mode=True)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
