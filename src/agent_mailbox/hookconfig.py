"""Install and remove the wake hooks in ``.claude/settings.json``, safely.

The dangerous part of "auto-configure" is other people's config: a writer that replaces
the file, or an event's hook list, evicts hooks the user (or another tool) put there. So
the merge is careful — pure functions transform the settings dict, adding only our own
entries and, on uninstall, removing *only* ours (identified by the ``wake-check``
command). Re-install is idempotent (it strips ours first), and the write is atomic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Our hook entries are the ones whose command runs this subcommand.
_MARKER = "wake-check"

#: The three events we hook. SessionStart/UserPromptSubmit inject context; Stop wakes.
EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")

#: A per-hook timeout (seconds). wake-check is fail-silent and fast; this is a backstop.
_TIMEOUT = 10


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

    ``command`` is the base command (e.g. ``agent-mailbox wake-check``); each event
    appends ``--event <Event>``. ``rewake`` adds the async/asyncRewake options to the
    Stop hook, the opt-in "wake a fully idle session" path.
    """
    out = strip(settings)  # never double-install
    hooks = out.setdefault("hooks", {})
    for event in EVENTS:
        entry: dict[str, Any] = {
            "type": "command",
            "command": f"{command} --event {event}",
            "timeout": _TIMEOUT,
        }
        if event == "Stop" and rewake:
            entry["async"] = True
            entry["asyncRewake"] = True
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):  # defend against a malformed existing value
            groups = []
            hooks[event] = groups
        groups.append({"hooks": [entry]})
    return out


# -- file I/O --------------------------------------------------------------


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


def install(
    root: Path, command: str = "agent-mailbox wake-check", *, rewake: bool = False
) -> Path:
    """Merge the wake hooks into ``root/.claude/settings.json``. Idempotent."""
    path = settings_path(root)
    _write(path, apply(_read(path), command, rewake=rewake))
    return path


def uninstall(root: Path) -> Path:
    """Remove exactly our wake hooks from ``root/.claude/settings.json``."""
    path = settings_path(root)
    if path.exists():
        _write(path, strip(_read(path)))
    return path
