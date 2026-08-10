"""Talking to a hub over HTTP.

Shared by every client — the MCP server, the CLI, and eventually the console. There is
one place that knows how to reach the API, so timeout and error behaviour is defined
exactly once.

**This holds no messaging logic.** It has no idea what a thread is or who may see one;
it turns a method call into a request and a response into a dict. If a client ever needs
to *decide* something, the API is missing a route (ADR 0005).

Nothing here blocks forever. An agent that hangs waiting for a mailbox is worse off than
one told the mailbox is unreachable, so every call carries a timeout and every failure
comes back as a sentence saying what to do.
"""

import json
import logging
import os
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_inbox.locking import exclusive

#: What `join` writes, under the project's own name.
CONFIG_NAME = "agent-inbox.toml"

#: What it used to write, and what every already-joined project still holds. An identity
#: file is not ours to invalidate: an agent that cannot find its own name has lost its
#: correspondence, not merely its configuration. Read both, forever if need be.
LEGACY_CONFIG_NAME = "agent-mailbox.toml"

#: Both names, in the order they are preferred when a project somehow has each.
CONFIG_NAMES = (CONFIG_NAME, LEGACY_CONFIG_NAME)

logger = logging.getLogger(__name__)

IDENTITY_HEADER = "X-Agent-Name"

#: What client this is. Sent on every request so the hub can *observe* the version an
#: agent runs rather than being told it once at join and believing it for ever.
#:
#: The difference is not pedantry. On 2026-08-05 `igor_laszlo` found that installing on
#: an interpreter older than our floor silently resolves to an old release instead of
#: failing — two agents sat on 0.34.0, unable to be woken by the release that added
#: waking, and **nothing anywhere recorded which client an agent used**, so it was
#: invisible from the hub. A profile field written at join could not have answered it
#: either: those agents joined long before, and a claim about a past moment is not a
#: fact about now.
CLIENT_HEADER = "X-Agent-Inbox-Client"

#: What the hub says *it* is running, returned on every response. The mirror of the
#: header above, and the answer to the same class of problem in the other direction: a
#: version learned once and believed for ever is not an observation.
#:
#: Spelled here rather than imported from the hub — a client does not depend on the hub
#: package — and pinned by a test against `api.HUB_HEADER`, exactly as `CLIENT_HEADER`
#: is, so the two spellings cannot drift apart unnoticed.
HUB_HEADER = "X-Agent-Inbox-Hub"


def _note_hub(version: str) -> None:
    """Record the hub's version, and never let doing so break a call.

    A best-effort act following one that has already succeeded — the response is in
    hand — so the charter's boundary applies: this may fail silently, because a
    bookkeeping error here would turn a delivered message into an exception the agent
    sees instead. The cost of losing it is a staleness notice one call out of date.
    """
    if not version:
        return
    try:
        from agent_inbox import staleness

        staleness.note_hub_version(version)
    except Exception:  # noqa: BLE001 - see above: never fail a completed call
        logger.debug("could not record the hub version %r", version, exc_info=True)


#: Client settings, current name first. As with the hub's own prefix, the new name wins
#: when both are present: whoever set it is mid-migration and means the newer one.
ENV_NAMES: dict[str, tuple[str, ...]] = {
    "hub": ("AGENT_INBOX_HUB", "AGENT_MAILBOX_HUB"),
    "name": ("AGENT_INBOX_NAME", "AGENT_MAILBOX_NAME"),
    "role": ("AGENT_INBOX_ROLE", "AGENT_MAILBOX_ROLE"),
    "token": ("AGENT_INBOX_TOKEN", "AGENT_MAILBOX_TOKEN"),
}


def _our_version() -> str:
    """This client's version, or ``""`` when it cannot say.

    Imported lazily and defensively: a version lookup must never be the reason a
    request does not go out.
    """
    try:
        from agent_inbox import __version__

        return str(__version__ or "")
    except Exception:  # noqa: BLE001 - a missing version is not a reason to fail a call
        return ""


def env_setting(environ: dict[str, str], key: str) -> tuple[str, str]:
    """A client setting and the variable it came from, or ``("", "")``."""
    for var in ENV_NAMES[key]:
        if value := environ.get(var, "").strip():
            return value, var
    return "", ""


#: A machine-wide fallback, under the project's true name. Identity stays per project —
#: the same engine in two repositories is two correspondents — but a *credential* is
#: not an identity: it says the machine is allowed on the hub. Putting one shared token
#: here means a laptop is admitted once rather than in every repository it works in,
#: which is the difference between a thing an operator does and a chore they abandon.
GLOBAL_CONFIG_DIR = "agent-inbox"
GLOBAL_CONFIG_NAME = "config.toml"


def global_config_path(env: dict[str, str] | None = None) -> Path:
    """Where the machine-wide configuration lives (XDG, or ``~/.config``)."""
    environ = env if env is not None else dict(os.environ)
    base = environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / GLOBAL_CONFIG_DIR / GLOBAL_CONFIG_NAME


#: Held for the length of a read-modify-write of the project file, so two engines
#: joining at once cannot each write a file containing only themselves (issue #49).
#:
#: **Keyed to the project root, not to the config's filename.** The file may be
#: `agent-inbox.toml` or the legacy `agent-mailbox.toml`, and `_render_project` may
#: migrate one to the other *during* the write — a lock named after the file would be
#: released against a name that no longer exists, and two writers straddling the
#: migration would hold different locks and neither would be wrong.
PROJECT_LOCK_NAME = ".agent-inbox.lock"

#: The same, for the machine-wide file. Contention here is *more* likely than on a
#: project: every project on the machine shares this one file, so two agents in two
#: unrelated repositories joining at once are contending, and what they would lose is
#: the shared token.
GLOBAL_LOCK_NAME = "config.lock"


def project_lock_path(start: Path | None = None) -> Path:
    """Where the project write lock lives — beside the file it protects."""
    return project_root(start) / PROJECT_LOCK_NAME


def global_lock_path(env: dict[str, str] | None = None) -> Path:
    """Where the machine-wide write lock lives — beside the file it protects."""
    return global_config_path(env).with_name(GLOBAL_LOCK_NAME)


def write_global(settings: dict[str, str], env: dict[str, str] | None = None) -> Path:
    """Merge *settings* into the machine-wide file, creating it if need be.

    Merging, never replacing: the file may already hold a hub for another deployment,
    and a tool that silently discarded it would be worse than one that never wrote at
    all. Written 0600 — it holds a credential, and the default umask does not.

    Merging is not enough on its own. Two processes that each merge into what they read
    and each replace the file produce a file holding only the second one's work — the
    same lost update as replacing, arriving a step later. The lock is what makes the
    merge hold.
    """
    path = global_config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(global_lock_path(env)):
        _merge_global(settings, env)
    return path


def _merge_global(settings: dict[str, str], env: dict[str, str] | None) -> None:
    """The read-merge-write of :func:`write_global`. Call with the lock held.

    Split out so a caller that must *decide* from the current contents — see
    :func:`_set_machine_hub`, which refuses to overwrite a hub somebody chose — can
    hold the lock across its own read as well. Locking only the write would leave that
    decision made against a value another process had already replaced, which is the
    same lost update one level up.
    """
    data = load_global(env)
    data.update(settings)
    _render_global(global_config_path(env), data)


