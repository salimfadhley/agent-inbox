"""The client side of push: notice new mail at the moments Claude Code will act.

Run as a Claude Code hook, ``agent-mailbox wake-check --event <Event>`` turns "what is
unread for me" into the right response for that hook event:

- **SessionStart** — announce everything waiting, so a fresh session sees it all.
- **UserPromptSubmit** — announce only what is *new* since last time, a per-turn nudge.
- **Stop** — on *new* mail, print a notice to stderr and exit 2, which Claude Code reads
  as "keep going": the agent processes the mail instead of idling. Announce-once means
  this fires once per message and cannot loop.

Everything the hub is asked is `check_inbox` (existing) — the hub gains nothing
harness-specific (charter). The core decision is a **pure function**
(:func:`wake_response`), testable without a network or a live session; :func:`run` is
the thin, totally fail-silent I/O wrapper — a wake must never break, block, or slow a
turn.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_mailbox.client import HubClient, load_config, project_root

#: Where the announce-once watermark lives — one file per project, beside the config.
WATERMARK_NAME = ".agent-mailbox-seen.json"

#: How many senders to name before collapsing the rest into "+N more".
_MAX_LISTED = 5

#: A short timeout: the hook runs on every turn, so it must never hang one.
_TIMEOUT = 3.0

#: The events we serve. Stop is the exit-2 "keep going"; the others inject context.
_INJECT_EVENTS = ("SessionStart", "UserPromptSubmit")


@dataclass(frozen=True, slots=True)
class WakeResult:
    """What a hook invocation should do. Pure output of :func:`wake_response`."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    #: The watermark to persist — the ids now considered announced.
    seen: frozenset[str] = field(default_factory=frozenset)


def _leaf(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _notice(new_notes: list[dict[str, Any]]) -> str:
    """A terse, capped notice — sender + subject, never the body (untrusted; C-004)."""
    total = len(new_notes)
    shown = []
    for note in new_notes[:_MAX_LISTED]:
        sender = _leaf(note.get("attributedTo")) or "someone"
        subject = (note.get("summary") or "(no subject)").strip() or "(no subject)"
        shown.append(f"{sender} {subject!r}")
    more = "" if total <= _MAX_LISTED else f", +{total - _MAX_LISTED} more"
    return (
        f"📬 {total} new: " + ", ".join(shown) + more + " — call check_inbox to read."
    )


def wake_response(
    event: str, unread: list[dict[str, Any]], seen: frozenset[str]
) -> WakeResult:
    """Decide the hook response. Pure: same inputs, same result — no I/O.

    ``unread`` is the list of waiting messages (each a dict with ``id``,
    ``attributedTo``, ``summary``); ``seen`` is the watermark of already-announced ids.
    SessionStart surfaces everything unread; the other events surface only what is new.
    The new watermark is always "everything currently unread", which keeps it bounded
    and announce-once.
    """
    unread_ids = frozenset(_leaf(n.get("id")) for n in unread)
    if event == "SessionStart":
        to_announce = list(unread)  # a fresh session gets the whole picture
    else:
        to_announce = [n for n in unread if _leaf(n.get("id")) not in seen]

    if not to_announce:
        return WakeResult(exit_code=0, seen=unread_ids)

    notice = _notice(to_announce)
    if event == "Stop":
        # exit 2 → Claude Code continues the turn, feeding stderr back to the agent.
        return WakeResult(exit_code=2, stderr=notice, seen=unread_ids)

    # SessionStart / UserPromptSubmit (and any unknown event, safely): inject context.
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event if event in _INJECT_EVENTS else "SessionStart",
            "additionalContext": notice,
        }
    }
    return WakeResult(exit_code=0, stdout=json.dumps(payload), seen=unread_ids)


# -- I/O wrapper: totally fail-silent --------------------------------------


def _load_seen(root: Path) -> frozenset[str]:
    try:
        data = json.loads((root / WATERMARK_NAME).read_text())
        return frozenset(str(x) for x in data.get("seen", []))
    except Exception:  # noqa: BLE001 - a missing/corrupt watermark is "nothing seen"
        return frozenset()


def _save_seen(root: Path, seen: frozenset[str]) -> None:
    try:
        (root / WATERMARK_NAME).write_text(
            json.dumps({"seen": sorted(seen)}), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - never let a watermark write break a turn
        pass


def run(event: str, *, root: Path | None = None) -> int:
    """Execute a wake-check for ``event``. Prints and returns an exit code.

    Wrapped so that **any** failure — hub down, unconfigured, corrupt state, a bug —
    prints nothing and exits 0. A hook that runs on every turn must never break, hang,
    or slow one; the mailbox stays the durable record, so a missed wake only means the
    agent learns on its next poll (NFR-004).
    """
    try:
        base = root or project_root()
        config = load_config(start=base)
        unread = HubClient(config, timeout=_TIMEOUT).check_inbox().get("items", [])
        result = wake_response(event, list(unread), _load_seen(base))
        _save_seen(base, result.seen)
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.exit_code
    except Exception:  # noqa: BLE001 - fail-silent is the whole contract here
        return 0
