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

from __future__ import annotations

import json
import os
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_NAME = "agent-mailbox.toml"
IDENTITY_HEADER = "X-Agent-Name"

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


def write_global(settings: dict[str, str], env: dict[str, str] | None = None) -> Path:
    """Merge *settings* into the machine-wide file, creating it if need be.

    Merging, never replacing: the file may already hold a hub for another deployment,
    and a tool that silently discarded it would be worse than one that never wrote at
    all. Written 0600 — it holds a credential, and the default umask does not.
    """
    path = global_config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_global(env)
    data.update(settings)
    lines = [
        "# agent-inbox — machine-wide settings, written by `agent-inbox configure`.",
        "# A shared token belongs here: it admits this machine, whatever project an",
        "# agent is working in. Identity stays per project, in agent-mailbox.toml.",
        "",
        *(f"{key} = {_toml_str(str(value))}" for key, value in sorted(data.items())),
        "",
    ]
    path.write_text("\n".join(lines))
    path.chmod(0o600)
    return path


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
    """
    environ = env if env is not None else dict(os.environ)
    engine = engine or detect_engine(environ) or "default"
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
    data = load_global(env)
    if name not in data:
        return False
    del data[name]
    path = global_config_path(env)
    lines = [
        "# agent-inbox — machine-wide settings, written by `agent-inbox config`.",
        "# A shared token belongs here: it admits this machine, whatever project an",
        "# agent is working in. Identity stays per project, in agent-mailbox.toml.",
        "",
        *(f"{key} = {_toml_str(str(value))}" for key, value in sorted(data.items())),
        "",
    ]
    path.write_text("\n".join(lines))
    path.chmod(0o600)
    return True


def unset_project(
    name: str,
    start: Path | None = None,
    env: dict[str, str] | None = None,
    engine: str | None = None,
) -> bool:
    """Remove one setting from one engine's entry. True if it was there."""
    environ = env if env is not None else dict(os.environ)
    engine = engine or detect_engine(environ) or "default"
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

    for key, var in (
        ("hub", "AGENT_MAILBOX_HUB"),
        ("name", "AGENT_MAILBOX_NAME"),
        ("role", "AGENT_MAILBOX_ROLE"),
        ("token", "AGENT_MAILBOX_TOKEN"),
    ):
        if value := environ.get(var, "").strip():
            found[key] = (value, var)
    return found


def load_global(env: dict[str, str] | None = None) -> dict[str, Any]:
    """The machine-wide file, or an empty mapping. Never raises for absence."""
    path = global_config_path(env)
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


#: What a config holds before this engine has a name — the CLI and the MCP client both
#: need *something* in the identity header to make their very first call. It is a
#: placeholder, never a claim: `join` translates it back to "issue me one" so the first
#: engine to join without a name cannot squat it and lock everyone else out.
UNNAMED = "unnamed"

#: Must match the hub's cookie name (agent_mailbox.api.SESSION_COOKIE). Defined here too
#: so the stdlib client stays free of any dependency on the Litestar app module.
SESSION_COOKIE = "agent_mailbox_session"
DEFAULT_TIMEOUT = 10.0

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
    # pass --engine and set AGENT_MAILBOX_* by hand for every command. Detection that
    # only works on some installs is worse than none, because the failure is a wrong
    # identity rather than an honest "I do not know".
    ("CODEX_THREAD_ID", "codex"),
    ("CODEX_MANAGED_BY_NPM", "codex"),
    ("CODEX_CI", "codex"),
    ("GEMINI_CLI", "gemini"),
    ("CURSOR_TRACE_ID", "cursor"),
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
    #: A device token minted by an operator. When set, it is sent as a bearer credential
    #: and is how the hub authenticates this agent once auth is enforced.
    token: str | None = None

    @property
    def base(self) -> str:
        return self.hub.rstrip("/")


def find_config(start: Path | None = None) -> Path | None:
    """Look for ``agent-mailbox.toml`` here and upwards, stopping at a repository root.

    Stopping at the boundary is deliberate: walking further would let one project
    silently adopt a sibling's identity.
    """
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_NAME
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
    if from_env := environ.get("AGENT_MAILBOX_HUB", "").strip():
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
    except (OSError, tomllib.TOMLDecodeError):
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
    except (OSError, tomllib.TOMLDecodeError):
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
    hub = environ.get("AGENT_MAILBOX_HUB", "").strip()
    name = environ.get("AGENT_MAILBOX_NAME", "").strip()
    role = environ.get("AGENT_MAILBOX_ROLE", "").strip()
    token = environ.get("AGENT_MAILBOX_TOKEN", "").strip()
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
            "Or set AGENT_MAILBOX_HUB and AGENT_MAILBOX_NAME. If you have no name yet, "
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
    """
    target = project_root(start) / CONFIG_NAME
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

    return _render_project(target, str(existing.get("hub") or hub), agents)


def _render_project(target: Path, hub: str, agents: dict[str, Any]) -> Path:
    """Write the project file. One renderer, so `join` and `configure` cannot drift."""
    lines = [
        "# agent-inbox — where the mailbox is, and who each agent here is on it.",
        "# Written by `join` and `agent-inbox configure`, one entry per engine. Do not",
        "# commit it: it names a deployment and may carry a device token. Do not",
        "# hand-edit it either — `configure` knows where every setting belongs.",
        "",
        f"hub = {_toml_str(hub)}",
        "",
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
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


class HubClient:
    """One hub, over HTTP.

    Deliberately uses the standard library. A client that an agent installs should not
    drag a dependency tree behind it, and this is a dozen requests with no streaming.
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

    # -- plumbing ----------------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header(IDENTITY_HEADER, self.config.name)
        # A device token, when we have one, is how the hub authenticates us once auth is
        # enforced. The identity header stays too, and is simply ignored under enforce.
        if self.config.token:
            request.add_header("Authorization", f"Bearer {self.config.token}")
        if self.session:
            request.add_header("Cookie", f"{SESSION_COOKIE}={self.session}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise self._from_response(exc) from exc
        except urllib.error.URLError as exc:
            raise ClientError(
                f"cannot reach the mailbox at {self.config.base} ({exc.reason}). "
                "Check the hub is running and the url is right."
            ) from exc
        except TimeoutError as exc:
            raise ClientError(
                f"the mailbox at {self.config.base} did not answer within "
                f"{self.timeout:g}s. It may be starting up or unreachable."
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
        except (ValueError, OSError):
            problem = {}
        detail = problem.get("detail") or exc.reason
        code = problem.get("code")
        return ClientError(f"{detail}" + (f" [{code}]" if code else ""))

    # -- the mailbox -------------------------------------------------------

    def hub_info(self) -> Any:
        return self._call("GET", "/")

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
        return self._call("GET", f"/actors/{self.config.name}/inbox{query}")

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
