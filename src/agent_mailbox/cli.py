"""One tool, several modes.

``agent-inbox`` is the command (``agent-mailbox`` is the same program under its older
name). It runs as an MCP server for an agent, as a terminal client for a human, or as
the hub itself — and in every mode it is the thing that **owns the local
configuration**.

That ownership is the point. Nobody hand-writes ``agent-mailbox.toml``: the first time
an engine runs here it claims a name and records itself, and because the file persists,
every later run is already configured. A second engine in the same directory gets its
own entry and does not disturb the first. `config` is how anything in either file is
changed, so that no one has to know which file, which engine's entry, or what
permissions a file holding a credential needs.

Built on click. The CLI grew past what argparse does gracefully — a flag written
anywhere but one exact position in `config set --global name value` was rejected as
"unrecognized arguments", which is a parser limitation presented to the user as their
mistake. click adds one pure-Python dependency (its only requirement is colorama, and
only on Windows) and it is now a base dependency rather than a client-only one, because
the hub's own entry point runs through this module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click

from agent_mailbox import __version__
from agent_mailbox.client import (
    CONFIG_NAME,
    UNNAMED,
    ClientError,
    Config,
    HubClient,
    NotConfigured,
    detect_engine,
    duplicate_names,
    effective_settings,
    find_config,
    global_config_path,
    load_config,
    load_global,
    load_hub,
    project_root,
    unset_global,
    unset_project,
    write_config,
    write_global,
    write_project,
)

#: Settings `config` will write. Anything else is a typo, and a typo silently accepted
#: leaves a file that reads correct and is not.
KNOWN_SETTINGS = ("hub", "name", "role", "token")

#: Per project, never machine-wide: the same engine in two repositories is two
#: correspondents, and one machine-wide name would quietly merge them into one inbox.
PROJECT_ONLY = ("name", "role")

EPILOG = """\
WHERE YOU RUN IT MATTERS. Identity is per project, so anything acting as an agent —
join, config, doctor, ping, inbox, send, read, reply, agents, whoami, role, hub — reads
agent-mailbox.toml from the directory you are in, searching upwards and stopping at the
repository root. Run those inside the project. A shared token may live machine-wide
(`config set --global token <token>`), because a credential admits the machine rather
than naming an agent.

`mcp` needs no particular directory: it asks the client that launched it for the
workspace, falls back to this one, and takes which engine it serves from the client's
own name. `--project` settles it for a client that offers neither.

