"""Install and remove the wake hooks in ``.claude/settings.json``, safely.

The dangerous part of "auto-configure" is other people's config: a writer that replaces
the file, or an event's hook list, evicts hooks the user (or another tool) put there. So
the merge is careful — pure functions transform the settings dict, adding only our own
entries and, on uninstall, removing *only* ours (identified by the ``wake-check``
command). Re-install is idempotent (it strips ours first), and the write is atomic.
"""

import json
import logging
import os
import shlex
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
SUPPORTED_HARNESSES: frozenset[str] = frozenset({"claude", "opencode", "omp", "codex"})

#: **Codex gets no held waiter, at any length** (#73). Codex runs a Stop hook
#: synchronously — only a synchronous hook may continue the turn — so a hook that
#: waits holds the *whole session*: the session shows "Working", and what the human
#: types next is queued until the hook returns or they press Esc. v1.6.0 shipped a
#: ten-minute hold and a Codex user on Windows met exactly that, pressing Esc before
#: every follow-up for five minutes at a time. Claude Code's eight-hour hold is only
#: tolerable because it is asynchronous there; there is no asynchronous hook on Codex
#: that may continue a turn, so the honest answer is not a shorter hold but none.
#:
#: What Codex keeps is the quick check at every boundary, which is a real wake for the
#: case that matters most: mail that arrives *during* a turn is delivered the moment
#: that turn ends, without the human saying anything.
CODEX_NO_HOLD_NOTE = (
    "Codex has no way to wait for mail without blocking your session: its Stop hook "
    "is synchronous, so a waiting hook queues whatever you type next until it ends. "
    "So these hooks only look — at session start, before each prompt, and when a turn "
    "ends. Mail that arrives while you work reaches you as soon as that turn is over; "
    "mail that arrives while you sit idle reaches you at your next prompt."
)

#: What `install-hook` must say on Codex, every time. Codex runs only hooks a human has
#: approved in its `/hooks` screen; a hook that is written is not yet a hook that runs.
CODEX_TRUST_NOTE = (
    "Codex runs a hook only once a person has trusted it: open Codex in this project, "
    "run /hooks, and trust the agent-inbox entries. Until then they are written, not "
    "running. Re-running install-hook keeps them byte-identical, so that trust holds."
)


def codex_hooks_path(root: Path) -> Path:
    """Codex's project-layer hook file (`docs/config.md`, "Lifecycle hooks")."""
    return root / ".codex" / "hooks.json"


def codex_apply(
    settings: dict[str, Any], command: str, *, rewake: bool = False
) -> dict[str, Any]:
    """Return ``settings`` with our hooks added, in Codex's `hooks.json` shape.

    The shape is Claude Code's — `hooks` → event → groups → `hooks` list of commands —
    and so is the Stop contract: exit 2 with the notice on stderr becomes the next
    turn's prompt. Every hook carries a `statusMessage`, because Codex shows one while
    a hook runs.

    **Every hook here returns at once, and `rewake` cannot change that** — see
    :data:`CODEX_NO_HOLD_NOTE`. The parameter is accepted so that one caller may pass
    it to every harness, and deliberately ignored; the caller reports that.

    **Byte-identical on reinstall, by construction.** Codex trusts a hook by a hash of
    its identity — event, command, timeout — recorded when a human approves it. A
    reinstall that rendered anything differently would un-trust it silently.
    """
    out = strip(settings)
    hooks = out.setdefault("hooks", {})
    for event in EVENTS:
        hook_command = f"{command} --event {event}"
        entry: dict[str, Any] = {
            "type": "command",
            "command": hook_command,
            "timeout": _TIMEOUT,
            "statusMessage": "agent-inbox: checking for mail",
        }
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            groups = []
            hooks[event] = groups
        groups.append({"hooks": [entry]})
    return out


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


def omp_extension_path(root: Path) -> Path:
    """Where omp (oh-my-pi) auto-loads a project's extensions from.

    `<cwd>/.omp/extensions/` is scanned at startup for `.ts` and `.js`, cwd-only with
    no ancestor walk (`docs/extension-loading.md`) — the same shape as
    `.opencode/plugins/`, and for the same reason the analogue of
    `.claude/settings.json`.
    """
    return root / ".omp" / "extensions" / "agent-inbox-wake.js"


