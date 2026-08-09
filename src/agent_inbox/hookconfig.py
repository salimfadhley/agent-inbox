"""Install and remove the wake hooks in ``.claude/settings.json``, safely.

The dangerous part of "auto-configure" is other people's config: a writer that replaces
the file, or an event's hook list, evicts hooks the user (or another tool) put there. So
the merge is careful — pure functions transform the settings dict, adding only our own
entries and, on uninstall, removing *only* ours (identified by the ``wake-check``
command). Re-install is idempotent (it strips ours first), and the write is atomic.
"""

import json
import shlex
import sys
from pathlib import Path
from typing import Any

#: Our hook entries are the ones whose command runs this subcommand.
#:
#: Deliberately the *subcommand* and not the program: the program has changed once
#: already (see :func:`default_command`), and a marker naming it would have orphaned
#: every hook installed before that change — leaving them un-uninstallable and doubling
#: on the next install.
_MARKER = "wake-check"

#: The three events we hook. SessionStart/UserPromptSubmit inject context; Stop wakes.
EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")

#: A per-hook timeout (seconds). wake-check is fail-silent and fast; this is a backstop.
_TIMEOUT = 10

#: The opt-in asyncRewake Stop hook is a real waiter, not a one-shot check.
#:
#: The interval is the **floor**, not the whole story: the waiter holds the hub's event
#: stream and polls underneath it, lengthening this while a connection is actually open.
#: What it fixes is the unstreamed case — a hub too old for the route, or a network that
#: will not hold a connection — which must keep waking at the speed it always did.
_REWAKE_TIMEOUT = 8 * 60 * 60
_REWAKE_POLL_INTERVAL = 5


def _is_ours(hook: Any) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and _MARKER in str(hook.get("command", ""))
    )


def strip(settings: dict[str, Any]) -> dict[str, Any]:
    """Return ``settings`` with only our wake hooks removed; everything else intact."""
    out = json.loads(json.dumps(settings))  # deep copy, JSON-safe by construction
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            inner = [h for h in group.get("hooks", []) if not _is_ours(h)]
            if inner:
                group = {**group, "hooks": inner}
                kept_groups.append(group)
            elif "hooks" not in group:
                kept_groups.append(group)  # a group with no hooks list — leave it
            # else: the group held only our hook(s) → drop it
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        out.pop("hooks", None)
    return out


def apply(
    settings: dict[str, Any], command: str, *, rewake: bool = False
) -> dict[str, Any]:
    """Return ``settings`` with our wake hooks added (idempotent — ours are replaced).

    ``command`` is the base command (e.g. ``agent-inbox wake-check``); each event
    appends ``--event <Event>``. ``rewake`` adds the async/asyncRewake options to the
    Stop hook, the opt-in "wake a fully idle session" path.
    """
    out = strip(settings)  # never double-install
    hooks = out.setdefault("hooks", {})
    for event in EVENTS:
        hook_command = f"{command} --event {event}"
        timeout = _TIMEOUT
        entry: dict[str, Any] = {
            "type": "command",
            "command": hook_command,
            "timeout": timeout,
        }
        if event == "Stop" and rewake:
            entry["command"] = (
                f"{hook_command} --wait --poll-interval {_REWAKE_POLL_INTERVAL} "
                f"--wait-timeout {_REWAKE_TIMEOUT}"
            )
            entry["timeout"] = _REWAKE_TIMEOUT + _TIMEOUT
            entry["async"] = True
            entry["asyncRewake"] = True
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):  # defend against a malformed existing value
            groups = []
            hooks[event] = groups
        groups.append({"hooks": [entry]})
    return out


# -- file I/O --------------------------------------------------------------


#: Harnesses whose waking mechanism we know how to install.
#:
#: **A harness absent from this is not a failure to install — it is a reason to say
#: so.**
#: Until 2026-08-09 `install-hook` wrote `.claude/settings.json` unconditionally and
#: reported success, whatever harness it was run under. The onboarding prompt promised
#: the opposite in as many words: *"where a harness has no such mechanism the command
#: says so and costs you nothing."* It did not say so. It wrote a file nothing read and
#: told the agent it was being woken.
#:
#: `aurelia_saahaa` was the first agent positioned to hit that, on opencode.
SUPPORTED_HARNESSES: frozenset[str] = frozenset({"claude", "opencode"})


def plugin_path(root: Path) -> Path:
    """Where opencode loads a project's plugins from.

    `.opencode/plugins/` is auto-loaded at startup, which makes it the direct analogue
    of `.claude/settings.json` — a file in a known place, read by the harness, needing
    no registration step.
    """
    return root / ".opencode" / "plugins" / "agent-inbox-wake.js"