`serve` and `console` are the hub and its window: configured by the environment
(AGENT_MAILBOX_*), not by a project, and they run anywhere.
"""


def _client() -> HubClient:
    return HubClient(load_config())


def _print(value: Any) -> None:
    click.echo(json.dumps(value, indent=2) if not isinstance(value, str) else value)


def _err(message: str) -> None:
    click.echo(message, err=True)


class AliasedGroup(click.Group):
    """A group whose commands may answer to more than one name.

    Only for names people demonstrably type: `config`/`configure` is one command, and
    making someone guess which we chose is a poor way to spend their attention.
    """

    aliases: dict[str, str] = {"configure": "config"}

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        return super().get_command(ctx, self.aliases.get(cmd_name, cmd_name))

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        _, command, rest = super().resolve_command(ctx, args)
        # Report the canonical name, so help and errors do not echo an alias back.
        return (command.name if command else None), command, rest


@click.group(
    cls=AliasedGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="One mailbox tool: MCP server, terminal client, or the hub itself.",
    epilog=EPILOG,
)
@click.version_option(
    __version__,
    "--version",
    # The onboarding prompt asks an agent to run this *before* installing, to find out
    # whether the copy it has is old enough to matter — so it must answer without a
    # subcommand, and name whichever of the two commands was invoked.
    message="%(prog)s %(version)s",
)
def cli() -> None:
    """One mailbox tool: MCP server, terminal client, or the hub itself."""


# -- modes -------------------------------------------------------------------


@cli.command()
@click.option(
    "--project",
    type=click.Path(),
    default=None,
    help="the project this session is working in. Rarely needed: the server asks the "
    "client for its workspace roots, and falls back to its working directory. Use it "
    "when a client offers neither.",
)
def mcp(project: str | None) -> int:
    """Run as an MCP server over stdio (for an agent)."""
    from agent_mailbox.mcp_client import main as run_mcp

    run_mcp(Path(project).expanduser() if project else None)
    return 0


@cli.command()
@click.option("--host", default="127.0.0.1", help="bind address")
@click.option("--port", default=8090, type=int)
def console(host: str, port: int) -> int:
    """Serve the human console in a browser."""
    try:
        import uvicorn

        from agent_mailbox.console import build_console
    except ImportError as exc:  # pragma: no cover - only without server extras
        _err(f"the console needs the server dependencies: {exc}")
        return 1
    config = load_config()
    click.echo(f"console for {config.hub} on http://{host}:{port}")
    uvicorn.run(
        build_console(HubClient(config)), host=host, port=port, log_level="warning"
    )
    return 0


@cli.command()
@click.option(
    "--reset-user-table",
    is_flag=True,
    help="on this start only: delete all operator accounts and seed a new admin, "
    "printing its password. Agents' device tokens and all mail are untouched. Start "
    "once with it, take the password from the log, then remove it.",
)
def serve(reset_user_table: bool) -> int:
    """Run the hub."""
    try:
        from agent_mailbox.serve import main as run_hub
    except ImportError as exc:  # pragma: no cover - only without server extras
        _err(f"the hub needs the server dependencies: {exc}")
        return 1
    run_hub(reset_user_table=reset_user_table)
    return 0


@cli.command("reset-admin")
@click.option("--username", default="admin", help="which account")
def reset_admin(username: str) -> int:
    """Put an operator account back to first-run (run on the hub).

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
        _err(f"this runs on the hub and needs its dependencies: {exc}")
        return 1

    config = Settings.from_env()
    if not config.secret_key:
        _err(
            "AGENT_MAILBOX_SECRET_KEY is unset. Set the same key the hub runs with, "
            "or the reset writes an account the hub cannot read."
        )
        return 1

    async def go() -> str:
        store = SqliteAuthStore(config.db)
        async with store:
            return await AuthService(store, secret_key=config.secret_key).reset_user(
                username
            )

    try:
        password = anyio.run(go)
    except Exception as exc:  # noqa: BLE001 - the message is the whole output
        _err(f"could not reset {username!r}: {exc}")
        return 1
    click.echo(f"{username} password: {password}")
    click.echo("Sign in with it, leaving the 6-digit code blank, and enrol 2FA again.")
    return 0


# -- configuration -----------------------------------------------------------


@cli.command()
@click.argument("name", required=False)
@click.option("--hub", help="hub url; taken from the config file if present")
@click.option("--role", default="agent", help="what this engine does here")
@click.option("--engine", help="override engine detection")
@click.option("--force", is_flag=True, help="replace an existing entry")
@click.option(
    "--token",
    help="a device token minted for this agent; saved to its entry. Not needed when a "
    "shared token is in the machine-wide config.",
)
def join(
    name: str | None,
    hub: str | None,
    role: str,
    engine: str | None,
    force: bool,
    token: str | None,
) -> int:
    """Claim a name and configure this engine. Omit NAME to be issued one."""
    engine = engine or detect_engine()
    if engine is None:
        _err(
            "cannot tell which engine this is — pass --engine, so that two agents in "
            "this directory do not end up sharing one identity."
        )
        return 1

    hub_url = hub or load_hub()
    if not hub_url:
        _err(f"no hub known. Pass --hub, or put one in {CONFIG_NAME}.")
        return 1

    # Joining an enforcing hub needs a credential *before* there is a project config to
    # hold one, so the shared machine-wide token counts here too. Explicit beats
    # environment beats machine-wide; whichever it is, it authenticates this call.
    given = (token or "").strip() or os.environ.get("AGENT_MAILBOX_TOKEN", "").strip()
    shared = str(load_global().get("token", "")).strip()
    client = HubClient(
        Config(hub=hub_url, name=name or UNNAMED, role=role, token=given or shared)
    )
    # Claim first, record second: a config asserting a refused name would be a file
    # claiming an identity that is not ours.
    claimed = client.join(name)
    granted = claimed.get("preferredUsername", name)
    # Only a token given *to this agent* is written into the project. Copying the shared
    # one in would defeat the point of having it in one place — and would scatter a
    # machine-wide secret through every repository it ever joins.
    path = write_config(
        hub_url, granted, engine=engine, role=role, force=force, token=given or None
    )
    _print({"name": granted, "role": role, "engine": engine, "config": str(path)})
    return 0