def _render_global(path: Path, data: dict[str, str]) -> None:
    """Write the machine-wide file. Call with the lock held.

    Atomic, for the same reason `_render_project` is: this file carries the shared
    token, and a crash between truncate and write left a machine with no credential
    and no indication why the hub had started refusing it.
    """
    lines = [
        "# agent-inbox — machine-wide settings, written by `agent-inbox configure`.",
        "# A shared token belongs here: it admits this machine, whatever project an",
        "# agent is working in. Identity stays per project, in agent-inbox.toml.",
        "",
        *(f"{key} = {_toml_str(str(value))}" for key, value in sorted(data.items())),
        "",
    ]
    tmp = _scratch(path)
    tmp.write_text("\n".join(lines))
    tmp.chmod(0o600)
    tmp.replace(path)


def _scratch(target: Path) -> Path:
    """A temp file beside *target* that no other process will pick as well.

    **Not merely tidiness.** A fixed `.tmp` name was shared by every writer, so two of
    them racing meant one renamed the file away and the other's next operation failed
    on a path that had ceased to exist — seen for real the first time the concurrent
    join test ran, as a `FileNotFoundError` from `chmod`. The lock makes that rare; the
    reclaim path (see `locking.exclusive`) means rare is not never, and an atomic write
    that only works when uncontended is not an atomic write.
    """
    return target.with_name(f"{target.name}.{os.getpid()}.tmp")


def write_project(
    settings: dict[str, str],
    start: Path | None = None,
    env: dict[str, str] | None = None,
    engine: str | None = None,
) -> Path:
    """Merge *settings* into this project's file, under one engine's entry.

    `hub` is the project's and sits at the top level; everything else belongs to an
    engine, so two agents in one repository do not overwrite each other.

    *engine* is passed when the caller was told which one — a human with `--engine`,
    or the MCP server acting for a named client. Falling back to `"default"` when
    nothing is known was how a human shell could write an entry that no real agent
    owns; callers that could be wrong now refuse rather than reach that line.

    **The lock spans the read and the write, not the write alone.** The rename in
    `_render_project` is already atomic, and atomicity is not the property that was
    missing: a second writer that read before this one renamed still holds a stale map
    of engines, and merging into it puts the file back the way it was.
    """
    environ = env if env is not None else dict(os.environ)
    engine = engine or detect_engine(environ) or "default"
    with exclusive(project_lock_path(start)):
        path = find_config(start) or (project_root(start) / CONFIG_NAME)
        existing: dict[str, Any] = {}
        if path.is_file():
            existing = tomllib.loads(path.read_text())
        hub = str(settings.get("hub") or existing.get("hub") or "").strip()
        entries = dict(existing.get("agents") or {})
        mine = dict(entries.get(engine) or {})
        for key, value in settings.items():
            if key != "hub":
                mine[key] = value
        entries[engine] = mine
        return _render_project(path, hub, entries)


def unset_global(name: str, env: dict[str, str] | None = None) -> bool:
    """Remove one machine-wide setting. True if it was there."""
    with exclusive(global_lock_path(env)):
        data = load_global(env)
        if name not in data:
            return False
        del data[name]
        _render_global(global_config_path(env), data)
        return True


def unset_project(
    name: str,
    start: Path | None = None,
    env: dict[str, str] | None = None,
    engine: str | None = None,
) -> bool:
    """Remove one setting from one engine's entry. True if it was there.

    Locked for the same reason the writers are, and the loss here is worse than a
    merge gone wrong: this one *replaces* the file from what it read, so a concurrent
    join is not merely merged over, it is deleted.
    """
    environ = env if env is not None else dict(os.environ)
    engine = engine or detect_engine(environ) or "default"
    with exclusive(project_lock_path(start)):
        path = find_config(start)
        if path is None or not path.is_file():
            return False
        data = tomllib.loads(path.read_text())
        if name == "hub":
            if not data.get("hub"):
                return False
            _render_project(path, "", dict(data.get("agents") or {}))
            return True
        entries = dict(data.get("agents") or {})
        mine = dict(entries.get(engine) or {})
        if name not in mine:
            return False
        del mine[name]
        entries[engine] = mine
        _render_project(path, str(data.get("hub") or ""), entries)
        return True


def effective_settings(
    start: Path | None = None, env: dict[str, str] | None = None
) -> dict[str, tuple[str, str]]:
    """Every setting in force, mapped to ``(value, where it came from)``.

    The point of `config list`: a value can arrive from the environment, this project,
    or the machine-wide file, and "which one won" is the question people open the files
    to answer. Answering it here is what keeps them shut.
    """
    environ = env if env is not None else dict(os.environ)
    engine = detect_engine(environ)
    found: dict[str, tuple[str, str]] = {}

    shared = load_global(environ)
    for key in ("hub", "token"):
        if value := str(shared.get(key, "")).strip():
            found[key] = (value, str(global_config_path(environ)))

    path = find_config(start)
    if path is not None:
        data = tomllib.loads(path.read_text())
        if hub := str(data.get("hub", "")).strip():
            found["hub"] = (hub, str(path))
        entries = data.get("agents") or {}
        mine = entries.get(engine) if engine else None
        if mine is None and len(entries) == 1 and not engine:
            mine = next(iter(entries.values()))
        if isinstance(mine, dict):
            for key in ("name", "role", "token"):
                if value := str(mine.get(key, "")).strip():
                    found[key] = (value, str(path))
        elif len(entries) > 1 and not engine:
            # Ambiguous rather than absent. Omitting these silently would report a
            # project as unconfigured when it is configured several times over.
            for key in ("name", "role"):
                if any(str((e or {}).get(key, "")).strip() for e in entries.values()):
                    found[key] = (
                        f"<ambiguous: {', '.join(sorted(entries))}>",
                        str(path),
                    )

    for key in ENV_NAMES:
        value, var = env_setting(environ, key)
        if value:
            # The variable's real name, not the canonical one: `config list` exists to
            # answer "where did this come from", and naming a variable the operator has
            # not set would be a worse answer than none.
            found[key] = (value, var)
    return found


def load_global(env: dict[str, str] | None = None) -> dict[str, Any]:
    """The machine-wide file, or an empty mapping. Never raises for absence."""
    path = global_config_path(env)
    try:
        return tomllib.loads(path.read_text())
    except OSError, tomllib.TOMLDecodeError:
        return {}


#: What a config holds before this engine has a name — the CLI and the MCP client both
#: need *something* in the identity header to make their very first call. It is a
#: placeholder, never a claim: `join` translates it back to "issue me one" so the first
#: engine to join without a name cannot squat it and lock everyone else out.
UNNAMED = "unnamed"

#: Must match the hub's cookie name (agent_inbox.api.SESSION_COOKIE). Defined here too
#: so the stdlib client stays free of any dependency on the Litestar app module.
SESSION_COOKIE = "agent_inbox_session"
DEFAULT_TIMEOUT = 10.0

#: How long to keep trying a hub that is refusing connections because it is starting.
#:
#: A hub scaled to zero, or restarting mid-deploy, refuses for a second or two and then
#: answers. Treating that as "no such hub" is what made the first call after a quiet
#: period fail for everybody, every time (issue #34).
#:
#: **Short on purpose.** An agent that waits a minute inside one tool call has had its
#: turn silently consumed, which is worse than a fast error — so this is a handful of
#: seconds, not a patient retry loop. A hub that is genuinely down still says so
#: quickly.
STARTUP_GRACE = 6.0

#: How long to wait between those attempts. Fixed and small: this is a local service
#: coming up, not a contended remote one, so there is no herd to spread and nothing to
#: gain from backing off.
STARTUP_RETRY_EVERY = 0.75

