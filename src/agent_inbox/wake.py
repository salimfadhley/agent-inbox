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

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_inbox.backoff import SETTLED_AFTER, reconnect_delay
from agent_inbox.client import HubClient, SseParser, load_config, project_root

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

#: How long the waiter sleeps between polls **while it is holding the event stream**.
#: Five seconds is pointless when the stream will interrupt the sleep in milliseconds,
#: but it cannot become "however long is left" either: a stream that connected and then
#: went silent — a buffering proxy is the ordinary cause — looks exactly like a healthy
#: one from this side, and this poll is the only thing that catches it. A minute is two
#: keep-alive intervals' worth of patience and 480 requests over a full wait instead of
#: 5,760.
STREAMING_POLL_INTERVAL = 60.0

#: How long we will wait to *connect* to the stream. There is deliberately no read
#: timeout below this: a stream is silent precisely when there is no mail, which is most
#: of the time.
_STREAM_CONNECT_TIMEOUT = 10.0

#: The one event type that means "there is mail". Anything else is ignored rather than
#: refused, so the hub can add an event type without waking every deployed client.
_ARRIVAL_EVENT = "mail"

#: Statuses that will never come good by being asked again during one wait. A hub too
#: old to have the route will not grow one inside eight hours, and a credential that was
#: refused will not become valid by repetition. The waiter stops streaming and polls.
_FINAL_STATUSES = frozenset({401, 403, 404, 405})

#: How long `close` waits for the reader thread to notice. It is a daemon thread, so
#: exceeding this delays nothing — the process still exits.
_CLOSE_GRACE = 2.0

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


# -- the event stream: a held connection that can only shorten a sleep ------


def _open_stream(url: str, headers: dict[str, str]) -> Any:
    """Open the stream with the standard library, and nothing else.

    `httpx` — which the MCP server uses for the same job — is in the `clients` extra.
    This runs from the base CLI install, so it gets `urllib`, exactly as the rest of
    `HubClient` does.
    """
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - hub url
    return urllib.request.urlopen(request, timeout=_STREAM_CONNECT_TIMEOUT)  # noqa: S310


class ArrivalStream:
    """The hub's event stream, held on a thread, exposing one bit: *something arrived*.

    **It can only ever shorten a sleep.** That is the whole design. It never decides
    what an agent is told, never reports a failure, and never blocks the loop that uses
    it — so a hub with no event route, a proxy that will not hold a connection, or a bug
    in here leaves the waiter polling exactly as it did before this existed.

    It reads the event's *type* and nothing else. The payload is written by whoever sent
    the message, and giving it a path into printed text would undo the one rule the wake
    mechanism exists under: a wake carries the hub's own account of who sent what, never
    the sender's.
    """

    def __init__(
        self,
        client: HubClient,
        *,
        connect: Callable[[str, dict[str, str]], Any] = _open_stream,
        rand: Callable[[], float] | None = None,
    ) -> None:
        # Address and credential come from the client, once. Assembling them here is how
        # a stream ends up authenticating differently from every other call, months
        # after the change that caused it.
        self._url = client.events_url()
        self._headers = client.stream_headers()
        self._connect = connect
        self._rand = rand
        self._arrived = threading.Event()
        self._stopped = threading.Event()
        self._connected = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: Any = None

    # -- what the waiter uses ----------------------------------------------

    def start(self) -> None:
        """Begin holding the stream. Never raises, whatever happens next."""
        if self._thread is not None:
            return
        thread = threading.Thread(
            target=self._run, name="agent-inbox-wake", daemon=True
        )
        self._thread = thread
        try:
            thread.start()
        except RuntimeError:  # a machine that will not give us a thread; poll instead
            self._thread = None

    def wait(self, seconds: float) -> None:
        """Sleep for `seconds`, or until mail arrives. The waiter's `Sleeper`.

        Signature and behaviour of `time.sleep` when nothing arrives, which is what lets
        it be substituted for one.

        **Cleared only when it was actually observed set.** Clearing unconditionally
        would drop an arrival that landed in the instant between the timeout returning
        and the clear — harmless today, because the caller polls immediately afterwards
        and the hub only announces mail it has already stored, but it would be a real
        lost wake the moment anything came to rely on the flag alone.
        """
        if self._arrived.wait(seconds):
            self._arrived.clear()

    @property
    def connected(self) -> bool:
        """Whether a connection is open *right now*.

        Deliberately not "have we ever connected". The slower poll (FR-006) is only
        justified while something is actually listening; a stream that has dropped and
        is waiting to retry must not also slow the poll that is covering for it.
        """
        return self._connected.is_set()

    def close(self) -> None:
        """Stop reading and let go of the connection. Idempotent, and never raises."""
        self._stopped.set()
        self._shut(self._response)
        thread, self._thread = self._thread, None
        if thread is not None:
            # A bounded join: the thread may be blocked in a read that closing the
            # response does not always interrupt. It is a daemon, so a straggler delays
            # nothing — the process still exits — and waiting longer would turn a
            # closing hook into a slow one.
            thread.join(timeout=_CLOSE_GRACE)

    # -- the thread --------------------------------------------------------

    def _run(self) -> None:
        """Connect, read, reconnect — until told to stop. Silent on every path."""
        attempt = 0
        while not self._stopped.is_set():
            opened_at: float | None = None
            try:
                opened_at = self._read_one_connection()
            except urllib.error.HTTPError as refusal:
                if refusal.code in _FINAL_STATUSES:
                    return  # this hub will not stream to us; the poll is the answer
            except Exception:  # noqa: BLE001 - a lost stream is never the agent's problem
                pass
            finally:
                self._connected.clear()
            # Start over from the shortest delay only if the connection *lasted*. A hub
            # that accepts and immediately drops — a proxy answering 200 and closing —
            # would otherwise be retried about twice a second for the whole wait, with
            # nothing anywhere to say so.
            if opened_at is not None and time.monotonic() - opened_at >= SETTLED_AFTER:
                attempt = 0
            if self._stopped.wait(self._delay(attempt)):
                return
            attempt += 1

    def _delay(self, attempt: int) -> float:
        if self._rand is None:
            return reconnect_delay(attempt)
        return reconnect_delay(attempt, rand=self._rand)

    def _read_one_connection(self) -> float:
        """Hold one connection until it ends. Returns when it opened, for the
        backoff to judge whether it lasted."""
        response = self._connect(self._url, self._headers)
        self._response = response
        opened_at = time.monotonic()
        self._connected.set()
        try:
            parser = SseParser()
            while not self._stopped.is_set():
                # Line at a time, because server-sent events are a line format and a
                # buffered `read(n)` would sit on a small event waiting for n bytes that
                # a quiet mailbox never sends. The parser still frames it; it accepts
                # any chunking, and a line is simply one chunking that always arrives.
                line = response.readline()
                if not line:
                    return opened_at  # the hub closed; reconnect
                for event in parser.feed(line.decode("utf-8", "replace")):
                    if event.event == _ARRIVAL_EVENT:
                        self._arrived.set()
        finally:
            self._response = None
            self._shut(response)
        return opened_at

    @staticmethod
    def _shut(response: Any) -> None:
        if response is None:
            return
        try:
            response.close()
        except Exception:  # noqa: BLE001 - closing is best-effort by definition
            pass


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