@cli.group(
    cls=AliasedGroup,
    invoke_without_command=False,
    help="Read and write configuration — use this rather than editing files by hand.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    help="act on the machine-wide file rather than this project's",
)
@click.pass_context
def config(ctx: click.Context, is_global: bool) -> None:
    """Read and write configuration, so nobody has to know where the files live.

    The tool owns its configuration, and hand-editing is how that gets broken. Opening
    `~/.config/agent-inbox/config.toml` in an editor asks someone to know a path, a
    format, which of two files a given setting belongs in, which engine's entry is
    theirs, and what permissions a file holding a token needs. This knows all five.

    `--global` is accepted here or on the verb, because both read naturally and
    refusing one of them would be a parser's convenience, not a user's.
    """
    ctx.ensure_object(dict)["global"] = is_global


def _scope_option(fn: Any) -> Any:
    return click.option(
        "--global",
        "is_global",
        is_flag=True,
        help="the machine-wide file (where a shared token belongs) instead of this "
        "project's",
    )(click.pass_context(fn))


def _machine_wide(ctx: click.Context, is_global: bool) -> bool:
    """True if either the group or the verb was given ``--global``."""
    return is_global or bool((ctx.obj or {}).get("global"))


@config.command("set")
@_scope_option
@click.argument("pairs", nargs=-1, required=True, metavar="NAME VALUE [NAME VALUE ...]")
def config_set(ctx: click.Context, is_global: bool, pairs: tuple[str, ...]) -> int:
    """Set one or more settings: `config set name jed_smith`.

    `NAME=VALUE` is accepted too, because that is what anyone who has used a config
    tool reaches for. Known settings: hub, name, role, token.
    """
    is_global = _machine_wide(ctx, is_global)
    words = list(pairs)
    settings: dict[str, str] = {}
    if any("=" in word for word in words):
        for word in words:
            key, sep, value = word.partition("=")
            if not sep or not key.strip():
                _err(f"expected NAME=VALUE, got {word!r}. Do not mix the two forms.")
                return 2
            settings[key.strip()] = value.strip()
    elif len(words) % 2:
        _err(f"expected NAME and VALUE in pairs, got {len(words)}: {' '.join(words)!r}")
        return 2
    else:
        settings = dict(zip(words[::2], words[1::2], strict=True))

    if unknown := set(settings) - set(KNOWN_SETTINGS):
        _err(
            f"unknown setting(s): {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(KNOWN_SETTINGS)}."
        )
        return 2
    if is_global and (settings.keys() & set(PROJECT_ONLY)):
        _err(
            f"{' and '.join(PROJECT_ONLY)} are per project, not machine-wide — drop "
            "--global, or run `join` to claim a name."
        )
        return 2

    # A name is not ours to simply write down. It has to be claimed on the hub, or the
    # file would assert an identity we do not hold — and the first message sent under it
    # would be refused, or worse, land in somebody else's inbox.
    if name := settings.get("name"):
        hub = load_hub()
        if not hub:
            _err(
                "no hub known, so a name cannot be claimed. Set one first:\n"
                "  agent-inbox config set hub http://<host>:8081"
            )
            return 2
        token = str(load_global().get("token", "")).strip()
        try:
            claimer = HubClient(Config(hub=hub, name=UNNAMED, token=token or None))
            granted = claimer.join(name)
        except ClientError as exc:
            _err(f"could not claim {name!r}: {exc}")
            return 1
        settings["name"] = str(granted.get("preferredUsername", name))

    path = write_global(settings) if is_global else write_project(settings)
    shown = {k: ("…" if k == "token" else v) for k, v in settings.items()}
    _print({"wrote": str(path), "set": shown})
    return 0


