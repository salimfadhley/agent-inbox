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
        return str(tomllib.loads(path.read_text()).get("hub", "")).strip()
    return ""


def load_config(start: Path | None = None, env: dict[str, str] | None = None) -> Config:
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
    engine = detect_engine(environ)

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
        elif not entries:
            # A single flat identity, from before this file grew a mapping.
            name = name or str(data.get("name", "")).strip()
            role = role or str(data.get("role", "")).strip()

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
    return Config(hub=hub, name=name, role=role or "agent", engine=engine)


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


def write_config(
    hub: str,
    name: str,
    engine: str,
    role: str = "agent",
    start: Path | None = None,
    force: bool = False,
) -> Path:
    """Add or update **this engine's** entry, leaving every other one alone.

    Merging rather than replacing is the whole point. Several agents work in one
    repository — Claude, Codex, Gemini — and each needs its own identity, because two
    sharing a name would silently share an inbox. A writer that replaced the file would
    evict whoever configured themselves first, and the eviction would be invisible until
    their mail stopped arriving.

    An existing entry for this engine is left as it is unless ``force`` is given:
    changing a name means mail addressed to the old one stops being delivered.
    """
    target = project_root(start) / CONFIG_NAME
    existing: dict[str, Any] = {}
    if target.exists():
        existing = tomllib.loads(target.read_text())

    agents: dict[str, Any] = dict(existing.get("agents") or {})
    if engine in agents and not force:
        held = agents[engine].get("name")
        raise ClientError(
            f"{engine} is already {held!r} on this project (in {target}). "
            "Keep it, or pass force to change it — mail addressed to the old name "
            "stops arriving."
        )
    agents[engine] = {"name": name, "role": role}

    lines = [
        "# agent-mailbox — where the mailbox is, and who each agent here is on it.",
        "# Written by `join`, one entry per engine. Safe to edit; safe to commit",
        "# unless the hub url is private to your deployment.",
        "",
        f'hub = "{existing.get("hub") or hub}"',
        "",
        "# One identity per engine: several agents work in this repository and they",
        "# are different correspondents. Names are permanent and deliberately",
        "# meaningless — do not encode the project or the model into them. What an",
        "# agent *does* here is its role; the rest belongs in `update_profile`.",
    ]
    for key in sorted(agents):
        entry = agents[key]
        lines += [
            "",
            f"[agents.{key}]",
            f'name = "{entry.get("name", "")}"',
            f'role = "{entry.get("role", "agent")}"',
        ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


class HubClient:
    """One hub, over HTTP.

    Deliberately uses the standard library. A client that an agent installs should not
    drag a dependency tree behind it, and this is a dozen requests with no streaming.
    """

    def __init__(self, config: Config, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.config = config
        self.timeout = timeout

    # -- plumbing ----------------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header(IDENTITY_HEADER, self.config.name)
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

    def join(self, name: str | None = None) -> Any:
        return self._call(
            "POST", "/actors", {"preferredUsername": name or self.config.name}
        )

    def list_agents(self) -> Any:
        return self._call("GET", "/actors")

    def whois(self, name: str) -> Any:
        return self._call("GET", f"/actors/{name}")

    def update_profile(self, profile: dict[str, Any]) -> Any:
        return self._call("PUT", f"/actors/{self.config.name}", {"profile": profile})

    def check_inbox(self) -> Any:
        return self._call("GET", f"/actors/{self.config.name}/inbox")

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
