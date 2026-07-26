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
import os
import sys
from pathlib import Path
from typing import Any

from agent_mailbox import __version__
from agent_mailbox.client import (
    CONFIG_NAME,
    UNNAMED,
    ClientError,
    Config,
    HubClient,
    NotConfigured,
    detect_engine,
    find_config,
    load_config,
    load_global,
    load_hub,
    project_root,
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


def cmd_console(args: argparse.Namespace) -> int:
    """Serve the human console — a browser window onto the hub."""
    try:
        import uvicorn

        from agent_mailbox.console import build_console
    except ImportError as exc:  # pragma: no cover - only without server extras
        print(f"the console needs the server dependencies: {exc}", file=sys.stderr)
        return 1
    config = load_config()
    print(f"console for {config.hub} on http://{args.host}:{args.port}")
    uvicorn.run(
        build_console(HubClient(config)),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


def cmd_reset_admin(args: argparse.Namespace) -> int:
    """Put an operator account back to first-run, and print its new password.

    Runs **on the hub**, against its own storage — so it is for whoever deploys the
    thing, not for anyone who can reach it over the network. That is the whole security
    argument: this grants nothing that possession of the server does not already grant.

    It exists because the alternative, on a hub whose only operator is locked out, is
    editing the auth tables by hand.
    """
    try:
        import anyio

        from agent_mailbox.auth.service import AuthService
        from agent_mailbox.auth.store import SqliteAuthStore
        from agent_mailbox.serve import Settings
    except ImportError as exc:  # pragma: no cover - only without server extras
        print(
            f"this runs on the hub and needs its dependencies: {exc}", file=sys.stderr
        )
        return 1

    config = Settings.from_env()
    if not config.secret_key:
        print(
            "AGENT_MAILBOX_SECRET_KEY is unset. Set the same key the hub runs with, "
            "or the reset writes an account the hub cannot read.",
            file=sys.stderr,
        )
        return 1

    async def go() -> str:
        store = SqliteAuthStore(config.db)
        async with store:
            return await AuthService(store, secret_key=config.secret_key).reset_user(
                args.username
            )

    try:
        password = anyio.run(go)
    except Exception as exc:  # noqa: BLE001 - the message is the whole output
        print(f"could not reset {args.username!r}: {exc}", file=sys.stderr)
        return 1
    print(f"{args.username} password: {password}")
    print("Sign in with it, leaving the 6-digit code blank, and enrol 2FA again.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the hub itself. Needs the server dependencies."""
    try:
        from agent_mailbox.serve import main as run_hub
    except ImportError as exc:  # pragma: no cover - only without server extras
        print(f"the hub needs the server dependencies: {exc}", file=sys.stderr)
        return 1
    run_hub(reset_user_table=args.reset_user_table)
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

    # Joining an enforcing hub needs a credential *before* there is a project config to
    # hold one, so the shared machine-wide token counts here too. Explicit beats
    # environment beats machine-wide; whichever it is, it authenticates this call.
    token = (args.token or "").strip() or os.environ.get(
        "AGENT_MAILBOX_TOKEN", ""
    ).strip()
    shared = str(load_global().get("token", "")).strip()
    client = HubClient(
        Config(
            hub=hub, name=args.name or UNNAMED, role=args.role, token=token or shared
        )
    )
    # Claim first, record second: a config asserting a refused name would be a file
    # claiming an identity that is not ours.
    claimed = client.join(args.name)
    granted = claimed.get("preferredUsername", args.name)
    # Only a token given *to this agent* is written into the project. Copying the
    # shared one in would defeat the point of having it in one place — and would
    # scatter a machine-wide secret through every repository it ever joins.
    path = write_config(
        hub,
        granted,
        engine=engine,
        role=args.role,
        force=args.force,
        token=token or None,
    )
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


def _token_help(hub_url: str, name: str, path: Path) -> str:
    """What to do about a missing device token, in the order someone can act on it.

    An agent cannot fix this alone — minting a token is an operator action behind a
    human login — so the text is written to be handed straight to a human, naming the
    exact file and key rather than describing them.
    """
    return (
        "\nThis hub authenticates, and this engine has no device token.\n"
        "A token is issued by a human operator, so ask yours to:\n\n"
        f"  1. Sign in to the console for {hub_url}\n"
        f"  2. Agents -> {name} -> Tokens -> Mint a token (it is shown once)\n"
        f"  3. Give it to you, and run:  agent-mailbox join {name} --token <token>\n\n"
        f"That writes it to {path}, under this engine's entry:\n\n"
        f'    [agents.<engine>]\n    name = "{name}"\n    token = "<token>"\n\n'
        "Do not commit that file. Nothing else needs the token — it is sent\n"
        "automatically on every call once it is there."
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check the whole path — configuration, reachability, the API, credentials.

    Four things can be wrong and they look alike from inside an agent: no config, an
    unreachable hub, a hub that answers but rejects us, and a hub that works but has
    not been told who we are. `ping` proves only the last of them. This walks the chain
    in order and stops at the first break, because a later check would only produce a
    second, more confusing error about the same cause.
    """
    ok = "ok  "
    bad = "FAIL"
    todo = "--  "
    where = find_config() or (project_root() / CONFIG_NAME)

    # 1. Configuration. Having none is the *normal* state before `join`, not an error:
    #    doctor is meant to be run first, to find out whether joining is even worth
    #    attempting. So a missing identity does not stop the connectivity check — that
    #    is the one an agent most needs answered before it asks for a name.
    config: Config | None = None
    try:
        config = load_config()
    except NotConfigured:
        pass

    hub_url = args.hub or (config.hub if config else "") or load_hub()
    if not hub_url:
        print(f"{bad} configuration   no hub url", file=sys.stderr, flush=True)
        print(
            f"     Nothing here knows where the mailbox is. Run:\n"
            f"       agent-mailbox join --hub http://<host>:8081\n"
            f"     and it will write {where} for you.",
            file=sys.stderr,
        )
        return 2

    if config is None:
        print(
            f"{todo} configuration   no entry for this engine yet ({where})",
            flush=True,
        )
        print(
            f"{todo} identity        none yet — ask the hub for one below", flush=True
        )
    else:
        print(f"{ok} configuration   {where}", flush=True)
        print(
            f"{ok} identity        {config.name} "
            f"({config.role}, engine {config.engine})"
        )

    # Without an identity there is still a hub to talk to, and reaching it is the
    # question that matters. UNNAMED never goes over the wire as a claim.
    client = HubClient(config or Config(hub=hub_url, name=UNNAMED))

    # 2. Reachability, which is the network alone — no identity, no credential. A
    #    failure here is a wrong url or a hub that is down, and saying which of the
    #    later checks was never reached saves someone chasing a credential problem
    #    that does not exist.
    try:
        hub = client.hub_info()
    except ClientError as exc:
        print(f"{bad} connectivity    {exc}", file=sys.stderr, flush=True)
        print(f"     the hub url is {hub_url}", file=sys.stderr)
        return 1
    print(
        f"{ok} connectivity    {hub_url} — {hub.get('name')} {hub.get('version')}",
        flush=True,
    )

    # 3. The hub's own verdict on us, credential included. Only the hub knows whether
    #    the token we sent was accepted, refused or revoked, and whether it has ever
    #    heard of this name — a client that guessed at those is the thing being
    #    debugged. The route answers rather than refusing, so it works when nothing
    #    else does; an older hub has no such route, which is not a fault of ours.
    remote: dict[str, Any] = {}
    try:
        remote = client.remote_doctor() or {}
    except ClientError as exc:
        print(f"{todo} hub check       not available ({exc})", flush=True)

    you = remote.get("you") or {}
    token_state = str(you.get("token", ""))
    authenticated = hub.get("authenticated") is True
    has_token = bool(config.token) if config else False

    if token_state in ("rejected", "revoked") or (authenticated and not has_token):
        # Reported before the API call rather than after: that call is about to fail,
        # and this is the reason, stated as something a person can act on.
        print(
            f"{bad} credentials     "
            + (f"token {token_state}" if token_state else "no device token"),
            file=sys.stderr,
        )
        if verdict := remote.get("verdict"):
            print(f"     the hub says: {verdict}", file=sys.stderr)
        print(
            _token_help(hub_url, config.name if config else "<your name>", where),
            file=sys.stderr,
        )
        return 1

    # Say *where* the token came from. A shared token in the machine-wide file is
    # invisible from inside the project, so "token present" alone leaves someone
    # hunting through a config that does not contain it.
    source = ""
    if has_token and config is not None:
        from agent_mailbox.client import global_config_path, load_global

        if os.environ.get("AGENT_MAILBOX_TOKEN", "").strip():
            source = " (from AGENT_MAILBOX_TOKEN)"
        elif config.token == str(load_global().get("token", "")).strip():
            source = f" (shared, from {global_config_path()})"
        else:
            source = f" (from {where})"
    print(
        f"{ok} credentials     "
        + (
            f"device token accepted by the hub{source}"
            if token_state == "accepted"
            else f"device token present{source}"
            if has_token
            else "none needed — this hub does not authenticate"
        ),
        flush=True,
    )
    if verdict := remote.get("verdict"):
        print(f"{ok} hub check       {verdict}", flush=True)

    # Reachable, and nothing is in the way — but we are nobody here yet. This is the
    # end of the road for an unjoined engine, and it is a *good* outcome: it says the
    # next step will work.
    if config is None:
        print(f"{todo} api             not joined yet", flush=True)
        print(
            "\nThe hub is reachable and ready. Ask it for a name:\n\n"
            f"    agent-mailbox join --hub {hub_url}\n\n"
            "The hub issues the name and settles uniqueness itself, so there is\n"
            "nothing to check first and nothing to retry. Add a name of your own\n"
            "only if you want one — you will be told if it is taken. Either way\n"
            f"{where} is written for you; there is no second step."
        )
        return 2

    # 4. The API, as us. Everything above can be right while a real call still fails,
    #    and only a real call finds that out.
    try:
        client.ping()
    except ClientError as exc:
        print(f"{bad} api             {exc}", file=sys.stderr, flush=True)
        if "auth" in str(exc).lower() or "token" in str(exc).lower():
            print(_token_help(hub_url, config.name, where), file=sys.stderr)
        return 1
    waiting = len(client.check_inbox().get("items", []))
    print(
        f"{ok} api             ping answered; {waiting} message(s) waiting", flush=True
    )

    if not authenticated:
        print(
            "\nNote: this hub does not authenticate. Anyone who can reach it can "
            "claim to be anyone.\nThat is fine on a trusted network and not fine on "
            "the open internet."
        )
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


def cmd_wake_check(args: argparse.Namespace) -> int:
    """Run as a Claude Code hook: notice new mail. Fail-silent, fast, announce-once."""
    from agent_mailbox.wake import run

    return run(args.event)


def cmd_install_hook(args: argparse.Namespace) -> int:
    """Install the wake hooks into this project's .claude/settings.json (merging)."""
    from pathlib import Path

    from agent_mailbox import hookconfig
    from agent_mailbox.client import project_root

    root = Path(args.dir) if args.dir else project_root()
    path = hookconfig.install(root, rewake=args.rewake)
    extra = " (with async rewake)" if args.rewake else ""
    print(f"wake hooks installed in {path}{extra}")
    print("Restart Claude Code so it picks up the hooks.")
    return 0


def cmd_uninstall_hook(args: argparse.Namespace) -> int:
    """Remove exactly our wake hooks from this project's .claude/settings.json."""
    from pathlib import Path

    from agent_mailbox import hookconfig
    from agent_mailbox.client import project_root

    root = Path(args.dir) if args.dir else project_root()
    path = hookconfig.uninstall(root)
    print(f"wake hooks removed from {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-mailbox",
        description="One mailbox tool: MCP server, terminal client, or the hub itself.",
    )
    # Without a subcommand on purpose. The onboarding prompt asks an agent to run this
    # before installing, to find out whether it already has the tool and whether that
    # copy is old enough to matter — a question it must be able to ask of a version too
    # old to know the answer, so it cannot hide behind a subcommand added later.
    parser.add_argument(
        "--version", action="version", version=f"agent-mailbox {__version__}"
    )
    subs = parser.add_subparsers(dest="mode", required=True)

    run = subs.add_parser("mcp", help="run as an MCP server over stdio (for an agent)")
    run.set_defaults(func=cmd_mcp)

    hub = subs.add_parser("serve", help="run the hub")
    # A one-shot, and the help says so: left in place it empties the table on every
    # start, so an operator would enrol, restart for some unrelated reason, and find
    # themselves a stranger to their own hub.
    hub.add_argument(
        "--reset-user-table",
        action="store_true",
        help="on this start only: delete all operator accounts and seed a new admin, "
        "printing its password. Agents' device tokens and all mail are untouched. "
        "Start once with it, take the password from the log, then remove it.",
    )
    hub.set_defaults(func=cmd_serve)

    # Runs on the hub, against its storage — an operator's escape hatch, not a route.
    reset = subs.add_parser(
        "reset-admin", help="put an operator account back to first-run (run on the hub)"
    )
    reset.add_argument("--username", default="admin", help="which account")
    reset.set_defaults(func=cmd_reset_admin)

    con = subs.add_parser("console", help="serve the human console in a browser")
    con.add_argument("--host", default="127.0.0.1", help="bind address")
    con.add_argument("--port", type=int, default=8090)
    con.set_defaults(func=cmd_console)

    join = subs.add_parser("join", help="claim a name and configure this engine")
    join.add_argument(
        "name", nargs="?", help="the name to claim; omit to be issued one"
    )
    join.add_argument("--hub", help="hub url; taken from the config file if present")
    join.add_argument("--role", default="agent", help="what this engine does here")
    join.add_argument("--engine", help="override engine detection")
    join.add_argument("--force", action="store_true", help="replace an existing entry")
    join.add_argument(
        "--token",
        help="a device token minted for this agent; saved to its entry. Not needed "
        "when a shared token is in the machine-wide config.",
    )
    join.set_defaults(func=cmd_join)

    who = subs.add_parser("whoami", help="who this engine is here")
    who.add_argument(
        "--role-definition", action="store_true", help="also fetch what the role means"
    )
    who.set_defaults(func=cmd_whoami)

    role = subs.add_parser("role", help="what a role means, according to the hub")
    role.add_argument("name", nargs="?", help="defaults to your own role")
    role.set_defaults(func=cmd_role)

    doc = subs.add_parser(
        "doctor", help="check config, connectivity, credentials and the API in order"
    )
    doc.add_argument(
        "--hub", help="hub url to test; taken from the config or the environment if set"
    )
    doc.set_defaults(func=cmd_doctor)
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

    wake = subs.add_parser(
        "wake-check", help="Claude Code hook: notice new mail (fail-silent)"
    )
    wake.add_argument(
        "--event",
        default="SessionStart",
        help="the hook event: SessionStart, UserPromptSubmit, or Stop",
    )
    wake.set_defaults(func=cmd_wake_check)

    inst = subs.add_parser(
        "install-hook", help="add the wake hooks to .claude/settings.json"
    )
    inst.add_argument("--dir", help="project dir (default: this repo root)")
    inst.add_argument(
        "--rewake",
        action="store_true",
        help="also wake a fully idle session (async; needs a live-session check)",
    )
    inst.set_defaults(func=cmd_install_hook)

    uninst = subs.add_parser(
        "uninstall-hook", help="remove the wake hooks from .claude/settings.json"
    )
    uninst.add_argument("--dir", help="project dir (default: this repo root)")
    uninst.set_defaults(func=cmd_uninstall_hook)

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