@config.command("get")
@click.argument("name")
def config_get(name: str) -> int:
    """Print one setting's effective value, and where it came from."""
    found = effective_settings()
    if name not in found:
        _err(f"{name} is not set. `config list` shows what is.")
        return 1
    value, source = found[name]
    click.echo(value if name != "token" else "…")
    _err(f"# from {source}")
    return 0


@config.command("list")
@_scope_option
def config_list(ctx: click.Context, is_global: bool) -> int:
    """Show the settings in force, and which file each came from.

    A value can arrive from the environment, this project, or the machine-wide file,
    and "which one won" is the question people open the files to answer.
    """
    if _machine_wide(ctx, is_global):
        data = load_global()
        if not data:
            click.echo(f"nothing set in {global_config_path()}")
            return 0
        for key in sorted(data):
            click.echo(f"{key:8} {'…' if key == 'token' else data[key]}")
        return 0

    found = effective_settings()
    if not found:
        click.echo("nothing configured here — `join` or `config set` to start")
        return 0
    width = max(len(k) for k in found)
    for key in sorted(found):
        value, source = found[key]
        click.echo(f"{key:{width}}  {'…' if key == 'token' else value:30}  {source}")
    return 0


@config.command("unset")
@_scope_option
@click.argument("name")
def config_unset(ctx: click.Context, is_global: bool, name: str) -> int:
    """Remove a setting from this project, or from the machine-wide file."""
    is_global = _machine_wide(ctx, is_global)
    removed = unset_global(name) if is_global else unset_project(name)
    if not removed:
        _err(f"{name} was not set {'machine-wide' if is_global else 'here'}")
        return 1
    click.echo(f"unset {name}")
    return 0


@config.command("path")
@_scope_option
def config_path(ctx: click.Context, is_global: bool) -> int:
    """Print the file this scope writes to, whether or not it exists yet."""
    if _machine_wide(ctx, is_global):
        click.echo(str(global_config_path()))
    else:
        click.echo(str(find_config() or (project_root() / CONFIG_NAME)))
    return 0


@cli.command()
@click.option("--role-definition", is_flag=True, help="also fetch what the role means")
def whoami(role_definition: bool) -> int:
    """Who this engine is here."""
    config = load_config()
    out: dict[str, Any] = {
        "name": config.name,
        "role": config.role,
        "engine": config.engine,
        "hub": config.hub,
    }
    if role_definition:
        out["role_definition"] = HubClient(config).role_definition(config.role)
    _print(out)
    return 0


@cli.command()
@click.argument("name", required=False)
def role(name: str | None) -> int:
    """What a role means, according to the hub. Defaults to your own.

    Definitions live on the hub rather than in a prompt page per role. Separate pages
    drift out of step with each other and with the code; one source does not, and
    changing what a role means does not mean re-onboarding anyone.
    """
    config = load_config()
    _print(HubClient(config).role_definition(name or config.role))
    return 0


# -- diagnosis ---------------------------------------------------------------