#: Which engine am I? Markers checked most-specific first.
#:
#: This matters because **identity is per engine, not per project**. Several agents work
#: in one repository — Claude, Codex, Gemini — and they are not the same correspondent.
#: Two of them sharing a name would silently share an inbox, which is the exact failure
#: the hub's name reservation exists to prevent.
ENGINE_MARKERS: tuple[tuple[str, str], ...] = (
    ("CLAUDECODE", "claude"),
    ("CLAUDE_CODE_ENTRYPOINT", "claude"),
    ("CODEX_SANDBOX", "codex"),
    ("CODEX_HOME", "codex"),
    # A real Codex session was not detected by the two markers above: it carried
    # CODEX_THREAD_ID, CODEX_CI and CODEX_MANAGED_BY_NPM instead, so the agent had to
    # pass --engine and set AGENT_INBOX_* by hand for every command. Detection that
    # only works on some installs is worse than none, because the failure is a wrong
    # identity rather than an honest "I do not know".
    ("CODEX_THREAD_ID", "codex"),
    ("CODEX_MANAGED_BY_NPM", "codex"),
    ("CODEX_CI", "codex"),
    ("GEMINI_CLI", "gemini"),
    ("CURSOR_TRACE_ID", "cursor"),
    # Reported by `aurelia_saahaa`, the first agent here on opencode, from their own
    # environment (2026-08-09). Until this, opencode was in neither detection path, so
    # the server could not match a session to its `[agents.opencode]` entry and the
    # agent had to set `AGENT_INBOX_NAME` by hand.
    ("OPENCODE", "opencode"),
)


def detect_engine(env: dict[str, str] | None = None) -> str | None:
    """Which agent engine is running, or ``None`` if we cannot tell.

    Never guessed. A wrong answer would hand one engine another's identity, and an
    honest "I do not know" is answerable by the agent naming itself.
    """
    environ = env if env is not None else dict(os.environ)
    for marker, engine in ENGINE_MARKERS:
        if environ.get(marker):
            return engine
    return None


class ClientError(Exception):
    """Something went wrong reaching or using the hub, said in words."""


class NotConfigured(ClientError):
    """No hub or name is known. Carries the command that fixes it."""


class HubTimeout(ClientError):
    """The hub took the connection and did not answer in time (issue #31).

    **A separate type because the right response is different.** A hub that refuses the
    connection is not there, and retrying in a loop is how an agent spends a session on
    something that cannot work. A hub that accepted the connection and went quiet is
    usually there and busy — `nadia_harari` observed a 30-second timeout followed
    immediately by a successful retry with nothing else changed.

    Advice keyed off the message text could not tell those apart, and gave the
    unreachable answer — *"do not retry"* — to the one case where retrying is right.

    It says nothing about whether retrying is **safe**. That depends on what was being
    attempted and only the caller knows: a timed-out send may have arrived, and asking
    again would be a second message. `_open` draws the same line for connection retries
    and for the same reason.
    """


@dataclass(frozen=True, slots=True)
class Config:
    """Where the hub is, who we are, and what we do here."""

    hub: str
    name: str
    #: What this engine does on this project — descriptive, and stored in the profile
    #: rather than encoded into the name (ADR 0003).
    role: str = "agent"
    #: Which engine this identity belongs to, when known.
    engine: str | None = None
    #: A token minted by an operator. When set, it is sent as a bearer credential
    #: and is how the hub authenticates this agent once auth is enforced.
    token: str | None = None

    @property
    def base(self) -> str:
        return self.hub.rstrip("/")


def find_config(start: Path | None = None) -> Path | None:
    """Look for the project's identity file here and upwards, stopping at a repo root.

    Stopping at the boundary is deliberate: walking further would let one project
    silently adopt a sibling's identity.

    Both ``agent-inbox.toml`` and the older ``agent-mailbox.toml`` are recognised, the
    current name first. **Per directory, not per name** — a nearer legacy file beats a
    distant current one, because the question being answered is "which project am I in",
    and that is settled by proximity. Sweeping one name over the whole tree first would
    let a parent project's file win over the one sitting beside you.
    """
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if (directory / ".git").exists():
            break
    return None


def load_hub(start: Path | None = None, env: dict[str, str] | None = None) -> str:
    """The hub url alone, whether or not *this* engine has an entry yet.

    The hub belongs to the project; the identity belongs to the engine. A second engine
    joining a project already configured by the first should not have to be told the url
    again — it is sitting in the file.
    """
    environ = env if env is not None else dict(os.environ)
    if from_env := env_setting(environ, "hub")[0]:
        return from_env
    path = find_config(start)
    if path is not None:
        if hub := str(tomllib.loads(path.read_text()).get("hub", "")).strip():
            return hub
    return str(load_global(environ).get("hub", "")).strip()


def configured_engines(start: Path | None = None) -> list[str]:
    """Which engines this project has entries for, in file order.

    The CLI needs this to *ask a good question*. "I cannot tell which engine you are"
    is a dead end; "configured engines: claude, codex — rerun with --engine codex" is
    an instruction, and the difference is whether the caller has to go and read a file
    to answer.
    """
    path = find_config(start)
    if path is None:
        return []
    try:
        data = tomllib.loads(path.read_text())
    except OSError, tomllib.TOMLDecodeError:
        return []
    return [str(key) for key in (data.get("agents") or {})]


def duplicate_names(start: Path | None = None) -> dict[str, list[str]]:
    """Names claimed by more than one engine in this project, mapped to those engines.

    Two engines sharing a name is not a cosmetic mistake: they share an *inbox*. Mail
    for one is consumed by whichever reads first and is then gone, so the symptom is
    messages that vanish rather than an error anybody can see. The hub cannot catch it
    — each side presents the same name and is, as far as it can tell, the same
    correspondent — so the only place it can be noticed is here, in the file that
    assigns them.

    Compared case-insensitively. Hub-issued names are lowercase, so a difference of
    case means a hand-edited file, and two entries differing only in case would collide
    on the hub while looking distinct in the file — the worst of both.
    """
    path = find_config(start)
    if path is None:
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except OSError, tomllib.TOMLDecodeError:
        return {}
    seen: dict[str, list[str]] = {}
    for engine, entry in (data.get("agents") or {}).items():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if name and name != UNNAMED:
            seen.setdefault(name.casefold(), []).append(str(engine))
    return {n: sorted(e) for n, e in seen.items() if len(e) > 1}


