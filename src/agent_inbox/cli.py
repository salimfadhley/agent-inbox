"""One tool, several modes.

``agent-inbox`` is the command (``agent-mailbox`` is the same program under its older
name). It runs as an MCP server for an agent, as a terminal client for a human, or as
the hub itself — and in every mode it is the thing that **owns the local
configuration**.

That ownership is the point. Nobody hand-writes ``agent-inbox.toml``: the first time
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

import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

import click

from agent_inbox import __version__, staleness
from agent_inbox.client import (
    CONFIG_NAME,
    UNNAMED,
    ClientError,
    Config,
    HubClient,
    NotConfigured,
    configured_engines,
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
from agent_inbox.deployment import verify_all

#: Settings `config` will write. Anything else is a typo, and a typo silently accepted
#: leaves a file that reads correct and is not.
KNOWN_SETTINGS = ("hub", "name", "role", "token")

#: Per project, never machine-wide: the same engine in two repositories is two
#: correspondents, and one machine-wide name would quietly merge them into one inbox.
PROJECT_ONLY = ("name", "role")

EPILOG = """\
WHERE YOU RUN IT MATTERS. Identity is per project, so anything acting as an agent —
join, config, doctor, ping, inbox, send, read, reply, agents, whoami, role, hub — reads
agent-inbox.toml from the directory you are in, searching upwards and stopping at the
repository root. Run those inside the project. A shared token may live machine-wide
(`config set --global token <token>`), because a credential admits the machine rather
than naming an agent.

`mcp` needs no particular directory: it asks the client that launched it for the
workspace, falls back to this one, and takes which engine it serves from the client's
own name. `--project` settles it for a client that offers neither.

`serve` and `console` are the hub and its window: configured by the environment
(AGENT_MAILBOX_*), not by a project, and they run anywhere.
"""


class EngineUnresolved(click.ClickException):
    """No engine could be resolved, and guessing would write to the wrong agent.

    Raised *before* anything is contacted or written. The message names the engines the
    project actually has and the exact command to rerun, because "I cannot tell which
    engine you are" sends the reader to a file, and a list plus a retry line does not.
    """

    exit_code = 2

    def __init__(self, engines: list[str], command: str) -> None:
        super().__init__(
            "cannot tell which engine to use for this project.\n"
            f"Configured engines: {', '.join(sorted(engines))}.\n"
            "Rerun with:\n"
            f"  agent-inbox --engine {sorted(engines)[0]} {command}"
        )


def _engine(ctx: click.Context) -> str | None:
    """The engine the caller named, if any. Explicit beats detection everywhere."""
    return (ctx.find_root().obj or {}).get("engine")


def _command_path(ctx: click.Context) -> str:
    """How the caller spelled this command, for a retry line they can paste.

    `ctx.info_name` alone is the leaf, so a nested command comes out as `set` and the
    suggestion does not run. Walking up to (but not including) the root gives back
    `config set`.
    """
    parts: list[str] = []
    node: click.Context | None = ctx
    while node is not None and node.parent is not None:
        if node.info_name:
            parts.append(node.info_name)
        node = node.parent
    return " ".join(reversed(parts))


class EngineNotConfigured(click.ClickException):
    """Named an engine this project has no entry for.

    Distinct from EngineUnresolved on purpose: there the caller said nothing and must
    choose, here they chose and the choice does not exist. Falling through to the
    generic "write agent-inbox.toml in your project root" told people to create a
    file that was open in front of them.
    """

    exit_code = 2

    def __init__(self, engine: str, engines: list[str]) -> None:
        have = ", ".join(sorted(engines)) if engines else "none"
        super().__init__(
            f"this project has no entry for engine {engine!r}.\n"
            f"Configured engines: {have}.\n"
            "Either use one of those, or create this one:\n"
            f"  agent-inbox join --engine {engine}"
        )


def _resolve_engine(ctx: click.Context, *, must_exist: bool = False) -> str | None:
    """Which engine this command should act as, or refuse.

    An agent session carries a marker and never notices this. A human shell does not,
    and in a project configuring several agents there is no honest default: picking one
    writes to someone else's identity, and a synthetic `default` entry belongs to
    nobody. So the third option — refuse and say how — is the only one that keeps the
    invariant that every project identity belongs to a real engine.

    One entry and no marker is still allowed (FR-009): there is nothing to get wrong.
    The caller reports which engine that was, so the day a second agent joins and the
    same command starts refusing, the reason is already familiar.
    """
    engines = configured_engines()
    if named := _engine(ctx):
        # `must_exist` separates acting from creating. `join` and `config set` may
        # legitimately name an engine that has no entry yet — that is how one is made.
        if must_exist and engines and named not in engines:
            raise EngineNotConfigured(named, engines)
        return named
    if detected := detect_engine():
        return detected
    if len(engines) > 1:
        raise EngineUnresolved(engines, _command_path(ctx) or "<command>")
    return engines[0] if engines else None


def _client(ctx: click.Context) -> HubClient:
    """A hub client acting as this project's agent — engine resolved or refused."""
    return HubClient(load_config(engine=_resolve_engine(ctx, must_exist=True)))


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
@click.option(
    "--engine",
    "engine",
    metavar="ENGINE",
    help="which engine's entry in agent-inbox.toml to act as (claude, codex, …). "
    "An agent session is detected automatically; a human shell in a project with more "
    "than one agent must say.",
)
@click.version_option(
    __version__,
    "--version",
    # The onboarding prompt asks an agent to run this *before* installing, to find out
    # whether the copy it has is old enough to matter — so it must answer without a
    # subcommand, and name whichever of the two commands was invoked.
    message="%(prog)s %(version)s",
)
@click.pass_context
def cli(ctx: click.Context, engine: str | None) -> None:
    """One mailbox tool: MCP server, terminal client, or the hub itself."""
    ctx.ensure_object(dict)["engine"] = engine


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
    from agent_inbox.mcp_client import main as run_mcp

    run_mcp(Path(project).expanduser() if project else None)
    return 0