def _token_help(hub_url: str, name: str, path: Path) -> str:
    """What to do about a missing device token, in the order someone can act on it.

    An agent cannot fix this alone — minting a token is an operator action behind a
    human login — so the text is written to be handed straight to a human, naming the
    exact command rather than describing it.
    """
    return (
        "\nThis hub authenticates, and this engine has no device token.\n"
        "A token is issued by a human operator, so ask yours to:\n\n"
        f"  1. Sign in to the console for {hub_url}\n"
        "  2. Tokens -> Mint a shared token (it is shown once, with a copy button)\n"
        "  3. Give it to you, and run **one** of:\n\n"
        "       agent-inbox config set --global token <token>   # this whole machine\n"
        "       agent-inbox config set token <token>            # this project only\n\n"
        "Do not edit the files by hand: `config` knows where each setting belongs\n"
        f"(machine-wide, or {path}) and writes it readable only by you. A shared\n"
        "token admits the machine, so one is enough however many agents run here.\n"
        "Nothing else needs it — it is sent automatically once it is set."
    )


@cli.command()
@click.option(
    "--hub", help="hub url to test; taken from the config or the environment if set"
)
def doctor(hub: str | None) -> int:
    """Check config, connectivity, credentials and the API, in that order.

    Fix what it reports with `config set`, never by editing files.

    Several things can be wrong and they look alike from inside an agent: no config, an
    unreachable hub, a hub that answers but rejects us, and a hub that works but has not
    been told who we are. `ping` proves only the last of them. This walks the chain in
    order and stops at the first break, because a later check would only produce a
    second, more confusing error about the same cause.
    """
    ok, bad, todo = "ok  ", "FAIL", "--  "
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

    hub_url = hub or (config.hub if config else "") or load_hub()
    if not hub_url:
        _err(f"{bad} configuration   no hub url")
        _err(
            "     Nothing here knows where the mailbox is. Run:\n"
            "       agent-inbox join --hub http://<host>:8081\n"
            f"     and it will write {where} for you."
        )
        return 2

    if config is None:
        click.echo(f"{todo} configuration   no entry for this engine yet ({where})")
        click.echo(f"{todo} identity        none yet — ask the hub for one below")
    else:
        click.echo(f"{ok} configuration   {where}")
        click.echo(
            f"{ok} identity        {config.name} "
            f"({config.role}, engine {config.engine})"
        )

    # Two engines sharing a name share an *inbox*, and the symptom is mail that quietly
    # vanishes — whichever reads first consumes it. The hub cannot see the mistake,
    # since both sides present the same name and are indistinguishable to it, so this
    # file is the only place it can be caught. Reported here, but the walk continues:
    # the engine running now may be working perfectly while another is having its mail
    # eaten.
    clashes = duplicate_names()
    for clashing, engines in sorted(clashes.items()):
        _err(f"{bad} unique names    {', '.join(engines)} all claim {clashing!r}")
    if clashes:
        _err(
            "     They share one inbox: mail for any of them is taken by whichever\n"
            "     reads first, and is then gone. Give each engine its own name — from\n"
            "     the one that should change, run:\n\n"
            "       agent-inbox config set name <a_new_name>\n\n"
            "     or omit the name and let the hub issue one. It is claimed before it\n"
            f"     is written, so it is really that engine's. File: {where}"
        )
    else:
        click.echo(f"{ok} unique names    one name per engine")

    # Without an identity there is still a hub to talk to, and reaching it is the
    # question that matters. A shared token still has to ride along: `load_config`
    # may have found one before raising because the *name* was missing, and dropping
    # it here turns "not joined yet" into a false credential failure.
    token = ""
    if config is not None:
        token = config.token or ""
    if not token:
        token = os.environ.get("AGENT_MAILBOX_TOKEN", "").strip()
    if not token:
        token = str(load_global().get("token", "")).strip()
    diagnostic = config or Config(hub=hub_url, name=UNNAMED, token=token or None)
    client = HubClient(diagnostic)

    # 2. Reachability, the network alone — no identity, no credential. A failure here is
    #    a wrong url or a hub that is down, and saying which later checks were never
    #    reached saves someone chasing a credential problem that does not exist.
    try:
        info = client.hub_info()
    except ClientError as exc:
        _err(f"{bad} connectivity    {exc}")
        _err(f"     the hub url is {hub_url}")
        return 1
    click.echo(
        f"{ok} connectivity    {hub_url} — {info.get('name')} {info.get('version')}"
    )

    # 3. The hub's own verdict on us, credential included. Only the hub knows whether
    #    the token we sent was accepted, refused or revoked, and whether it has ever
    #    heard of this name — a client that guessed at those is the thing being
    #    debugged. That route answers rather than refusing, so it works when nothing
    #    else does; an older hub has no such route, which is not a fault of ours.
    remote: dict[str, Any] = {}
    try:
        remote = client.remote_doctor() or {}
    except ClientError as exc:
        click.echo(f"{todo} hub check       not available ({exc})")

    you = remote.get("you") or {}
    token_state = str(you.get("token", ""))
    authenticated = info.get("authenticated") is True
    has_token = bool(diagnostic.token)

    if token_state in ("rejected", "revoked") or (authenticated and not has_token):
        # Reported before the API call rather than after: that call is about to fail,
        # and this is the reason, stated as something a person can act on.
        _err(
            f"{bad} credentials     "
            + (f"token {token_state}" if token_state else "no device token")
        )
        if verdict := remote.get("verdict"):
            _err(f"     the hub says: {verdict}")
        _err(_token_help(hub_url, config.name if config else "<your name>", where))
        return 1

    # Say *where* the token came from. A shared token in the machine-wide file is
    # invisible from inside the project, so "token present" alone leaves someone hunting
    # through a config that does not contain it.
    source = ""
    if has_token:
        if os.environ.get("AGENT_MAILBOX_TOKEN", "").strip():
            source = " (from AGENT_MAILBOX_TOKEN)"
        elif diagnostic.token == str(load_global().get("token", "")).strip():
            source = f" (shared, from {global_config_path()})"
        else:
            source = f" (from {where})"
    click.echo(
        f"{ok} credentials     "
        + (
            f"device token accepted by the hub{source}"
            if token_state == "accepted"
            else f"device token present{source}"
            if has_token
            else "none needed — this hub does not authenticate"
        )
    )
    if verdict := remote.get("verdict"):
        click.echo(f"{ok} hub check       {verdict}")

    # Reachable, and nothing is in the way — but we are nobody here yet. This is the end
    # of the road for an unjoined engine, and it is a *good* outcome: it says the next
    # step will work.
    if config is None:
        click.echo(f"{todo} api             not joined yet")
        click.echo(
            "\nThe hub is reachable and ready. Ask it for a name:\n\n"
            f"    agent-inbox join --hub {hub_url}\n\n"
            "The hub issues the name and settles uniqueness itself, so there is\n"
            "nothing to check first and nothing to retry. Add a name of your own\n"
            "only if you want one — you will be told if it is taken. Either way\n"
            f"{where} is written for you; there is no second step."
        )
        return 2

    # 4. The API, as us. Everything above can be right while a real call still
    #    fails, and only a real call finds that out.
    try:
        client.ping()
    except ClientError as exc:
        _err(f"{bad} api             {exc}")
        if "auth" in str(exc).lower() or "token" in str(exc).lower():
            _err(_token_help(hub_url, config.name, where))
        return 1
    waiting = len(client.check_inbox().get("items", []))
    click.echo(f"{ok} api             ping answered; {waiting} message(s) waiting")

    # A local fault the network checks cannot see, so it decides the exit code even when
    # everything else answered.
    if clashes:
        return 1

    if not authenticated:
        click.echo(
            "\nNote: this hub does not authenticate. Anyone who can reach it can "
            "claim to be anyone.\nThat is fine on a trusted network and not fine on "
            "the open internet."
        )
    return 0


