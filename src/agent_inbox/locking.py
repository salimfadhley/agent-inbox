"""One writer at a time, across processes, without a dependency.

An atomic *write* stops a file being torn in half. It does nothing about a **lost
update**: two processes that each read, each merge, and each replace produce a file
containing only the second one's work, and the first one's is gone with no error
anywhere.

That is issue #49. Two engines joining the same project in the same moment each read a
config without the other's entry and each write one containing only their own. The
symptom is the one this codebase treats as most serious — **an agent whose mail quietly
stops arriving** — and nothing looks wrong until somebody notices a reply that never
came.

**`O_EXCL` rather than `fcntl` or `msvcrt`.** Creating a file exclusively is atomic on
every filesystem this runs on and needs no per-platform branch, which matters because
several agents here work on Windows. `wake.py` already uses the same idiom for its
single-waiter lock; this is that pattern generalised, with the one difference that
matters: a waiter that cannot take the lock **skips**, and a writer that cannot take it
must **wait**, because skipping a write is the data loss.
"""

import json
import logging
import os
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from agent_inbox.exceptions import MailboxError

logger = logging.getLogger(__name__)

#: How long to keep trying before giving up. The protected section is a read, a merge
#: and a rename — microseconds — so anything approaching this means a lock nobody owns
#: or a filesystem in trouble, and neither is improved by waiting longer.
DEFAULT_TIMEOUT = 5.0

#: How long between attempts. Short enough that an ordinary contended join is
#: imperceptible, long enough not to spin a core while waiting.
RETRY_EVERY = 0.02

#: When a held lock is assumed abandoned. Deliberately generous next to the microseconds
#: the section takes: the cost of reclaiming too early is the corruption this prevents,
#: and the cost of reclaiming too late is a few seconds of waiting.
STALE_AFTER = 30.0


class LockUnavailable(MailboxError):
    """Somebody else is writing and would not let go.

    **Raised rather than proceeding anyway**, which is the whole point of the lock. A
    writer that gave up and wrote regardless would produce exactly the lost update it
    was taken out to prevent, at the one moment we know the risk is real — and it would
    do it silently.
    """

    code = "lock_unavailable"


def _held_by(path: Path) -> tuple[int, float] | None:
    """The pid and time in a lock file, or None if it says nothing usable."""
    try:
        data = json.loads(path.read_text())
        return int(data["pid"]), float(data["created"])
    except OSError, ValueError, KeyError, TypeError, json.JSONDecodeError:
        # Unreadable, truncated, or written by something else entirely. Treated as
        # "no useful claim" rather than as an error: a half-written lock file is what a
        # crash mid-acquire leaves, and it must not wedge every future writer.
        return None


def _age(path: Path) -> float:
    """How long the lock file has existed, by its own mtime.

    The fallback when the *contents* say nothing. Needed because there is a real gap
    between `O_EXCL` creating the file and the holder writing its pid into it, and a
    contender arriving inside that gap reads an **empty** file — which is
    indistinguishable, by content alone, from the debris of a crash.

    Treating that as abandoned is what the first version of this did, and it meant the
    lock excluded nobody: under genuine contention, which is the only case that
    matters, the loser reclaimed the winner's brand-new lock and both proceeded. The
    concurrent-join test caught it on the first run. Age separates the two states
    cleanly — the gap is microseconds and a crash is seconds old by the time anyone
    looks.
    """
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return 0.0


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Somebody else's process. It exists, which is the question being asked.
        return True
    except OSError:
        return False
    return True


def _abandoned(path: Path, *, stale_after: float) -> bool:
    """Whether a held lock can be taken from its holder.

    Three ways to qualify, and each covers what the others cannot.

    **The pid check** reclaims immediately from a process that has died — the common
    case, since an agent's session ends whenever its human closes the terminal, and
    waiting out a timeout for a process that is already gone is pure delay.

    **The age check** covers a pid we cannot ask about honestly: pids are recycled, so
    a live pid is weaker evidence than it looks, and a lock older than any real
    critical section is abandoned whatever the process table says.

    **A lock saying nothing usable is judged by age alone**, never reclaimed on the
    spot. See :func:`_age`: on the spot is wrong, and wrong in the direction that
    silently removes all exclusion.
    """
    held = _held_by(path)
    if held is None:
        return _age(path) > stale_after
    pid, created = held
    return not _alive(pid) or (time.time() - created) > stale_after


@contextmanager
def exclusive(
    path: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    stale_after: float = STALE_AFTER,
    sleep: Callable[[float], None] | None = None,
) -> Generator[None]:
    """Hold *path* as a lock for the duration of the block, or raise.

    Released on the way out however the block ends, including by exception — a writer
    that fails must not leave the next one waiting for a timeout.

    Only the holder releases. A process that reclaimed a stale lock and then finished
    must not delete a lock some third process has since taken, so the pid recorded in
    the file is checked before unlinking.

    **What this does not promise.** Reclaiming an abandoned lock cannot be made atomic
    without an OS lock, so two processes that both judge the *same* thirty-second-old
    lock abandoned in the same instant can both take it. That is a microsecond window
    at the end of an already-exceptional path, and the alternative — never reclaiming —
    means one crashed agent stops every later write in that project for good. Said
    plainly here rather than left for somebody to discover.
    """
    pause = sleep if sleep is not None else time.sleep
    deadline = time.monotonic() + max(0.0, timeout)
    path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _abandoned(path, stale_after=stale_after):
                logger.warning(
                    "event=lock.reclaimed path=%s — the holder is gone or the lock is "
                    "older than any real critical section",
                    path,
                )
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass  # somebody else reclaimed it first; try again either way
                except OSError:
                    raise LockUnavailable(
                        f"cannot clear a stale lock at {path}"
                    ) from None
            elif time.monotonic() >= deadline:
                # `from None`, here and below: the `FileExistsError` being handled is
                # the ordinary signal that somebody else holds the lock, not a fault.
                # Chaining it would print a traceback that reads like a bug in the
                # locking to somebody whose actual problem is a busy project.
                raise LockUnavailable(
                    f"another process has been writing {path.parent} for more than "
                    f"{timeout:g}s. Nothing has been changed — try again."
                ) from None
            else:
                pause(RETRY_EVERY)
            # The deadline governs the reclaim path too. Without it, a lock being
            # recreated as fast as it is cleared — two processes fighting, or a
            # supervisor restarting a crashing agent — would spin here for ever
            # instead of failing with a sentence saying so.
            if time.monotonic() >= deadline and path.exists():
                raise LockUnavailable(
                    f"could not take the lock at {path} within {timeout:g}s. "
                    "Nothing has been changed — try again."
                ) from None
            continue
        except OSError as denied:
            raise LockUnavailable(
                f"cannot create a lock at {path}: {denied}"
            ) from denied

        # **The claim is written immediately, and it is still not instantaneous.** A
        # contender arriving between the create above and this line sees an empty file;
        # `_abandoned` judges that by age precisely so it does not mistake it for
        # debris. Keep these two statements adjacent.
        with os.fdopen(handle, "w", encoding="utf-8") as writing:
            json.dump({"pid": os.getpid(), "created": time.time()}, writing)
        break

    try:
        yield
    finally:
        held = _held_by(path)
        if held is not None and held[0] == os.getpid():
            try:
                path.unlink()
            except OSError:
                # The next writer's staleness check will clear it. Failing to release
                # must never turn a successful write into a reported failure.
                logger.debug("could not release the lock at %s", path, exc_info=True)


__all__ = ["DEFAULT_TIMEOUT", "STALE_AFTER", "LockUnavailable", "exclusive"]