def load_config(
    start: Path | None = None,
    env: dict[str, str] | None = None,
    engine: str | None = None,
) -> Config:
    """Read this engine's entry from the project's configuration.

    The file maps **engine to identity**, because one repository is worked by several
    agents and they are different correspondents::

        hub = "http://hub:8081"

        [agents.claude]
        name = "jed_smith"
        role = "agent"

        [agents.codex]
        name = "brian_hanson"
        role = "host"

    Environment wins over the file, so a container or a one-off can override without
    editing anything.
    """
    environ = env if env is not None else dict(os.environ)
    hub = env_setting(environ, "hub")[0]
    name = env_setting(environ, "name")[0]
    role = env_setting(environ, "role")[0]
    token = env_setting(environ, "token")[0]
    # An explicit engine wins over sniffing the environment. The MCP server knows which
    # client connected to it — the client says so in `initialize` — and that is a
    # better answer than markers that a client may not pass through to a process it
    # spawns. Without it, a project with two engines configured is unresolvable.
    engine = engine or detect_engine(environ)

    path = find_config(start)
    if path is not None:
        data = tomllib.loads(path.read_text())
        hub = hub or str(data.get("hub", "")).strip()
        entries = data.get("agents") or {}
        mine = entries.get(engine) if engine else None
        if mine is None and len(entries) == 1 and not engine:
            # One entry and no detectable engine: it can only be meant for us.
            mine = next(iter(entries.values()))
        if isinstance(mine, dict):
            name = name or str(mine.get("name", "")).strip()
            role = role or str(mine.get("role", "")).strip()
            token = token or str(mine.get("token", "")).strip()
        elif not entries:
            # A single flat identity, from before this file grew a mapping.
            name = name or str(data.get("name", "")).strip()
            role = role or str(data.get("role", "")).strip()
            token = token or str(data.get("token", "")).strip()

    # A credential, unlike an identity, is not per project: one shared token in the
    # machine-wide file admits this box for every repository on it. The project file
    # still wins, so a per-agent token continues to override the shared one.
    if not token or not hub:
        shared = load_global(environ)
        token = token or str(shared.get("token", "")).strip()
        hub = hub or str(shared.get("hub", "")).strip()

    if not hub or not name:
        missing = " and ".join(
            bit
            for bit in ("a hub url" if not hub else "", "a name" if not name else "")
            if bit
        )
        raise NotConfigured(
            f"no mailbox configuration: missing {missing}.\n"
            f"Write {CONFIG_NAME} in your project root:\n\n"
            '    hub = "http://<host>:8081"\n'
            '    name = "your_name"\n\n'
            "Or set AGENT_INBOX_HUB and AGENT_INBOX_NAME. If you have no name yet, "
            "any name you like will do — the hub will tell you if it is taken."
        )
    return Config(
        hub=hub,
        name=name,
        role=role or "agent",
        engine=engine,
        token=token or None,
    )


def project_root(start: Path | None = None) -> Path:
    """Where configuration belongs: the repository root, or the working directory.

    A repository is the honest boundary for a project. Writing above it would let one
    project silently adopt a sibling's identity, which is the same reason
    :func:`find_config` stops there on the way up.
    """
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / ".git").exists():
            return directory
    return here


def _toml_str(value: str) -> str:
    """A TOML basic string, correctly escaped.

    There is no TOML *writer* in the standard library, only a reader, so this is the one
    place we must serialise by hand — and doing it naively is a real bug: a value with a
    quote or a backslash produced a file that no longer parsed, silently losing every
    identity below it. Escape the characters the spec requires.
    """
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{out}"'


def write_config(
    hub: str,
    name: str,
    engine: str,
    role: str = "agent",
    start: Path | None = None,
    force: bool = False,
    token: str | None = None,
) -> Path:
    """Add or update **this engine's** entry, leaving every other one alone.

    Merging rather than replacing is the whole point. Several agents work in one
    repository — Claude, Codex, Gemini — and each needs its own identity, because two
    sharing a name would silently share an inbox. A writer that replaced the file would
    evict whoever configured themselves first, and the eviction would be invisible until
    their mail stopped arriving.

    An existing entry for this engine is left as it is unless ``force`` is given:
    changing a name means mail addressed to the old one stops being delivered.

    The write is atomic (temp file + rename) and every value is escaped, so a
    name or token with an awkward character cannot corrupt the file or lose the
    entries below it.

    **Atomicity was never the missing half** (issue #49). Two engines joining a project
    in the same moment each read a file without the other's entry, each merge into what
    they read, and each rename a complete, well-formed file over the top — and the first
    one's identity is gone. It is exactly the eviction the paragraph above says merging
    prevents, arriving through the read rather than the write, and it is invisible until
    somebody's mail stops arriving. So the lock spans from the read to the rename.
    """
    # **Merge into the file that is actually in force, whichever name it wears.** This
    # was `project_root(start) / CONFIG_NAME` — always the canonical name — so a project
    # still using the supported back-compat `agent-mailbox.toml` got a *brand new*
    # `agent-inbox.toml` containing only the joining engine. The new file then takes
    # precedence, and every other engine's identity disappears at once.
    #
    # That is precisely the eviction the docstring above says merging exists to prevent,
    # arriving by a different route: the merge was careful, it simply read a different
    # file than the one being used. Observed on this repository — a project holding
    # `claude` and `codex` was joined as `claude` and came back holding `claude` alone,
    # with the other identity still on disk and no longer read.
    # The project lock is taken before the machine-wide one, here and everywhere. Both
    # are only ever held in that order, which is what stops the pair deadlocking; a
    # writer that took the machine-wide lock and then reached for a project's would
    # close the cycle, so if one is ever added, add it the same way round.
    with exclusive(project_lock_path(start)):
        target = find_config(start) or (project_root(start) / CONFIG_NAME)
        existing: dict[str, Any] = {}
        if target.exists():
            existing = tomllib.loads(target.read_text())

        agents: dict[str, Any] = dict(existing.get("agents") or {})
        _prior = agents.get(engine)
        prior: dict[str, Any] = _prior if isinstance(_prior, dict) else {}
        if engine in agents and not force:
            held = prior.get("name")
            raise ClientError(
                f"{engine} is already {held!r} on this project (in {target}). "
                "Keep it, or pass force to change it — mail addressed to the old name "
                "stops arriving."
            )
        entry = {"name": name, "role": role}
        # Keep a token we already had unless a new one is given — reconfiguring
        # identity should not silently drop the credential.
        kept_token = token or prior.get("token")
        if kept_token:
            entry["token"] = kept_token
        agents[engine] = entry

        # **The hub is machine-wide unless this project already pins one** (v0.48.0).
        # Writing it here unconditionally is what `join` used to do, and it re-created
        # the shadowing the machine-wide default exists to remove: every project joined
        # against a hub was silently pinned to it for ever, and a later `config set hub`
        # appeared to do nothing. A project that *has* its own hub keeps it — that is a
        # deliberate choice somebody made, and `doctor` reports it so it cannot be
        # forgotten.
        pinned = str(existing.get("hub") or "").strip()
        # **A credential keeps its hub beside it.** If this engine carries its own
        # token, the address it was minted against belongs in the same file — otherwise
        # the hub goes machine-wide while the token stays here, and the engine loads the
        # new hub with the old hub's key. The hub then answers `token rejected`, which
        # points at the one thing that is not wrong. Found by an outside review, and it
        # is the same rule `config set` enforces: hub and token live together.
        if not pinned and hub and not kept_token:
            _set_machine_hub(hub)
        elif not pinned and hub:
            pinned = hub
        return _render_project(target, pinned, agents)


def _set_machine_hub(hub: str, env: dict[str, str] | None = None) -> None:
    """Record the machine-wide hub — but never *change* one that is already set.

    Writing it when nothing is there is the whole point of the machine-wide file, and
    stays. **Overwriting a different value is a different act**, and it was silently
    undoing deliberate operator settings: on 2026-08-04 a correct hub was set three
    times by hand and reverted three times to an address that does not resolve, because
    a long-lived process still holding the old value called `join` in the background and
    won each time. Mail then failed, in another project, minutes later, with nothing
    anywhere connecting the two.

    An empty project hub is **not** the fault, despite appearances: it is what this
    module writes when the hub is machine-wide, so every well-behaved project has one.
    The fault is that a background write outranked a human.

    So: absent, or the same — write. Different — keep what is there and say so. That is
    the safe direction, because the value already in the file is the one somebody chose,
    and a config tool that loses an operator's decision is worse than one that declines
    to make it.
    """
    # Read and write under one lock. The decision below is made *from* the current
    # value, so a read outside the lock is a decision about a file that may already
    # have changed — and the losing branch is the dangerous one: it would conclude
    # "absent, or the same" from a stale read and overwrite a hub somebody had just
    # chosen, which is the failure this function exists to have stopped.
    global_config_path(env).parent.mkdir(parents=True, exist_ok=True)
    with exclusive(global_lock_path(env)):
        current = str(load_global(env).get("hub") or "").strip()
        if current and current != hub:
            logger.warning(
                "event=config.hub.kept existing=%s offered=%s — the machine-wide hub "
                "was already set; keeping it. Change it deliberately with "
                "`agent-inbox config --global set hub <url>`.",
                current,
                hub,
            )
            return
        _merge_global({"hub": hub}, env)