# -- mailbox -----------------------------------------------------------------


@cli.command()
def ping() -> int:
    """Prove the connection."""
    _print(_client().ping())
    return 0


@cli.command()
def inbox() -> int:
    """What is waiting."""
    items = _client().check_inbox().get("items", [])
    if not items:
        click.echo("nothing waiting")
        return 0
    for note in items:
        sender = (note.get("attributedTo") or "").rsplit("/", 1)[-1]
        ident = (note.get("id") or "").rsplit("/", 1)[-1]
        click.echo(f"{ident}  {sender:20} {note.get('summary') or '(no subject)'}")
    return 0


@cli.command()
@click.argument("to")
@click.argument("body")
@click.option("-s", "--subject")
def send(to: str, body: str, subject: str | None) -> int:
    """Send a message."""
    sent = _client().send_message(to, body, subject)
    _print({"sent": sent.get("id"), "to": sent.get("to")})
    return 0


@cli.command()
@click.argument("id")
def read(id: str) -> int:  # noqa: A002 - the argument is named for the user, not us
    """Read and consume a message."""
    note = _client().read_message(id)
    click.echo(f"from    : {(note.get('attributedTo') or '').rsplit('/', 1)[-1]}")
    click.echo(f"subject : {note.get('summary') or '(none)'}")
    click.echo()
    click.echo(note.get("content", ""))
    return 0