@cli.command()
@click.option("--host", default="127.0.0.1", help="bind address")
@click.option("--port", default=8090, type=int)
def console(host: str, port: int) -> int:
    """Serve the human console in a browser."""
    try:
        import uvicorn

        from agent_inbox.console import build_console
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
    "printing its password. Agents' tokens and all mail are untouched. Start "
    "once with it, take the password from the log, then remove it.",
)
def serve(reset_user_table: bool) -> int:
    """Run the hub."""
    try:
        from agent_inbox.serve import main as run_hub
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

        from agent_inbox.auth.service import AuthService
        from agent_inbox.auth.store import SqliteAuthStore
        from agent_inbox.serve import Settings
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
    help="a token minted by an operator; saved to this project. Not needed when a "
    "shared token is in the machine-wide config.",
)
@click.pass_context
def join(
    ctx: click.Context,
    name: str | None,
    hub: str | None,
    role: str,
    engine: str | None,
    force: bool,
    token: str | None,
) -> int:
    """Claim a name and configure this engine. Omit NAME to be issued one."""
    # `--engine` on the command still works and wins; otherwise the root option, then
    # detection, then a refusal that names the project's engines.
    engine = engine or _resolve_engine(ctx)
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

    if is_global:
        path = write_global(settings)
    else:
        # A project write lands in one engine's entry. Getting that wrong writes into
        # another agent's identity, which is why this refuses rather than defaults.
        path = write_project(settings, engine=_resolve_engine(ctx))
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
    removed = (
        unset_global(name)
        if is_global
        else unset_project(name, engine=_resolve_engine(ctx))
    )
    if not removed:
        _err(f"{name} was not set {'machine-wide' if is_global else 'here'}")
        return 1
    click.echo(f"unset {name}")
    return 0


# -- profile -----------------------------------------------------------------