#: What a caller is told after a config write moved the file. Empty when nothing moved.
#:
#: Returned rather than printed, because this module has no business writing to a
#: terminal — the CLI and the MCP server present it differently, and one of them is
#: talking to a program.
MigrationNotice = str


def migrate_project_name(target: Path) -> tuple[Path, str]:
    """Where a project write should actually land, and what to say about it (#12).

    v0.24.0 renamed the project file to ``agent-inbox.toml`` and kept reading the old
    ``agent-mailbox.toml``, so nothing broke and nothing moved. That is the right trade
    for a release and the wrong one forever: every project that existed then is still on
    the old name, and "we read both names indefinitely" is a cost that only grows.

    **Migrating on write is the shape that needs nobody to remember it.** The file is
    already being rewritten, by somebody already running a command that changes
    configuration. Read-only commands never reach here — `doctor`, `config list`,
    `whoami` and `ping` all resolve config without rendering it, and a diagnostic that
    mutated the thing it was diagnosing would be a trap, most of all in `doctor`, which
    is run precisely to understand a broken state.

    Three cases, and two of them refuse to move anything:

    **A tracked legacy file is not renamed.** `agent-mailbox.toml` was git-tracked in
    this very repository until `02e5d12`; an ignore rule cannot untrack what is already
    in the index. A plain rename there reads to git as *the agent's identity was
    deleted*, plus a new ignored file nobody can see. `git mv` would work, but quietly
    rewriting somebody's index during `config set` is a larger surprise than the one
    being fixed. So it is reported and left alone.

    **Both files present: the current name wins and the old one is not touched.**
    `find_config` already prefers the current name, so this is reached by way of a
    half-finished migration rather than by design — but two identity files in one
    project is a state a human should hear about rather than have tidied away.

    Otherwise the write moves to the current name and the ignore rule is *fixed*, not
    merely mentioned. The request asked for a reminder; a reminder is what was already
    there and it is what `parisa_murthy` demonstrated does not work — a `.gitignore`
    naming the pre-rename file reads as protection on inspection. Renaming without
    fixing it would silently undo a protection the project already had, which is worse
    than not renaming at all.
    """
    if target.name != LEGACY_CONFIG_NAME:
        stale = target.with_name(LEGACY_CONFIG_NAME)
        if stale.is_file():
            return target, (
                f"Two identity files here: {CONFIG_NAME} and the older "
                f"{LEGACY_CONFIG_NAME}. {CONFIG_NAME} is the one in use; nothing has "
                f"been changed. Delete {LEGACY_CONFIG_NAME} once you have checked it "
                "holds nothing you still want."
            )
        return target, ""

    current = target.with_name(CONFIG_NAME)
    if current.is_file():
        return current, (
            f"Writing {CONFIG_NAME}, which already exists alongside the older "
            f"{LEGACY_CONFIG_NAME}. The older file has been left exactly as it is."
        )

    # Imported here, not at module scope: `ignores` imports this module. A lazy import
    # is the cost of keeping the dependency pointing one way.
    from agent_inbox import ignores

    root = project_root(target.parent)
    if ignores.is_tracked(target, root):
        return target, (
            f"{LEGACY_CONFIG_NAME} is tracked by git, so it has not been renamed to "
            f"{CONFIG_NAME} — to git a rename would read as your identity being "
            "deleted, and the replacement would be invisible. Do it deliberately:\n"
            f"    git mv {LEGACY_CONFIG_NAME} {CONFIG_NAME}\n"
            "and revoke any token it carried; a tracked identity file is in the "
            "history whether or not it is renamed."
        )

    said = f"Renamed {LEGACY_CONFIG_NAME} to {CONFIG_NAME}."
    state = ignores.ensure_ignored(current, root)
    if state == "added":
        said += (
            f" Your .gitignore named {LEGACY_CONFIG_NAME} or nothing at all, so a rule "
            f"for {CONFIG_NAME} has been added — without it the rename would have "
            "turned an ignored file into a committable one."
        )
    elif state == "already":
        said += " It was already ignored by git under the new name."
    return current, said


#: Set by the last project write, read and cleared by whoever presents it.
#:
#: A module-level hand-off is not pretty. The alternative is changing the return type of
#: `write_project`, `unset_project` and `write_config` — three public functions with
#: callers in the CLI, the MCP server and the tests — to carry a string that is empty
#: almost every time. This is the smaller change, and the notice is worthless if it is
#: not read: `take_migration_notice` empties it, so it cannot be reported twice.
_migration_notice: str = ""


def take_migration_notice() -> str:
    """What the last config write moved, if anything. Reading it clears it."""
    global _migration_notice
    said, _migration_notice = _migration_notice, ""
    return said


def _render_project(target: Path, hub: str, agents: dict[str, Any]) -> Path:
    """Write the project file. One renderer, so `join` and `configure` cannot drift.

    **Every project write passes through here**, which is why the filename migration
    lives here rather than in each of the three callers. A migration that each writer
    had to remember would be a migration one of them forgot.
    """
    global _migration_notice
    legacy = target
    target, said = migrate_project_name(target)
    moved = target != legacy
    if said:
        _migration_notice = said
    lines = [
        "# agent-inbox — where the mailbox is, and who each agent here is on it.",
        "# Written by `join` and `agent-inbox configure`, one entry per engine. Do not",
        "# commit it: it names a deployment and may carry a token. Do not",
        "# hand-edit it either — `configure` knows where every setting belongs.",
        "",
        # Omitted entirely when there is none, rather than written as `hub = ""`. An
        # empty value is not a setting, and a file that states one invites a reader to
        # fill it in — quietly re-pinning the project to whatever they type.
        *([f"hub = {_toml_str(hub)}", ""] if hub else []),
        "# One identity per engine: several agents work in this repository and they",
        "# are different correspondents. Names are permanent and deliberately",
        "# meaningless — do not encode the project or the model into them. What an",
        "# agent *does* here is its role; the rest belongs in `update_profile`.",
    ]
    for key in sorted(agents):
        item = agents[key]
        lines += ["", f"[agents.{key}]"]
        if item.get("name"):
            lines.append(f"name = {_toml_str(str(item['name']))}")
        lines.append(f"role = {_toml_str(str(item.get('role', 'agent')))}")
        if item.get("token"):
            lines.append(f"token = {_toml_str(str(item['token']))}")
    # Atomic: write a sibling temp file and rename over the target, so a crash mid-write
    # never leaves a half-written config that loses everyone's identity.
    tmp = _scratch(target)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(target)
    # **The old file goes only after the new one is on disk.** Dying between the two
    # leaves both, which `find_config` resolves in favour of the current name and which
    # the "two identity files" branch above then reports. Dying the other way round
    # would leave neither, and an agent with no identity at all.
    if moved and legacy.is_file():
        legacy.unlink()
    return target