def opencode_plugin(command: str) -> str:
    """The plugin source: subscribe to idle, run *our* waiter, deliver what it says.

    **Thin on purpose, and it must stay thin.** `session.idle` is opencode's analogue of
    Claude Code's `Stop`, and everything that makes waiting work — holding the hub's
    event stream, the polling floor beneath it, the announce-once watermark, the re-arm
    when the clock runs out — already exists in `wake.py` and is harness-agnostic. What
    differs between harnesses is only *who calls the waiter* and *what they do with exit
    2*. A second implementation of the waiting logic in JavaScript is the failure this
    shape exists to avoid.

    **The notice is what the waiter wrote, unaltered.** On Claude Code exit-2 stderr is
    visibly machine output; here it lands as a message in the conversation, in the
    human's voice. So it must be unmistakably from the mailbox and must never carry a
    message *body* — `wake._notice` already emits sender and subject only, and that is
    the reason this passes its text through rather than composing any of its own.
    Injecting mail content as a prompt would let any peer drive somebody else's agent,
    which is ADR 0008 broken at the root.

    One waiter at a time per session: idle can fire again while the previous is held,
    and two waiters would announce the same arrival twice.
    """
    return f"""// Installed by `agent-inbox install-hook`. Safe to delete;
// re-run the command to restore it.
//
// Waking, for opencode. `session.idle` is this harness's `Stop`: it fires when the
// agent goes quiet. We then run the mailbox's own waiter, which holds the hub's event
// stream and returns the moment something arrives — or re-arms when its clock runs out.
//
// Exit 2 means "there is mail, and here is who it is from" on stderr. That text is
// passed through unchanged: it names senders and subjects and never a message body,
// because a message arriving here reads as though your human said it.
export const AgentInboxWake = async ({{ client, $ }}) => {{
  let holding = false
  return {{
    event: async ({{ event }}) => {{
      if (event?.type !== "session.idle") return
      if (holding) return
      holding = true
      try {{
        const args = `--event Stop --wait --poll-interval 5 --wait-timeout 28800`
        const run = await $`{command} ${{args}}`
          .nothrow()
          .quiet()
        const said = String(run.stderr ?? "").trim()
        if (run.exitCode === 2 && said) {{
          await client.session.prompt({{
            path: {{ id: event.properties.sessionID }},
            body: {{ parts: [{{ type: "text", text: said }}] }},
          }})
        }}
      }} finally {{
        holding = false
      }}
    }},
  }}
}}
"""


def settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON; fix or remove it first") from exc


def _write(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def default_command() -> str:
    """How to run `wake-check`, without going through the `agent-inbox` launcher.

    **This is the Windows upgrade bug, and it is ours.** On Windows a running `.exe`
    cannot be overwritten, and `uv tool install --force` has to replace the launcher at
    `~/.local/bin/agent-inbox.exe`. Installing this hook as `agent-inbox wake-check`
    started that launcher on *every turn of every session*, so the file was reliably in
    use and every upgrade ended in::

        error: Failed to install entrypoint
          Caused by: ... The process cannot access the file because it is being used by
          another process. (os error 32)

    Reported by the owner on 2026-08-07 upgrading 0.83.0 to 0.87.0, with the
    observation that makes the fix obvious: **the launcher never actually changes
    between releases.** It is a generic stub holding an interpreter path and an entry
    point, both identical from one version to the next. uv copies it anyway, and the
    copy is what fails. Nothing was wrong with the upgrade.

    So run the interpreter directly. `sys.executable` is the environment agent-inbox is
    installed into — the uv tool venv, or a project venv from source — and it is the one
    that can import `agent_inbox`. It was measured during the MCP work that
    `uv tool install --force` leaves that interpreter unchanged by inode, so holding
    *it* open across an upgrade costs nothing.

    The same reasoning already moved the MCP server to `python -m agent_inbox mcp`; this
    is the other invocation we make on somebody's behalf, and it was missed because it
    is installed once and never seen again.

    Quoted with `shlex`, because the path is not ours and a uv tool directory can sit
    under a directory with a space in it.
    """
    return f"{shlex.quote(sys.executable)} -m agent_inbox wake-check"


class NoWakingHere(Exception):
    """This harness has no mechanism we can install into, and saying so is the point.

    Raised rather than returned, and never swallowed by the caller, because the whole
    defect being fixed is that the absence used to be *silent*: a file was written, a
    success reported, and the agent went on believing it would be woken.
    """


def install_for(
    harness: str | None, root: Path, command: str | None = None, *, rewake: bool = False
) -> Path:
    """Install waking for the harness actually running, or refuse and say why.

    `harness` is what `client.detect_engine` reported — `None` when it could not tell,
    which is a legitimate answer and must not be papered over with a guess. Guessing
    here writes a file the harness never reads and tells somebody they are reachable.
    """
    if harness == "claude":
        return install(root, command, rewake=rewake)
    if harness == "opencode":
        return install_opencode(root, command)
    raise NoWakingHere(
        f"{harness or 'this harness'} has no waking mechanism I know how to install. "
        "Nothing has been written. Keep checking your inbox at the start of a turn — "
        "that always works, and is what every agent did before hooks existed."
    )


def install_opencode(root: Path, command: str | None = None) -> Path:
    """Write the opencode plugin. Idempotent — the file is replaced, not appended to.

    Unlike `.claude/settings.json`, this file is ours entirely: opencode loads every
    plugin in the directory, so there is nothing of anybody else's to merge with and
    nothing to strip. Overwriting is the whole operation.
    """
    path = plugin_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(opencode_plugin(command or default_command()), encoding="utf-8")
    tmp.replace(path)
    return path


def uninstall_opencode(root: Path) -> Path:
    """Remove the plugin. Absent is success — this is how uninstall is called twice."""
    path = plugin_path(root)
    path.unlink(missing_ok=True)
    return path


def install(root: Path, command: str | None = None, *, rewake: bool = False) -> Path:
    """Merge the wake hooks into ``root/.claude/settings.json``. Idempotent.

    Re-running this **migrates** an older hook: `apply` strips every entry carrying the
    marker before adding ours, and the marker is the subcommand rather than the program,
    so a hook installed as `agent-inbox wake-check` is replaced rather than duplicated.
    """
    path = settings_path(root)
    _write(path, apply(_read(path), command or default_command(), rewake=rewake))
    return path


def uninstall(root: Path) -> Path:
    """Remove exactly our wake hooks from ``root/.claude/settings.json``."""
    path = settings_path(root)
    if path.exists():
        _write(path, strip(_read(path)))
    return path