def _stream_for(root: Path) -> ArrivalStream | None:
    """The stream for this project's identity, or `None` if we cannot have one.

    Unconfigured, unreadable, or anything else at all: the answer is `None` and the
    waiter polls. Nothing here is worth failing a wait over.
    """
    try:
        return ArrivalStream(HubClient(load_config(start=root), timeout=_TIMEOUT))
    except Exception:  # noqa: BLE001 - no stream is a supported state, not an error
        return None


def _interval(poll_interval: float, stream: ArrivalStream | None) -> float:
    """How long to sleep before polling again.

    Longer while a connection is actually open, because the stream will interrupt the
    sleep long before it elapses. Never *unbounded*, though (FR-006): a stream that
    connected and then went silent — a proxy that buffers is the ordinary cause — is
    indistinguishable from a healthy one here, and this poll is what catches it.

    `max` rather than a plain substitution, so a caller that deliberately asked for a
    longer interval keeps it.
    """
    if stream is not None and stream.connected:
        return max(poll_interval, STREAMING_POLL_INTERVAL)
    return poll_interval


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
        # After the lock, never before: the lock is what keeps this to one waiter per
        # project, and connecting first would open a stream only to discover somebody
        # else already holds the project and close it again.
        stream = _stream_for(root)
        if stream is not None:
            stream.start()
            # The stream's `wait` *is* a sleeper — it sleeps, unless mail arrives. That
            # is the whole change: the loop below is unaltered, and the arrival reaches
            # `_run_once` by exactly the path a timed-out sleep takes.
            sleep = stream.wait
        try:
            while True:
                try:
                    code = _run_once(event, root)
                except Exception:  # noqa: BLE001 - a blip must not end an 8-hour wait
                    # The one-shot hook may fail silently and be retried next turn. A
                    # waiter has no next turn: it *is* the thing keeping an idle session
                    # reachable, so dying here means no wake until a human intervenes,
                    # with nothing said. The hub being briefly unreachable is the normal
                    # case — it is restarted on every deploy — so treat it as "nothing
                    # waiting" and poll again. A permanently dead hub costs one request
                    # per interval and recovers by itself the moment it returns.
                    code = 0
                if code != 0:
                    return code
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 0
                sleep(min(_interval(poll_interval, stream), remaining))
        finally:
            # On a wake, on a timeout, and on anything raised: a hook that leaks a
            # connection per turn is a hook that gets uninstalled.
            if stream is not None:
                stream.close()


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