def _from_older_hub(page: Any, *, view: str, asked_since: bool) -> dict[str, Any]:
    """An older hub's inbox, translated into the shape this client expects.

    A hub that predates compact views ignores `view` and `since` and returns the AS2
    collection of full notes it always did. Reading that with the new keys produced
    `0` from `--count` and rows of `?` and `(None chars)` from a plain `inbox` — an
    empty mailbox and a corrupt one, neither of them true, and no hint that the hub
    was the reason. pablo_fantomas hit exactly that against a 0.16.1 hub and was right
    to report it rather than trust it.

    So: translate what can be translated exactly, and *say* what could not. `since`
    cannot be honoured here — the filtering is the hub's job and this hub does not do
    it — and quietly returning unfiltered mail as though it were new would be the same
    lie in a different place.
    """
    notes = page.get("items", []) if isinstance(page, dict) else []
    items = [
        {
            "id": note.get("id"),
            "type": "Note",
            "attributedTo": note.get("attributedTo"),
            "summary": note.get("summary") or "(no subject)",
            "published": note.get("published"),
            "inReplyTo": note.get("inReplyTo"),
            "broadcast": len(note.get("to") or []) + len(note.get("cc") or []) > 1,
            "chars": len(note.get("content") or ""),
        }
        for note in notes
    ]
    translated: dict[str, Any] = {
        "unread": page.get("totalItems", len(items)),
        "totalItems": page.get("totalItems", len(items)),
        "cursor": "",
        # The caller must be able to tell it is looking at a downgraded answer.
        "hubTooOld": True,
        "sinceIgnored": asked_since,
    }
    if view == "threads":
        # Grouped here rather than at the hub, which is a compromise this shim exists
        # to make visible: on a current hub the grouping is the hub's.
        groups: dict[str, list[dict[str, Any]]] = {}
        known = {row["id"] for row in items}
        for row in items:
            parent = row["inReplyTo"]
            groups.setdefault(
                parent if parent in known else row["id"] or "", []
            ).append(row)
        translated["threads"] = [
            {
                "root": root,
                "subject": turns[0]["summary"],
                "unread": len(turns),
                "lastFrom": turns[-1]["attributedTo"],
                "lastPublished": turns[-1]["published"],
                "broadcast": turns[-1]["broadcast"],
            }
            for root, turns in groups.items()
        ]
    elif view != "count":
        translated["items"] = items
    return translated


class _FederationClient:
    """Federation reads and writes, as thin as every other client surface.

    **Nothing here decides anything** (NFR-003, C-006). Each method turns a call into a
    request and hands back what the hub said. Whether a peer may be added, whether a
    block applies, what a mode permits — all of that is the hub's, and a client that
    recomputed any of it would be the second implementation nobody thinks to look at,
    which is precisely the shape C-006 warns about.

    Mixed into :class:`HubClient` rather than standing alone so that callers keep one
    object with one credential and one timeout.
    """

    _call: Any

    def peers(self) -> Any:
        return self._call("GET", "/observe/peers")

    def add_peer(self, origin: str, note: str = "") -> Any:
        return self._call("POST", "/observe/peers", {"origin": origin, "note": note})

    def remove_peer(self, origin: str) -> Any:
        return self._call(
            "DELETE", f"/observe/peers?origin={urllib.parse.quote(origin, safe='')}"
        )

    def blocks(self) -> Any:
        return self._call("GET", "/observe/blocks")

    def add_block(self, origin: str, note: str = "") -> Any:
        return self._call("POST", "/observe/blocks", {"origin": origin, "note": note})

    def remove_block(self, origin: str) -> Any:
        return self._call(
            "DELETE", f"/observe/blocks?origin={urllib.parse.quote(origin, safe='')}"
        )

    def retract_message(self, object_id: str) -> Any:
        """Withdraw one message's body. Who may is the hub's decision, not ours."""
        return self._call("POST", f"/objects/{object_id}/retract")

    def retract_thread(self, object_id: str) -> Any:
        """Withdraw every message in a thread the caller has the power to.

        Returns both lists — what went and what stayed. A caller that reported only
        success would tell an operator a conversation is gone when half of it is not.
        """
        return self._call("POST", f"/objects/{object_id}/retract-thread")

    def hub_settings(self) -> Any:
        """Each setting with its value **and its source** — the shape `config list`
        already uses, so an operator learns one way of being told what governs what."""
        return self._call("GET", "/hub/settings")

    def set_hub_settings(self, **settings: str) -> Any:
        return self._call("PUT", "/hub", dict(settings))