def omp_extension(command: str) -> str:
    """The extension source: arm *our* waiter when the agent goes quiet, deliver on 2.

    **The same shape as the opencode plugin, and thin for the same reason** — see
    `opencode_plugin`. What differs is the harness's primitive, and omp's is stronger.
    `pi.sendMessage(text, {{ deliverAs: "followUp", triggerTurn: true }})` starts a turn
    on an *idle* session: an omp agent whose human has walked away is woken, which
    Claude Code's blocking `Stop` hook cannot do. `followUp` — never the default
    `steer`, which interrupts a running agent — is what keeps the prompt's promise that
    *waking is not interrupting*: a notice that lands mid-run waits for the run to end.

    **Extensions run in-process with no isolation** (`docs/extensions.md`). A raw timer
    or detached promise that throws is an `uncaughtException` and tears down the whole
    session. So the waiter is deferred through `ctx.setTimeout` — managed: a rejected
    promise is logged, not fatal; `unref`'d; cleared on shutdown — and never awaited
    inside the handler, where an hours-long await would hold every other extension's
    `agent_end` behind it. The child is aborted on `session_shutdown` so no orphan
    waiter outlives its session.

    `attribution` is left to omp's default, which `normalizeCustomMessagePayload`
    sets to `"agent"` — machine output, not the human's voice. The notice text is the
    waiter's, unaltered: sender and subject, never a body (ADR 0008).

    `command` is split into argv here because `pi.exec` takes `(command, args)` and
    spawns without a shell; the platform-aware splitter preserves quoted requirements.
    """
    argv = json.dumps(split_command(command))
    return f"""// Installed by `agent-inbox install-hook`. Safe to delete;
// re-run the command to restore it.
//
// Waking, for omp (oh-my-pi). `agent_end` is this harness's `Stop`: it fires when the
// agent goes quiet. We then run the mailbox's own waiter, which holds the hub's event
// stream and returns the moment something arrives — or re-arms when its clock runs out.
// `session_start` arms it too, so a freshly opened session that has not yet taken a
// turn is reachable as well.
//
// Exit 2 means "there is mail, and here is who it is from" on stderr. That text is
// passed through unchanged: it names senders and subjects and never a message body,
// because a message arriving here lands in your conversation.
//
// `followUp` queues the notice until any running turn ends; `triggerTurn` starts one
// if you are idle. The default, `steer`, would interrupt you mid-run, and is not used.
export default function (pi) {{
  const argv = {argv}
  // `--engine omp` because a process omp starts for us carries no marker at all, and
  // a project with several agents configured would otherwise be unresolvable.
  const args = [
    "--engine", "omp", "--event", "Stop", "--wait",
    "--poll-interval", "5", "--wait-timeout", "28800",
  ]
  let holding = false
  let abort = null

  pi.setLabel("agent-inbox wake")

  const arm = (ctx) => {{
    if (holding) return
    holding = true
    // Deferred, not awaited: extensions share one process with no isolation, and
    // `ctx.setTimeout` is the managed timer whose rejections are logged rather than
    // fatal. Awaiting here would also hold every other extension's handler for hours.
    ctx.setTimeout(async () => {{
      abort = new AbortController()
      try {{
        const run = await pi.exec(
          argv[0], argv.slice(1).concat(args), {{ signal: abort.signal }},
        )
        const said = String(run.stderr ?? "").trim()
        if (run.code === 2 && said && !run.killed) {{
          pi.sendMessage(
            {{ customType: "agent-inbox", content: said, display: true }},
            {{ deliverAs: "followUp", triggerTurn: true }},
          )
        }}
      }} finally {{
        abort = null
        holding = false
      }}
    }}, 0)
  }}

  pi.on("session_start", async (_event, ctx) => arm(ctx))
  pi.on("agent_end", async (_event, ctx) => arm(ctx))
  pi.on("session_shutdown", async () => {{
    if (abort) abort.abort()
  }})
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
    """Keep installed hooks independent of interpreter paths and project environments.

    The requirement is a compatibility floor, not the installing package's version:
    changing the command on every release would invalidate Codex's trusted hash.
    uv resolves the package using its cache; package updates need no hook rewrite.
    `--isolated` ignores active virtualenvs and `--no-project` ignores the host project.
    The Python module avoids holding the Windows agent-inbox.exe launcher open.
    """
    from agent_inbox.staleness import uv_run_command

    return f"{uv_run_command()} wake-check"


#: Characters a path may contain and still be passed to `cmd.exe` bare. Anything else
#: gets double quotes, which `cmd.exe` honours and a bash on Windows honours too.
_WINDOWS_BARE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:\\/._-+~"
)


def quote_for_shell(path: str, *, windows: bool | None = None) -> str:
    """Quote one path for the shell a harness will hand our command to.

    **POSIX quoting broke every hook on Windows** (#71, reported 2026-09-21 from a
    live Codex session: `Hook failed`, exit 1). `shlex.quote` wraps a path in single
    quotes, and Codex on Windows runs a hook through `COMSPEC` — `cmd.exe /C` — to
    which a single quote is an ordinary character: it looked for a program literally
    named `'C:\\Users\\...\\python.exe'` and found none. Verified in
    `hooks/src/engine/command_runner.rs` (`default_shell_command`); PowerShell is not
    the hook shell unless somebody configures one.

    On Windows a path with nothing but ordinary characters goes **bare** — the one
    form every shell there agrees on — and anything else is double-quoted, which
    `cmd.exe` honours and a bash on Windows honours too (backslashes are literal
    inside double quotes in bash, and these paths carry no `\\"`). Never single quotes
    on Windows.

    `windows` is explicit so the Windows rule is testable on any platform.
    """
    on_windows = os.name == "nt" if windows is None else windows
    if not on_windows:
        return shlex.quote(path)
    if path and all(ch in _WINDOWS_BARE for ch in path):
        return path
    return f'"{path}"'


def split_command(command: str, *, windows: bool | None = None) -> list[str]:
    """The argv a shell would build from *command* — the inverse of the above.

    For omp, which spawns argv directly and must be given the pieces (#65). POSIX
    `shlex.split` treats a backslash as an escape, so a Windows path fed to it comes
    out as `C:Usersxpython.exe`; on Windows the split keeps backslashes and strips
    only the double quotes this module adds.
    """
    on_windows = os.name == "nt" if windows is None else windows
    if not on_windows:
        return shlex.split(command)
    tokens = shlex.split(command, posix=False)
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] == '"' else t for t in tokens]


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
    if harness == "omp":
        return install_omp(root, command)
    if harness == "codex":
        return install_codex(root, command, rewake=rewake)
    raise NoWakingHere(
        f"{harness or 'this harness'} has no waking mechanism I know how to install. "
        "Nothing has been written. Keep checking your inbox at the start of a turn — "
        "that always works, and is what every agent did before hooks existed."
    )


def keep_out_of_git(path: Path, root: Path) -> str:
    """Ignore a generated hook, narrowly, and say what happened (#70).

    The file carries the installing machine's interpreter path — on Windows, a path
    under the user's profile — so it is per-machine, and `git add -A` in a project
    that had never thought about it staged it. The rule is anchored to the one file,
    not its directory: `.omp/` may hold extensions a team shares on purpose.

    Best effort and never fatal, as with the identity file: the hook is written and
    working, and a checkout that is not a repository, or a `.gitignore` we may not
    write, costs a safeguard — which `doctor` reports — not the wake.
    """
    from agent_inbox import ignores

    try:
        rule = "/" + path.relative_to(root).as_posix()
        return ignores.ensure_ignored(path, root, rule=rule, note=ignores.HOOK_NOTE)
    except Exception as exc:  # noqa: BLE001 - the hook is installed; this is hygiene
        logger.debug("could not add an ignore rule for %s: %s", path, exc)
        return ""


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
    keep_out_of_git(path, root)
    return path


def uninstall_opencode(root: Path) -> Path:
    """Remove the plugin. Absent is success — this is how uninstall is called twice."""
    path = plugin_path(root)
    path.unlink(missing_ok=True)
    return path


def install_omp(root: Path, command: str | None = None) -> Path:
    """Write the omp extension. Idempotent, entirely ours — see `install_opencode`."""
    path = omp_extension_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(omp_extension(command or default_command()), encoding="utf-8")
    tmp.replace(path)
    keep_out_of_git(path, root)
    return path


def uninstall_omp(root: Path) -> Path:
    """Remove the extension. Absent is success."""
    path = omp_extension_path(root)
    path.unlink(missing_ok=True)
    return path


def install_codex(
    root: Path, command: str | None = None, *, rewake: bool = False
) -> Path:
    """Merge our hooks into ``root/.codex/hooks.json`` and keep the file out of git.

    Merged, not replaced: it is Codex's file and may hold hooks that are not ours.
    Kept ignored as before: custom commands may embed machine-local paths, and
    trust lives in Codex's own state, not in the file's being committed.
    """
    path = codex_hooks_path(root)
    _write(path, codex_apply(_read(path), command or default_command(), rewake=rewake))
    keep_out_of_git(path, root)
    return path


def uninstall_codex(root: Path) -> Path:
    """Remove exactly our hooks from ``root/.codex/hooks.json``. Absent is success."""
    path = codex_hooks_path(root)
    if path.exists():
        _write(path, strip(_read(path)))
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
