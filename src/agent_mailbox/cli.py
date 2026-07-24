"""One tool, several modes.

``agent-mailbox`` is the only command. It runs as an MCP server for an agent, as a
terminal client for a human, or as the hub itself — and in every mode it is the thing
that **owns the local configuration**.

That ownership is the point. Nobody hand-writes ``agent-mailbox.toml``: the first time
an engine runs here it claims a name and records itself, and because the file persists,
every later run is already configured. A second engine in the same directory gets its
own entry and does not disturb the first.

Standard library only. A tool an agent installs should not drag a dependency tree behind
it, and argparse is enough for a dozen subcommands.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_mailbox.client import (
    CONFIG_NAME,
    ClientError,
    Config,
    HubClient,
    NotConfigured,
    detect_engine,
    load_config,
    load_hub,
    write_config,
)


def _client() -> HubClient:
    return HubClient(load_config())


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2) if not isinstance(value, str) else value)


# -- modes -------------------------------------------------------------------


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run as an MCP server over stdio, for an agent."""
    from agent_mailbox.mcp_client import main as run_mcp

    run_mcp()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the hub itself. Needs the server dependencies."""
    try:
        from agent_mailbox.serve import main as run_hub
    except ImportError as exc:  # pragma: no cover - only without server extras
        print(f"the hub needs the server dependencies: {exc}", file=sys.stderr)
        return 1
    run_hub()
    return 0


# -- configuration -----------------------------------------------------------


def cmd_join(args: argparse.Namespace) -> int:
    """Claim a name and record this engine in the project's configuration."""
    engine = args.engine or detect_engine()
    if engine is None:
        print(
            "cannot tell which engine this is — pass --engine, so that two agents in "
            "this directory do not end up sharing one identity.",
            file=sys.stderr,
        )
        return 1

    hub = args.hub or load_hub()
    if not hub:
        print(
            f"no hub known. Pass --hub, or put one in {CONFIG_NAME}.", file=sys.stderr
        )
        return 1

    client = HubClient(Config(hub=hub, name=args.name or "unnamed", role=args.role))
    # Claim first, record second: a config asserting a refused name would be a file
    # claiming an identity that is not ours.
    claimed = client.join(args.name)
    granted = claimed.get("preferredUsername", args.name)
    path = write_config(hub, granted, engine=engine, role=args.role, force=args.force)
    _print({"name": granted, "role": args.role, "engine": engine, "config": str(path)})
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    """Who this engine is on this project, and what its role means."""
    config = load_config()
    out: dict[str, Any] = {
        "name": config.name,
        "role": config.role,
        "engine": config.engine,
        "hub": config.hub,
    }
    if args.role_definition:
        out["role_definition"] = HubClient(config).role_definition(config.role)
    _print(out)
    return 0


def cmd_role(args: argparse.Namespace) -> int:
    """What a role means, according to the hub.

    Definitions live on the hub rather than in a prompt page per role. Three separate
    pages drift out of step with each other and with the code; one source does not, and
    changing what a role means does not mean re-onboarding anyone.
    """
    config = load_config()
    _print(HubClient(config).role_definition(args.name or config.role))
    return 0


# -- mailbox -----------------------------------------------------------------


def cmd_ping(args: argparse.Namespace) -> int:
    _print(_client().ping())
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    page = _client().check_inbox()
    items = page.get("items", [])
    if not items:
        print("nothing waiting")
        return 0
    for note in items:
        sender = (note.get("attributedTo") or "").rsplit("/", 1)[-1]
        ident = (note.get("id") or "").rsplit("/", 1)[-1]
        print(f"{ident}  {sender:20} {note.get('summary') or '(no subject)'}")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    sent = _client().send_message(args.to, args.body, args.subject)
    _print({"sent": sent.get("id"), "to": sent.get("to")})
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    note = _client().read_message(args.id)
    print(f"from    : {(note.get('attributedTo') or '').rsplit('/', 1)[-1]}")
    print(f"subject : {note.get('summary') or '(none)'}")
    print()
    print(note.get("content", ""))
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    _print(_client().reply_message(args.id, args.body, args.subject))
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    for actor in _client().list_agents().get("items", []):
        name = actor.get("preferredUsername", "?")
        role = (actor.get("profile") or {}).get("role", "")
        about = (actor.get("summary") or "").split(".")[0]
        print(f"{name:24} {role:10} {about[:60]}")
    return 0


def cmd_hub(args: argparse.Namespace) -> int:
    _print(_client().hub_info())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-mailbox",
        description="One mailbox tool: MCP server, terminal client, or the hub itself.",
    )
    subs = parser.add_subparsers(dest="mode", required=True)

    run = subs.add_parser("mcp", help="run as an MCP server over stdio (for an agent)")
    run.set_defaults(func=cmd_mcp)

    hub = subs.add_parser("serve", help="run the hub")
    hub.set_defaults(func=cmd_serve)

    join = subs.add_parser("join", help="claim a name and configure this engine")
    join.add_argument(
        "name", nargs="?", help="the name to claim; omit to be issued one"
    )
    join.add_argument("--hub", help="hub url; taken from the config file if present")
    join.add_argument("--role", default="agent", help="what this engine does here")
    join.add_argument("--engine", help="override engine detection")
    join.add_argument("--force", action="store_true", help="replace an existing entry")
    join.set_defaults(func=cmd_join)

    who = subs.add_parser("whoami", help="who this engine is here")
    who.add_argument(
        "--role-definition", action="store_true", help="also fetch what the role means"
    )
    who.set_defaults(func=cmd_whoami)

    role = subs.add_parser("role", help="what a role means, according to the hub")
    role.add_argument("name", nargs="?", help="defaults to your own role")
    role.set_defaults(func=cmd_role)

    subs.add_parser("ping", help="prove the connection").set_defaults(func=cmd_ping)
    subs.add_parser("inbox", help="what is waiting").set_defaults(func=cmd_inbox)
    subs.add_parser("agents", help="who is on the hub").set_defaults(func=cmd_agents)
    subs.add_parser("hub", help="what this hub is").set_defaults(func=cmd_hub)

    send = subs.add_parser("send", help="send a message")
    send.add_argument("to")
    send.add_argument("body")
    send.add_argument("-s", "--subject")
    send.set_defaults(func=cmd_send)

    read = subs.add_parser("read", help="read and consume a message")
    read.add_argument("id")
    read.set_defaults(func=cmd_read)

    reply = subs.add_parser("reply", help="reply to a message")
    reply.add_argument("id")
    reply.add_argument("body")
    reply.add_argument("-s", "--subject")
    reply.set_defaults(func=cmd_reply)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except NotConfigured as exc:
        print(exc, file=sys.stderr)
        return 2
    except ClientError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