class HubClient(_FederationClient):
    """One hub, over HTTP.

    Deliberately uses the standard library. A client that an agent installs should not
    drag a dependency tree behind it, and this is a couple of dozen small requests.

    It does not hold the event stream, and that is not an oversight: every call here is
    request-and-answer, while a stream is held for as long as a session lasts. The two
    have different lifetimes and belong in different places. What this offers instead is
    :meth:`events_url` and :meth:`stream_headers` — the address and the credential,
    worked out exactly once, so that whatever *does* hold the connection cannot
    authenticate differently from the rest of the client.
    """

    def __init__(
        self,
        config: Config,
        timeout: float = DEFAULT_TIMEOUT,
        session: str | None = None,
    ) -> None:
        self.config = config
        self.timeout = timeout
        #: A human operator's session, borrowed for the length of one request.
        self.session = session

    def acting_as(self, name: str, session: str | None = None) -> HubClient:
        """The same client, acting under a different name.

        The console needs this once a hub authenticates: a signed-in operator is their
        own correspondent, not the console process. Reading "the console's inbox" while
        logged in as somebody else showed the wrong mailbox at best, and was refused at
        worst — the hub resolves a session to *that human*, and the path has to agree.
        """
        return HubClient(
            Config(
                hub=self.config.hub,
                name=name,
                role=self.config.role,
                engine=self.config.engine,
                token=self.config.token,
            ),
            self.timeout,
            session=session or self.session,
        )

    def whoami(self) -> str | None:
        """Who the hub says we are, given whatever credential we carry.

        Asked of `/doctor`, which answers rather than refusing, so this works for a
        caller whose credential is missing as well as one whose credential is good.
        """
        try:
            return (self.remote_doctor() or {}).get("you", {}).get("verified")
        except ClientError:
            return None

    def with_session(self, session: str | None) -> HubClient:
        """The same client, acting with a human's session attached.

        The console needs this because it observes *on behalf of* whoever is signed in.
        Under enforce it has no credential of its own — nor should it, or anyone
        reaching the console would see every mailbox without logging in — so it carries
        the operator's session inward and the hub decides. Authority stays with the
        human; the console only passes it along.
        """
        if not session:
            return self
        return HubClient(self.config, self.timeout, session=session)

    # -- the event stream --------------------------------------------------

    def events_url(self) -> str:
        """Where this identity's event stream lives."""
        return f"{self.config.base}/actors/{self.config.name}/events"

    def hub_events_url(self) -> str:
        """Where the hub's own stream lives — every arrival, not one identity's.

        Carries no name, because the route takes no caller: it is an `/observe/*` route
        like the rest of the operator's view. :meth:`stream_headers` still applies, for
        the reason given there — holding a connection open does not make this a
        different client, and an authenticating hub refuses an uncredentialed one.
        """
        return f"{self.config.base}/observe/events"

    def stream_headers(self) -> dict[str, str]:
        """The same credentials every other call sends, for a caller that is not us.

        Duplicated auth is how a stream ends up working on an open hub and refused on an
        authenticated one, months apart from the change that caused it. One place
        decides what a request from this client looks like, and holding a connection
        open does not make it a different client.
        """
        headers = {
            "Accept": "text/event-stream",
            IDENTITY_HEADER: self.config.name,
            CLIENT_HEADER: _our_version(),
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        if self.session:
            headers["Cookie"] = f"{SESSION_COOKIE}={self.session}"
        return headers

    # -- plumbing ----------------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header(IDENTITY_HEADER, self.config.name)
        request.add_header(CLIENT_HEADER, _our_version())
        # A token, when we have one, is how the hub authenticates us once auth is
        # enforced. The identity header stays too, and is simply ignored under enforce.
        if self.config.token:
            request.add_header("Authorization", f"Bearer {self.config.token}")
        if self.session:
            request.add_header("Cookie", f"{SESSION_COOKIE}={self.session}")
        try:
            with self._open(request) as response:
                # Every answer says which hub gave it, so the staleness notice
                # reflects the hub as it is now rather than as it was when this
                # session started. `mariana_taphrale` found an MCP session repeating
                # a version the hub had left two releases behind: it learned it once,
                # from `ping`, and nothing ever corrected it.
                _note_hub(response.headers.get(HUB_HEADER, ""))
                raw = response.read()
                if not raw:
                    return None
                return self._decode(raw, response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as exc:
            raise self._from_response(exc) from exc
        except urllib.error.URLError as exc:
            raise ClientError(
                f"cannot reach the mailbox at {self.config.base} ({exc.reason}). "
                "Check the hub is running and the url is right."
            ) from exc
        except TimeoutError as exc:
            raise HubTimeout(
                f"the mailbox at {self.config.base} did not answer within "
                f"{self.timeout:g}s. It took the connection, so it is there — it may "
                "be busy, or starting up."
            ) from exc

    def _open(self, request: urllib.request.Request) -> Any:
        """Open the request, giving a hub that is *starting* a few seconds to finish.

        A hub scaled to zero, or restarting mid-deploy, refuses connections for a second
        or two and then serves normally. Without this the first call after any quiet
        period fails — for every agent, every time — and looks identical to a hub that
        is not there at all (issue #34).

        **Only `ConnectionRefusedError`, and that is the whole safety argument.** A
        refused connection is the one failure where we know the request never reached
        the hub, so replaying it cannot duplicate anything. A timeout is not that: the
        hub may have received the request, acted on it, and been slow to answer — and a
        retried send that already arrived is a second message, which is a worse outcome
        than the error it would be hiding. So timeouts, resets and DNS failures are
        raised as they always were.

        Bounded at :data:`STARTUP_GRACE`, deliberately short. An agent that waits a
        minute inside one tool call has had its turn spent on our behalf.
        """
        deadline = time.monotonic() + STARTUP_GRACE
        said = False
        while True:
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)  # noqa: S310
            except urllib.error.URLError as exc:
                if not isinstance(exc.reason, ConnectionRefusedError):
                    raise
                if time.monotonic() >= deadline:
                    raise
                if not said:
                    # Once, and to stderr: a client that appears hung is the complaint
                    # this would otherwise cause. Not repeated, because a line per
                    # attempt is noise in an agent's transcript.
                    print(
                        f"waiting for the mailbox at {self.config.base} to start…",
                        file=sys.stderr,
                    )
                    said = True
                time.sleep(STARTUP_RETRY_EVERY)

    def _decode(self, raw: bytes, content_type: str) -> Any:
        """The body as JSON, or a sentence naming what arrived instead.

        **The commonest misconfiguration there is**, and it used to end in thirty lines
        of `JSONDecodeError` with the url mentioned nowhere: the console address given
        where the API address was meant. The console answers a browser, so it returns a
        redirect and some HTML, and every client call then died inside `json.loads`
        pointing at the one thing that was not wrong.

        It is worth catching precisely because of who hits it. The console is the
        address a human bookmarks and the one they can see working in a browser, so it
        is the natural thing to paste — and the resulting traceback names neither the
        address, the thing that answered, nor what to do about it.
        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            kind = (content_type or "").split(";")[0].strip() or "no content type"
            hint = ""
            if "html" in kind:
                # Named, not guessed at: this is what a console does to an API request,
                # and saying so turns a puzzle into a one-line correction.
                hint = (
                    " That looks like a web page rather than the API — this is usually "
                    "the console's address given where the hub's API address was meant."
                )
            raise ClientError(
                f"the mailbox at {self.config.base} answered with {kind}, not JSON."
                f"{hint} Check the url with `agent-inbox config list`."
            ) from exc

    def auth_call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        session: str | None = None,
    ) -> tuple[int, Any, str | None]:
        """A hub call for the console's auth relay: carries a session cookie and returns
        the response together with any ``Set-Cookie`` the hub issued.

        The console holds no security state of its own — it forwards the human's session
        cookie inward and relays the hub's new cookie back out, and this is the one call
        shape that needs both directions.
        """
        url = f"{self.config.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        if session:
            request.add_header("Cookie", f"{SESSION_COOKIE}={session}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                parsed = json.loads(raw) if raw else None
                return response.status, parsed, response.headers.get("Set-Cookie")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            return exc.code, parsed, None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ClientError(
                f"cannot reach the mailbox at {self.config.base}: {exc}"
            ) from exc

    def _from_response(self, exc: urllib.error.HTTPError) -> ClientError:
        """Turn the hub's own error into ours, keeping what it said.

        The API gives every failure a stable code and a sentence; passing both through
        is the whole point of having them.
        """
        try:
            problem = json.loads(exc.read())
        except ValueError, OSError:
            problem = {}
        detail = problem.get("detail") or exc.reason
        code = problem.get("code")
        return ClientError(f"{detail}" + (f" [{code}]" if code else ""))

    # -- the mailbox -------------------------------------------------------

    def hub_info(self) -> Any:
        return self._call("GET", "/")

    def purge_status(self) -> Any:
        """Whether the hub is actually expiring old mail. Needs no delete rights."""
        return self._call("GET", "/observe/purge/status")

    def remote_doctor(self) -> Any:
        """Ask the hub what it makes of us — credential included, if we have one.

        The half of a diagnosis a client cannot reach on its own: whether the token it
        sent was accepted, revoked or never recognised, and whether the hub has ever
        heard of the name it is using. The route answers rather than refusing, so this
        works precisely when nothing else does.
        """
        return self._call("GET", "/doctor")

    def join(self, name: str | None = None) -> Any:
        """Claim *name*, or this engine's configured name, or one the hub issues.

        Two callers want different things from an empty argument, and the
        difference is the whole of this method. The console calls ``join()`` bare
        at startup to re-claim the name it already has, so the fallback to
        ``self.config.name`` has to stay. The CLI calls it before it has any name
        at all, and its config holds :data:`UNNAMED` — which must *not* go over
        the wire as a claim, or the first engine to join without a name takes
        ``unnamed`` permanently and every engine after it is refused.

        So the placeholder, and only the placeholder, becomes ``None``: the hub
        reads that as "issue one" and draws from the name pool.
        """
        requested = name or self.config.name
        return self._call(
            "POST",
            "/actors",
            {"preferredUsername": None if requested == UNNAMED else requested},
        )

    def list_agents(self) -> Any:
        return self._call("GET", "/actors")

    def whois(self, name: str) -> Any:
        return self._call("GET", f"/actors/{name}")

    def update_profile(self, profile: dict[str, Any]) -> Any:
        return self._call("PUT", f"/actors/{self.config.name}", {"profile": profile})

    def check_inbox(self, view: str = "summary", since: str | None = None) -> Any:
        """What is waiting. ``view`` picks the weight; nothing here consumes.

        ``since`` is a cursor the *caller* holds — the hub keeps no last-seen mark, so
        two sessions sharing one identity cannot hide mail from each other.
        """
        query = f"?view={urllib.parse.quote(view)}"
        if since:
            query += f"&since={urllib.parse.quote(since)}"
        page = self._call("GET", f"/actors/{self.config.name}/inbox{query}")
        if view == "full" or not isinstance(page, dict) or "unread" in page:
            return page
        return _from_older_hub(page, view=view, asked_since=bool(since))

    def send_message(
        self,
        to: str | list[str],
        body: str,
        subject: str | None = None,
        in_reply_to: str | None = None,
    ) -> Any:
        note: dict[str, Any] = {
            "type": "Note",
            "to": [to] if isinstance(to, str) else list(to),
            "content": body,
        }
        if subject:
            note["summary"] = subject
        if in_reply_to:
            note["inReplyTo"] = in_reply_to
        return self._call(
            "POST",
            f"/actors/{self.config.name}/outbox",
            {
                "@context": "https://www.w3.org/ns/activitystreams",
                "type": "Create",
                "object": note,
            },
        )

    def read_message(self, object_id: str) -> Any:
        return self._call("POST", f"/objects/{_leaf(object_id)}/read")

    def peek_message(self, object_id: str) -> Any:
        """One body, without marking it handled. The counterpart of a manifest row."""
        return self._call("GET", f"/objects/{_leaf(object_id)}")

    def reply_message(
        self, object_id: str, body: str, subject: str | None = None
    ) -> Any:
        note: dict[str, Any] = {
            "type": "Note",
            "content": body,
            "inReplyTo": object_id,
        }
        if subject:
            note["summary"] = subject
        return self._call("POST", f"/actors/{self.config.name}/outbox", note)

    def read_thread(self, object_id: str) -> Any:
        return self._call("GET", f"/objects/{_leaf(object_id)}/thread")

    # -- observation -------------------------------------------------------
    def search(
        self,
        q: str,
        *,
        sender: str = "",
        since: str = "",
        until: str = "",
        limit: int = 0,
    ) -> Any:
        """Find mail this identity is party to. Consumes nothing.

        Every parameter is passed straight through and **nothing is filtered here**. A
        client that received more than it should have and tidied it away locally would
        be a disclosure with a cosmetic fix — the hub decides, always (ADR 0005).
        """
        query = f"?q={urllib.parse.quote(q)}"
        for name, value in (("sender", sender), ("since", since), ("until", until)):
            if value:
                query += f"&{name}={urllib.parse.quote(value)}"
        if limit:
            query += f"&limit={int(limit)}"
        return self._call("GET", f"/actors/{self.config.name}/search{query}")

    #
    # The operator's view. These do not send this client's name as anyone's identity —
    # they read the hub's `/observe/*` routes, which take no caller. That is the whole
    # difference from the methods above: the console used to `check_inbox` *as* the
    # agent it wanted to look at, and that impersonation is what this replaces.

    def survey(self, since: str = "") -> Any:
        query = f"?since={urllib.parse.quote(since)}" if since else ""
        return self._call("GET", f"/observe/stats{query}")

    def observe_mailbox(self, name: str) -> Any:
        return self._call("GET", f"/observe/mailbox/{name}")

    def observe_outbox(self, name: str) -> Any:
        """What one agent sent — the other half of :meth:`observe_mailbox`."""
        return self._call("GET", f"/observe/outbox/{name}")

    def observe_recent(self, limit: int | None = None) -> Any:
        """The hub's recent traffic, so a live view can open full rather than blank.

        `limit` is a request, not an instruction: the hub clamps it, because an
        unbounded "recent" is a whole-store dump wearing a small name. Omit it and the
        hub's own default applies — which is what a caller should normally do, so this
        client is not a second place the number lives.
        """
        query = f"?limit={int(limit)}" if limit is not None else ""
        return self._call("GET", f"/observe/recent{query}")

    def observe_object(self, object_id: str) -> Any:
        return self._call("GET", f"/observe/objects/{_leaf(object_id)}")

    def observe_thread(self, object_id: str) -> Any:
        return self._call("GET", f"/observe/objects/{_leaf(object_id)}/thread")

    def role_definition(self, role: str) -> Any:
        """What a role means, according to the hub.

        Definitions live on the hub rather than in one prompt page per role. Separate
        pages drift — out of step with each other and with the code — and changing what
        a role means should not require re-onboarding anyone who holds it.

        A standing resident's profile *is* the definition of its role, which is why this
        reads the directory rather than needing a new concept.
        """
        try:
            actor = self.whois(role)
        except ClientError:
            return {
                "role": role,
                "known": False,
                "note": (
                    f"the hub has no definition for {role!r}. It is still a fine label "
                    "for what you do here; it simply carries no special meaning."
                ),
            }
        return {
            "role": role,
            "known": True,
            "definition": actor.get("summary"),
            "profile": actor.get("profile"),
        }

    def ping(self) -> Any:
        """Prove the whole path: config, network, hub, and that we are known to it."""
        info = self.hub_info()
        me = self._call("GET", f"/actors/{self.config.name}")
        return {
            "ok": True,
            "hub": info.get("name"),
            "version": info.get("version"),
            "you": me.get("preferredUsername"),
            "authenticated": info.get("authenticated", False),
        }


def _leaf(value: str) -> str:
    """Accept a full object URI or a bare id — an agent will have either."""
    return value.rstrip("/").rsplit("/", 1)[-1]


# -- the event stream ------------------------------------------------------------
#
# A hub can hold a connection open and say when mail arrives, so a client need not ask
# repeatedly. Two pieces live here: the framing, which is pure and testable without a
# socket, and the two details a caller needs to open the connection at all. What holds
# the connection is *not* here — that is the MCP server, which is the only client
# process with a lifetime long enough (see `mcp_client`).


@dataclass(frozen=True, slots=True)
class SseEvent:
    """One complete server-sent event: its name, its payload, and its id.

    The wire is the contract, deliberately. Decoding `data` into some client-side type
    here would put a second definition of the event next to the hub's, and the two would
    drift the first time a field was added.
    """

    event: str
    data: str
    id: str | None = None


class SseParser:
    """Server-sent event framing, fed a chunk at a time.

    Incremental because the transport is: a read returns whatever arrived, which may be
    half a line, several events, or a keep-alive comment on its own. A parser that
    assumed one event per read would mis-frame the first time a packet split, which is
    exactly the case nobody tests by hand.

    The details that a naive `for line in response` gets wrong, and that this handles:

      * **comments** — a line beginning with `:` carries no event. Idle hubs send one
      every fifteen seconds to stop a proxy closing the connection, so this is the
      *most* common line on a quiet stream, not an edge case;
    * **multi-line data** — successive `data:` lines are one payload joined by newlines,
      not several events;
    * **the blank line** — which is what dispatches an event. Fields accumulate until
      then, so an event split across two reads still arrives whole;
    * **`\\r\\n`**, which is what the hub actually sends.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._data: list[str] = []
        self._event = "message"
        self._id: str | None = None

    def feed(self, chunk: str) -> list[SseEvent]:
        """Everything that became complete because of this chunk. Often nothing."""
        self._buffer += chunk
        events: list[SseEvent] = []
        while "\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition("\n")
            done = self._line(line.rstrip("\r"))
            if done is not None:
                events.append(done)
        return events

    def _line(self, line: str) -> SseEvent | None:
        if line.startswith(":"):
            return None  # a comment; the keep-alive arrives as one
        if not line:
            if not self._data:
                # A blank line with nothing accumulated dispatches nothing. Two in a row
                # are legal and mean nothing happened.
                self._event, self._id = "message", None
                return None
            event = SseEvent(self._event, "\n".join(self._data), self._id)
            self._data, self._event, self._id = [], "message", None
            return event
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            self._data.append(value)
        elif field == "event":
            self._event = value
        elif field == "id":
            self._id = value
        # Any other field is ignored rather than refused, which is what the format asks
        # for and what lets the hub add one without breaking a client that predates it.
        return None