def _parse_profile(raw: str) -> dict[str, Any]:
    """A profile from JSON text, or a refusal a caller can act on.

    Two refusals rather than one, because they need different fixes: text that is not
    JSON at all, and JSON that is not an object. A list parses perfectly well and is
    still not a profile.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"that is not valid JSON: {exc}. A profile looks like "
            '\'{"project": "billing", "engine": "claude-opus"}\''
        ) from exc
    if not isinstance(parsed, dict):
        raise click.ClickException(
            f"a profile must be a JSON object, not {type(parsed).__name__}. "
            'It maps names to values: \'{"project": "billing"}\''
        )
    return parsed


@cli.group(cls=AliasedGroup, invoke_without_command=False)
def profile() -> None:
    """Say who you are here — what you work on, what you can help with.

    The hub asks every agent for this at onboarding. It is how another agent deciding
    whether to write to you can tell what you are for, and it is what the roster and the
    console overview are built from.

    Free-form on purpose: your *name* is opaque and permanent, so everything descriptive
    lives here instead, where it can change without your identity changing.
    """


@profile.command("show")
@click.pass_context
def profile_show(ctx: click.Context) -> int:
    """Print your current profile, as the JSON `profile set` accepts.

    Worth running before you set anything: setting **replaces**, so this is how you see
    what you are about to overwrite — and its output can go straight back in.
    """
    client = _client(ctx)
    _print(client.whois(client.config.name).get("profile") or {})
    return 0


@profile.command("set")
@click.argument("json_text", metavar="JSON")
@click.pass_context
def profile_set(ctx: click.Context, json_text: str) -> int:
    """Set your profile from a JSON object — this **replaces** the whole thing.

    Not a merge: send the fields you want to keep, or they are gone. That is what the
    hub does, and what the MCP tool does, so all three surfaces agree. `profile show`
    prints what you have now, in the form this accepts.

        agent-inbox profile set '{"project": "billing", "engine": "claude-opus"}'
    """
    _print(_client(ctx).update_profile(_parse_profile(json_text)))
    return 0


@cli.command("update-profile", hidden=True)
@click.argument("json_text", metavar="JSON")
@click.pass_context
def update_profile(ctx: click.Context, json_text: str) -> int:
    """Deprecated spelling of `profile set`, kept because the MCP tool is called this.

    An agent reading `update_profile` in MCP-oriented text and trying it at a shell
    should find the command, not a dead end that teaches it the step does not exist.
    Hidden from `--help` so the canonical form is the one people learn.
    """
    return int(ctx.invoke(profile_set, json_text=json_text))


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
@click.pass_context
def whoami(ctx: click.Context, role_definition: bool) -> int:
    """Who this engine is here."""
    config = load_config(engine=_resolve_engine(ctx, must_exist=True))
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
@click.pass_context
def role(ctx: click.Context, name: str | None) -> int:
    """What a role means, according to the hub. Defaults to your own.

    Definitions live on the hub rather than in a prompt page per role. Separate pages
    drift out of step with each other and with the code; one source does not, and
    changing what a role means does not mean re-onboarding anyone.
    """
    config = load_config(engine=_resolve_engine(ctx, must_exist=True))
    _print(HubClient(config).role_definition(name or config.role))
    return 0


# -- diagnosis ---------------------------------------------------------------


def _token_help(hub_url: str, name: str, path: Path) -> str:
    """What to do about a missing token, in the order someone can act on it.

    An agent cannot fix this alone — minting a token is an operator action behind a
    human login — so the text is written to be handed straight to a human, naming the
    exact command rather than describing it.
    """
    return (
        "\nThis hub authenticates, and this machine has no token.\n"
        "A token is issued by a human operator, so ask yours to:\n\n"
        f"  1. Sign in to the console for {hub_url}\n"
        "  2. Tokens -> Mint (it is shown once, with a copy button)\n"
        "  3. Give you the setup prompt shown beside it — that has the token in it\n"
        "     already. Failing that, the token alone, and run:\n\n"
        "       agent-inbox config set --global token <token>\n\n"
        "Do not edit the files by hand: `config` knows where each setting belongs\n"
        f"(machine-wide, or {path}) and writes it readable only by you. A shared\n"
        "token admits the machine, so one is enough however many agents run here.\n"
        "Nothing else needs it — it is sent automatically once it is set."
    )


@cli.command("verify-deployment")
@click.option(
    "--hub",
    "hubs",
    multiple=True,
    required=True,
    help="a hub url to prove; repeat for each target",
)
@click.option(
    "--prompt",
    "prompts",
    multiple=True,
    help=(
        "where each hub's onboarding prompt is served, in the same order as --hub. "
        "Usually the console. Omit to skip the prompt/descriptor agreement check."
    ),
)
@click.option("--expect", default="", help="the version that was supposed to land")
def verify_deployment(
    hubs: tuple[str, ...], prompts: tuple[str, ...], expect: str
) -> int:
    """Prove a deployment took, and **fail** if it did not.

    A deploy is not successful until the running service proves it. Deploy tooling
    reports on the request it made, not on what is running afterwards — twice now that
    has reported success over a hub running a five-release-old version, and over a hub
    that was not running at all.

    This knows nothing about how anything is deployed. Point it at what should be
    serving, say what should be there, and it exits non-zero if the two disagree.

    \b
    Example:
      agent-inbox verify-deployment \\
        --hub https://hub.example --prompt https://console.example/prompts/agent \\
        --expect 1.2.3
    """
    targets = [
        (hub, prompts[i] if i < len(prompts) else "") for i, hub in enumerate(hubs)
    ]
    reports, ok = verify_all(targets, expect)
    for report in reports:
        click.echo(report.target)
        for check in report.checks:
            click.echo(str(check))
    if ok:
        click.echo(f"\nall {len(reports)} target(s) proved themselves")
        return 0
    failed = [r.target for r in reports if not r.ok]
    _err(f"{len(failed)} of {len(reports)} target(s) did not: " + ", ".join(failed))
    return 1


@cli.command()
@click.option(
    "--hub", help="hub url to test; taken from the config or the environment if set"
)
@click.pass_context
def doctor(ctx: click.Context, hub: str | None) -> int:
    """Check config, connectivity, credentials and the API, in that order.

    Several things can be wrong and they look alike from inside an agent: no config, an
    unreachable hub, a hub that answers but rejects us, and a hub that works but has not
    been told who we are. `ping` proves only the last of them. This walks the chain in
    order and stops at the first break, because a later check would only produce a
    second, more confusing error about the same cause.

    Each line is marked:

    \b
      ok     this is fine
      --     worth knowing, but not a fault — a step you have not taken yet
      FAIL   broken; the text says what to do about it

    Fix what it reports with `config set`, never by editing files.

    EXIT CODE: 0 when nothing FAILed — including a brand new agent that has not joined,
    which is the ordinary first-run state and not an error. Non-zero when something did.
    A hub that rejects your credentials exits 1 and the other blockers exit 2, but that
    distinction is historical and carries no defined meaning: treat any non-zero as
    "something on this list is broken" and read the FAIL line to find out which.
    """
    ok, bad, todo, warn = "ok  ", "FAIL", "--  ", "note"
    where = find_config() or (project_root() / CONFIG_NAME)

    # 1. Configuration. Having none is the *normal* state before `join`, not an error:
    #    doctor is meant to be run first, to find out whether joining is even worth
    #    attempting. So a missing identity does not stop the connectivity check — that
    #    is the one an agent most needs answered before it asks for a name.
    # Never refuses for want of an engine: diagnosing is exactly what a caller does
    # *before* they know what to select, so an unresolved engine is a finding to report
    # rather than a reason to stop. That is why this does not call `_resolve_engine`.
    engines = configured_engines()
    chosen = _engine(ctx) or detect_engine()
    if chosen is None and len(engines) == 1:
        chosen = engines[0]  # nothing to get wrong (FR-009)

    config: Config | None = None
    try:
        config = load_config(engine=chosen)
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

    # An unresolved engine and an unconfigured project look identical from a distance
    # and need opposite actions — one is "tell me who you are", the other "join". Say
    # which, and name the engines, so the next command is obvious.
    ambiguous = chosen is None and len(engines) > 1
    if ambiguous:
        click.echo(f"{ok} configuration   {where}")
        click.echo(
            f"{todo} identity        no engine selected — this project has "
            f"{', '.join(sorted(engines))}"
        )
    elif config is None:
        click.echo(f"{todo} configuration   no entry for this engine yet ({where})")
        click.echo(f"{todo} identity        none yet — ask the hub for one below")
    else:
        # Say which engine was chosen and why. When a second agent joins and this
        # command starts refusing, the reader has already seen the mechanism.
        how = (
            "named"
            if _engine(ctx)
            else ("detected" if detect_engine() else "the only one configured")
        )
        click.echo(f"{ok} configuration   {where}")
        click.echo(
            f"{ok} identity        {config.name} "
            f"({config.role}, engine {config.engine or chosen} — {how})"
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
    # NFR-002: with no engine we still reach the hub and its remote doctor, carrying
    # whatever shared credential exists. A machine token authenticates the machine; it
    # does not need an identity to be checked.
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

    # We are holding both versions at this point and used to discard the comparison.
    # An agent whose client is behind sees new commands as "No such command", which is
    # true and reads as "the feature does not exist" — reported from live use with a
    # client six releases old. `doctor` is what somebody runs when they already suspect
    # something is wrong, so it is the right place to say the most likely cause.
    #
    # A note, never a failure (FR-003): an older client mostly works, and exiting
    # non-zero would make a working setup look broken. Nothing is printed when the two
    # match (FR-007) — a line on every healthy run is a line nobody reads.
    staleness.note_hub_version(info.get("version"))
    match staleness.standing(info.get("version")):
        case "behind":
            click.echo(f"{warn} version         {staleness.notice()}")
        case "ahead":
            # The other direction, and a different problem with a different owner: the
            # hub is old, not this client, and upgrading here would fix nothing.
            click.echo(
                f"{warn} version         this client is {__version__} and the hub runs "
                f"{info.get('version')} — the hub is behind, not you. Nothing to do "
                f"here; whoever operates it may want to know."
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
            + (f"token {token_state}" if token_state else "no token")
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
            f"token accepted by the hub{source}"
            if token_state == "accepted"
            else f"token present{source}"
            if has_token
            else "none needed — this hub does not authenticate"
        )
    )
    if verdict := remote.get("verdict"):
        click.echo(f"{ok} hub check       {verdict}")

    # FR-007: an unresolved engine is not a missing credential. Inviting someone to
    # mint a token when the blocking issue is "which of your two agents am I" sends
    # them to an operator for a problem they can fix themselves in one flag.
    if ambiguous:
        click.echo(f"{todo} api             no engine selected")
        click.echo(
            "\nThe hub is reachable and your credentials are in order. Say which "
            "agent to act as:\n\n"
            f"    agent-inbox --engine {sorted(engines)[0]} doctor\n\n"
            f"This project configures {', '.join(sorted(engines))}. Identity is per "
            "engine, so there is no safe default — picking one for you would act as, "
            "and could write to, the wrong agent."
        )
        return 2

    # Reachable, and nothing is in the way — but we are nobody here yet. This is the end
    # of the road for an unjoined engine, and it is a *good* outcome: it says the next
    # step will work.
    if config is None:
        click.echo(f"{todo} api             not joined yet")
        # With no engine resolved, a bare `join` would refuse for the same reason
        # everything else does — so suggest the form that works rather than the one
        # that sends them back here.
        flag = "" if chosen else " --engine <engine>"
        click.echo(
            "\nThe hub is reachable and ready. Ask it for a name:\n\n"
            f"    agent-inbox join{flag} --hub {hub_url}\n\n"
            "The hub issues the name and settles uniqueness itself, so there is\n"
            "nothing to check first and nothing to retry. Add a name of your own\n"
            "only if you want one — you will be told if it is taken. Either way\n"
            f"{where} is written for you; there is no second step."
        )
        # Amber, not red. Nothing failed: every check that ran passed, and the only
        # outstanding thing is a step the caller has not taken yet. This used to return
        # 2, directly beneath the comment above calling it a good outcome — so the
        # command printed nothing but `ok` and `--` and then reported failure, and any
        # script reading the code could not tell a new agent from an unreachable hub.
        #
        # `clashes` still decides, because that check reports and keeps walking rather
        # than returning: a duplicate name is a real fault that has nothing to do with
        # whether *this* engine has joined, and widening success must not swallow it.
        return 1 if clashes else 0

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
@click.pass_context
def ping(ctx: click.Context) -> int:
    """Prove the connection."""
    _print(_client(ctx).ping())
    return 0


@cli.command()
@click.option("--full", is_flag=True, help="Include message bodies (expensive).")
@click.option(
    "--count", is_flag=True, help="Print the number waiting and nothing else."
)
@click.option("--threads", is_flag=True, help="Group waiting mail by conversation.")
@click.option(
    "--since",
    metavar="CURSOR",
    help="Only mail newer than this cursor, as printed by a previous run.",
)
@click.pass_context
def inbox(
    ctx: click.Context, full: bool, count: bool, threads: bool, since: str | None
) -> int:
    """What is waiting. Consumes nothing — `read` is what marks mail handled."""
    client = _client(ctx)

    def _warn_if_old(page: dict[str, Any]) -> None:
        """Say when the hub is too old to answer properly, rather than showing zeros."""
        if not page.get("hubTooOld"):
            return
        _err(
            "note: this hub predates compact inbox views, so it sent every waiting "
            "message and the summary above was worked out here."
        )
        if page.get("sinceIgnored"):
            _err("      --since was ignored: only the hub can filter. Upgrade it.")

    if count:
        page = client.check_inbox(view="count", since=since)
        click.echo(page.get("unread", 0))
        _warn_if_old(page)
        return 0

    if threads:
        page = client.check_inbox(view="threads", since=since)
        groups = page.get("threads", [])
        if not groups:
            click.echo("nothing waiting")
            return 0
        _warn_if_old(page)
        for group in groups:
            kind = "broadcast" if group.get("broadcast") else "direct"
            click.echo(
                f"{group.get('unread'):>3} unread  {group.get('lastFrom') or '?':20}"
                f" {group.get('subject')}  ({kind}, last {group.get('lastPublished')})"
            )
        return 0

    if full:
        for note in client.check_inbox(view="full").get("items", []):
            sender = (note.get("attributedTo") or "").rsplit("/", 1)[-1]
            ident = (note.get("id") or "").rsplit("/", 1)[-1]
            click.echo(f"{ident}  {sender:20} {note.get('summary') or '(no subject)'}")
            click.echo(f"    {note.get('content') or ''}\n")
        return 0

    page = client.check_inbox(view="summary", since=since)
    items = page.get("items", [])
    if not items:
        click.echo("nothing waiting")
        return 0
    _warn_if_old(page)
    for row in items:
        ident = (row.get("id") or "").rsplit("/", 1)[-1]
        sender = (row.get("attributedTo") or "").rsplit("/", 1)[-1] or "?"
        mark = "*" if row.get("broadcast") else " "
        click.echo(
            f"{ident}  {mark}{sender:20} "
            f"{row.get('summary')}  ({row.get('chars')} chars)"
        )
    # The cursor is the caller's to keep — printed so a script can hold it and a human
    # can see there is nothing hidden about it.
    click.echo(f"\ncursor: {page.get('cursor')}   (* = broadcast)")
    return 0


@cli.command()
@click.argument("query")
@click.option("--from", "sender", metavar="NAME", help="Only mail from this sender.")
@click.option("--since", metavar="TIME", help="Only mail at or after this timestamp.")
@click.option("--until", metavar="TIME", help="Only mail at or before this timestamp.")
@click.option("-n", "--limit", type=int, default=0, help="How many results (capped).")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    sender: str | None,
    since: str | None,
    until: str | None,
    limit: int,
) -> int:
    """Find mail about a topic, including mail you have already read.

    Consumes nothing. Searches only mail you are party to — sent by you or addressed
    to you — for as long as its conversation is retained.
    """
    page = _client(ctx).search(
        query,
        sender=sender or "",
        since=since or "",
        until=until or "",
        limit=limit,
    )
    results = page.get("results", [])
    if not results:
        click.echo("nothing found")
        return 0
    for row in results:
        ident = (row.get("id") or "").rsplit("/", 1)[-1]
        who = (row.get("attributedTo") or "").rsplit("/", 1)[-1] or "?"
        click.echo(f"{ident}  {who:20} {row.get('summary')}")
        click.echo(f"    {row.get('snippet')}\n")
    if page.get("truncated"):
        # Said plainly, because a capped answer that looks complete is worse than a
        # short one: the reader stops looking for what was cut.
        click.echo("more matched than are shown — narrow with --from or --since")
    return 0


@cli.command()
@click.argument("to")
@click.argument("body")
@click.option("-s", "--subject")
@click.pass_context
def send(ctx: click.Context, to: str, body: str, subject: str | None) -> int:
    """Send a message."""
    sent = _client(ctx).send_message(to, body, subject)
    _print({"sent": sent.get("id"), "to": sent.get("to")})
    return 0


@cli.command()
@click.argument("id")
@click.pass_context
def read(ctx: click.Context, id: str) -> int:  # noqa: A002 - named for the user
    """Read and consume a message."""
    note = _client(ctx).read_message(id)
    click.echo(f"from    : {(note.get('attributedTo') or '').rsplit('/', 1)[-1]}")
    click.echo(f"subject : {note.get('summary') or '(none)'}")
    click.echo()
    click.echo(note.get("content", ""))
    return 0


@cli.command()
@click.argument("id")
@click.argument("body")
@click.option("-s", "--subject")
@click.pass_context
def reply(ctx: click.Context, id: str, body: str, subject: str | None) -> int:  # noqa: A002
    """Reply to a message."""
    _print(_client(ctx).reply_message(id, body, subject))
    return 0


@cli.command()
@click.pass_context
def agents(ctx: click.Context) -> int:
    """Who is on the hub."""
    for actor in _client(ctx).list_agents().get("items", []):
        name = actor.get("preferredUsername", "?")
        role_name = (actor.get("profile") or {}).get("role", "")
        about = (actor.get("summary") or "").split(".")[0]
        click.echo(f"{name:24} {role_name:10} {about[:60]}")
    return 0


@cli.command()
@click.pass_context
def hub(ctx: click.Context) -> int:
    """What this hub is, and whether it is looking after itself."""
    client = _client(ctx)
    _print(client.hub_info())

    # Retention liveness belongs here rather than behind its own command. It is a
    # property of the hub, and the reason it was invisible for the life of this project
    # is that nobody had a reason to go looking. Printing it beside the version means
    # nobody has to.
    try:
        status = client.purge_status()
    except ClientError:
        # An older hub has no such route, and an unauthenticated caller may not read it.
        # Neither is a fault worth interrupting `hub` for.
        return 0

    if last := status.get("lastCycle"):
        click.echo(
            f"\nretention: last checked {str(last)[:19].replace('T', ' ')} UTC "
            f"({status.get('cycles', 0)} checks, "
            f"{status.get('lastRemovedObjects', 0)} removed)"
        )
    else:
        click.echo(
            "\nretention: no check has completed yet — normal for the first few "
            "minutes after the hub starts, a fault if it persists"
        )
    if failed := status.get("lastError"):
        click.echo(f"retention: the last check FAILED — {failed}", err=True)
    return 0


@cli.command()
@click.pass_context
def retention(ctx: click.Context) -> int:
    """Whether this hub is expiring old mail. Machine-readable.

    `hub` says the same thing in a sentence, for a human glancing at it. This prints
    the object, for a monitor that wants to alert when `lastCycle` stops advancing —
    which is the failure that went unnoticed here for the life of the project.

    Needs no operator session and no delete rights: asking whether housekeeping runs is
    not the same question as asking what it is about to remove.
    """
    _print(_client(ctx).purge_status())
    return 0


# -- the wake hook -----------------------------------------------------------


@cli.command("wake-check")
@click.option(
    "--event",
    default="SessionStart",
    help="the hook event: SessionStart, UserPromptSubmit, or Stop",
)
@click.option(
    "--wait",
    is_flag=True,
    help="hold the hub's event stream until mail arrives, polling underneath; "
    "intended for asyncRewake Stop hooks",
)
@click.option(
    "--poll-interval",
    type=float,
    default=5.0,
    show_default=True,
    help="seconds between checks when --wait is active",
)
@click.option(
    "--wait-timeout",
    type=float,
    default=8 * 60 * 60.0,
    show_default=True,
    help="maximum seconds to wait when --wait is active",
)
def wake_check(
    event: str, wait: bool, poll_interval: float, wait_timeout: float
) -> int:
    """Session hook: notice new mail (fail-silent)."""
    from agent_inbox.wake import run

    return run(
        event,
        wait=wait,
        poll_interval=poll_interval,
        wait_timeout=wait_timeout,
    )


@cli.command("install-hook")
@click.option("--dir", "directory", help="project dir (default: this repo root)")
@click.option(
    "--command",
    default="agent-inbox wake-check",
    show_default=True,
    help="base hook command; override for local source-tree testing",
)
@click.option(
    "--rewake",
    is_flag=True,
    help="also wake a fully idle session (async; needs a live-session check)",
)
def install_hook(directory: str | None, command: str, rewake: bool) -> int:
    """Add the wake hooks to .claude/settings.json."""
    from agent_inbox import hookconfig

    root = Path(directory) if directory else project_root()
    path = hookconfig.install(root, command=command, rewake=rewake)
    extra = " (with async rewake)" if rewake else ""
    click.echo(f"wake hooks installed in {path}{extra}")
    click.echo("Restart your session so it picks up the hooks.")
    return 0


@cli.command("uninstall-hook")
@click.option("--dir", "directory", help="project dir (default: this repo root)")
def uninstall_hook(directory: str | None) -> int:
    """Remove the wake hooks from .claude/settings.json."""
    from agent_inbox import hookconfig

    root = Path(directory) if directory else project_root()
    click.echo(f"wake hooks removed from {hookconfig.uninstall(root)}")
    return 0


def force_utf8(stream: Any) -> None:
    """Make one output stream write UTF-8, whatever the locale thinks.

    Our text uses em-dashes and other non-ASCII punctuation. On Windows, when stdout is
    not attached to a UTF-8 console — Git Bash, or anything redirected — Python encodes
    with the locale codepage instead, so U+2014 goes out as the single byte ``0x97``
    rather than ``e2 80 94``. Every UTF-8 consumer downstream then shows mojibake.

    **It does not stay on the terminal.** This project routes command output into
    session logs, CI artifacts, and mail bodies that quote commands. A corrupted
    character outlives the terminal that produced it and is unreadable to every later
    reader, agents included — so this degrades from a display problem into a data
    problem the moment anyone redirects.

    Fixed at the stream rather than at the ~39 call sites that use the character,
    because chasing call sites fixes today's occurrences and not tomorrow's: the next
    person to type an em-dash would reintroduce it. Encoding is a property of the
    stream, so it belongs where the stream is configured.

    **Never fails the command.** Anything may be standing in for stdout — a test
    capture, a pipe wrapper, a harness — and a CLI that refuses to run because it could
    not adjust its own output encoding would be worse than one that occasionally
    prints an odd character.

    Known trade, and it is the right way round: on a console that genuinely cannot
    render UTF-8, correct bytes may display as replacement characters instead of
    mojibake. That is a legible failure rather than a silent corruption, and the
    redirected case — the one that persists — becomes correct.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    with suppress(Exception):
        reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Entry point for both console scripts, returning an exit code.

    `standalone_mode=False` so a command's return value reaches us instead of click
    exiting on our behalf — the container and the tests both want the code, not a raised
    SystemExit. In that mode click also *returns* the code for `--help` and `--version`
    rather than raising, which is why there is no branch for them here; the console
    script turns whatever comes back into the process's exit status.
    """
    # Before the first byte. Click writes through these streams, so reconfiguring after
    # it has started would leave whatever was already emitted encoded the old way.
    force_utf8(sys.stdout)
    force_utf8(sys.stderr)
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
