"""The client side of push: notice new mail at the moments Claude Code will act.

Run as a Claude Code hook, ``agent-inbox wake-check --event <Event>`` turns "what is
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
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_inbox.client import HubClient, load_config, project_root

#: Where the announce-once watermark lives — one file per project, beside the config.
WATERMARK_NAME = ".agent-mailbox-seen.json"

#: A per-project guard so an asyncRewake Stop hook does not spawn many pollers.
LOCK_NAME = ".agent-mailbox-wake.lock"

#: How many senders to name before collapsing the rest into "+N more".
_MAX_LISTED = 5

#: A short timeout: the hook runs on every turn, so it must never hang one.
_TIMEOUT = 3.0

#: Defaults for the opt-in asyncRewake waiter.
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_WAIT_TIMEOUT = 8 * 60 * 60.0

#: The events we serve. Stop is the exit-2 "keep going"; the others inject context.
_INJECT_EVENTS = ("SessionStart", "UserPromptSubmit")

Sleeper = Callable[[float], None]


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


def _fetch_unread(root: Path) -> list[dict[str, Any]]:
    config = load_config(start=root)
    unread = HubClient(config, timeout=_TIMEOUT).check_inbox().get("items", [])
    return list(unread)


def _emit(result: WakeResult) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)


def _run_once(event: str, root: Path) -> int:
    result = wake_response(event, _fetch_unread(root), _load_seen(root))
    _save_seen(root, result.seen)
    _emit(result)
    return result.exit_code


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_data(path: Path) -> tuple[int, float] | None:
    try:
        data = json.loads(path.read_text())
        return int(data["pid"]), float(data["created"])
    except OSError, ValueError, KeyError, TypeError, json.JSONDecodeError:
        return None


def _lock_stale(path: Path, *, max_age: float) -> bool:
    data = _lock_data(path)
    if data is None:
        return True
    pid, created = data
    return not _pid_alive(pid) or time.time() - created > max_age


def _acquire_lock(path: Path, *, max_age: float) -> bool:
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not _lock_stale(path, max_age=max_age):
                return False
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return False
            continue
        except OSError:
            return False

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created": time.time()}, handle)
        return True
    return False


def _release_lock(path: Path) -> None:
    data = _lock_data(path)
    if data is None or data[0] != os.getpid():
        return
    try:
        path.unlink()
    except OSError:
        pass


@contextmanager
def _single_waiter(root: Path, *, max_age: float) -> Iterator[bool]:
    path = root / LOCK_NAME
    acquired = _acquire_lock(path, max_age=max_age)
    try:
        yield acquired
    finally:
        if acquired:
            _release_lock(path)


def _wait_for_wake(
    event: str,
    root: Path,
    *,
    poll_interval: float,
    wait_timeout: float,
    sleep: Sleeper,
) -> int:
    poll_interval = max(0.1, poll_interval)
    wait_timeout = max(0.0, wait_timeout)
    deadline = time.monotonic() + wait_timeout
    with _single_waiter(root, max_age=wait_timeout + 60.0) as acquired:
        if not acquired:
            return 0
        while True:
            try:
                code = _run_once(event, root)
            except Exception:  # noqa: BLE001 - a blip must not end an 8-hour wait
                # The one-shot hook may fail silently and be retried next turn. A
                # waiter has no next turn: it *is* the thing keeping an idle session
                # reachable, so dying here means no wake until a human intervenes, with
                # nothing said. The hub being briefly unreachable is the normal case —
                # it is restarted on every deploy — so treat it as "nothing waiting"
                # and poll again. A permanently dead hub costs one request per
                # interval and recovers by itself the moment it returns.
                code = 0
            if code != 0:
                return code
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0
            sleep(min(poll_interval, remaining))


def run(
    event: str,
    *,
    root: Path | None = None,
    wait: bool = False,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    sleep: Sleeper = time.sleep,
) -> int:
    """Execute a wake-check for ``event``. Prints and returns an exit code.

    Wrapped so that **any** failure — hub down, unconfigured, corrupt state, a bug —
    prints nothing and exits 0. A hook that runs on every turn must never break, hang,
    or slow one; the mailbox stays the durable record, so a missed wake only means the
    agent learns on its next poll (NFR-004).
    """
    try:
        base = root or project_root()
        if wait:
            return _wait_for_wake(
                event,
                base,
                poll_interval=poll_interval,
                wait_timeout=wait_timeout,
                sleep=sleep,
            )
        return _run_once(event, base)
    except Exception:  # noqa: BLE001 - fail-silent is the whole contract here
        return 0