@cli.command()
@click.argument("id")
@click.argument("body")
@click.option("-s", "--subject")
def reply(id: str, body: str, subject: str | None) -> int:  # noqa: A002
    """Reply to a message."""
    _print(_client().reply_message(id, body, subject))
    return 0


@cli.command()
def agents() -> int:
    """Who is on the hub."""
    for actor in _client().list_agents().get("items", []):
        name = actor.get("preferredUsername", "?")
        role_name = (actor.get("profile") or {}).get("role", "")
        about = (actor.get("summary") or "").split(".")[0]
        click.echo(f"{name:24} {role_name:10} {about[:60]}")
    return 0


@cli.command()
def hub() -> int:
    """What this hub is."""
    _print(_client().hub_info())
    return 0


# -- the wake hook -----------------------------------------------------------


@cli.command("wake-check")
@click.option(
    "--event",
    default="SessionStart",
    help="the hook event: SessionStart, UserPromptSubmit, or Stop",
)
def wake_check(event: str) -> int:
    """Session hook: notice new mail (fail-silent)."""
    from agent_mailbox.wake import run

    return run(event)


@cli.command("install-hook")
@click.option("--dir", "directory", help="project dir (default: this repo root)")
@click.option(
    "--rewake",
    is_flag=True,
    help="also wake a fully idle session (async; needs a live-session check)",
)
def install_hook(directory: str | None, rewake: bool) -> int:
    """Add the wake hooks to .claude/settings.json."""
    from agent_mailbox import hookconfig

    root = Path(directory) if directory else project_root()
    path = hookconfig.install(root, rewake=rewake)
    extra = " (with async rewake)" if rewake else ""
    click.echo(f"wake hooks installed in {path}{extra}")
    click.echo("Restart your session so it picks up the hooks.")
    return 0


@cli.command("uninstall-hook")
@click.option("--dir", "directory", help="project dir (default: this repo root)")
def uninstall_hook(directory: str | None) -> int:
    """Remove the wake hooks from .claude/settings.json."""
    from agent_mailbox import hookconfig

    root = Path(directory) if directory else project_root()
    click.echo(f"wake hooks removed from {hookconfig.uninstall(root)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for both console scripts, returning an exit code.

    `standalone_mode=False` so a command's return value reaches us instead of click
    exiting on our behalf — the container and the tests both want the code, not a raised
    SystemExit. In that mode click also *returns* the code for `--help` and `--version`
    rather than raising, which is why there is no branch for them here; the console
    script turns whatever comes back into the process's exit status.
    """
    try:
        return int(cli.main(args=argv, standalone_mode=False) or 0)
    except click.ClickException as exc:  # usage errors, unknown commands
        exc.show()
        return exc.exit_code
    except click.Abort:  # pragma: no cover - interrupted at a prompt
        _err("aborted")
        return 1
    except NotConfigured as exc:
        _err(str(exc))
        return 2
    except ClientError as exc:
        _err(str(exc))
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
