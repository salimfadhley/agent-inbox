"""The lock itself: it waits, it lets go, and it cannot be left holding the door.

A lock is only worth having if every one of these holds, and each is a way the
mailbox has been broken before or a way it obviously could be:

- **It waits rather than skipping.** This is the one difference from `wake.py`'s
  single-waiter lock, which the idiom is otherwise copied from. A waiter that finds
  another waiter already running should stand down — a second waiter announces the
  same arrival twice. A *writer* that stands down loses somebody's identity, which is
  the whole of issue #49. Same mechanism, opposite answer.
- **It lets go on the way out, including out through an exception.** `write_config`
  raises for an engine that is already configured; a lock leaked on that path would
  make every later write in that project wait out a timeout for nothing.
- **It cannot be held for ever by a process that died.** A crash mid-write is the
  ordinary case, not the exotic one — an agent's session ends whenever its human
  closes the terminal.
- **A lock file that says nothing usable does not wedge the project.** A truncated
  file is what a crash *during acquire* leaves, and it must not be more durable than
  a valid one.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agent_inbox.locking import LockUnavailable, exclusive


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    return tmp_path / "writes.lock"


class TestItExcludes:
    def test_the_file_exists_while_held_and_not_after(self, lock: Path) -> None:
        with exclusive(lock):
            assert lock.is_file()

        assert not lock.exists()

    def test_a_second_writer_is_refused_while_the_first_holds(self, lock: Path) -> None:
        """The property everything else rests on. Refused *loudly*: a lock that let
        the second writer through on a timeout would be theatre — it would fail exactly
        when contention is real, which is the only time it is doing anything."""
        with exclusive(lock), pytest.raises(LockUnavailable):
            with exclusive(lock, timeout=0.05):
                pass

    def test_the_refusal_says_where_and_that_nothing_changed(self, lock: Path) -> None:
        """A caller seeing this has to decide whether to retry, and cannot if the
        message leaves open whether a partial write happened."""
        with exclusive(lock), pytest.raises(LockUnavailable) as refused:
            with exclusive(lock, timeout=0.05):
                pass

        assert "Nothing has been changed" in str(refused.value)
        assert str(lock.parent) in str(refused.value)


class TestItWaitsRatherThanSkipping:
    """The design decision, asserted rather than described.

    `wake._acquire_lock` returns `False` and the caller quietly does nothing. If this
    behaved the same way, two engines joining at once would produce one identity and a
    zero exit code — the failure being fixed, wearing a lock as a disguise.
    """

    def test_it_takes_its_turn_once_the_holder_is_done(self, lock: Path) -> None:
        released = threading.Event()

        def hold() -> None:
            with exclusive(lock):
                time.sleep(0.2)
            released.set()

        holder = threading.Thread(target=hold)
        holder.start()
        while not lock.exists():  # let the holder actually get there first
            time.sleep(0.005)

        with exclusive(lock, timeout=5.0):
            got_in_after_release = released.is_set()

        holder.join()
        assert got_in_after_release, "it took the lock while another writer held it"


class TestItLetsGo:
    def test_an_exception_inside_the_block_still_releases(self, lock: Path) -> None:
        """`write_config` raises for an already-configured engine, which is an ordinary
        outcome of `join`, not an exotic one. Leaking the lock there would make the
        commonest refusal poison the project for the next writer."""
        with pytest.raises(RuntimeError):
            with exclusive(lock):
                raise RuntimeError("the write refused")

        assert not lock.exists()
        with exclusive(lock, timeout=0.05):  # and the next writer gets straight in
            pass

    def test_it_does_not_delete_a_lock_somebody_else_now_holds(
        self, lock: Path
    ) -> None:
        """The subtle one. A process that reclaimed a stale lock and then finished must
        not unlink whatever is there *now* — between reclaim and release, a third
        process may legitimately have taken it, and deleting that hands the door to a
        fourth while the third is mid-write."""
        with exclusive(lock):
            lock.write_text(
                json.dumps({"pid": os.getpid() + 1, "created": time.time()})
            )

        assert lock.is_file(), "it deleted a lock it did not hold"


class TestADeadHolderDoesNotWedgeTheProject:
    def _a_pid_that_has_certainly_exited(self) -> int:
        """Waited on rather than invented. A made-up number can belong to a real
        process on a busy machine, and the test would then assert the opposite of
        what it says."""
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait(timeout=60)
        return done.pid

    def test_a_lock_held_by_a_dead_process_is_reclaimed(self, lock: Path) -> None:
        lock.write_text(
            json.dumps(
                {"pid": self._a_pid_that_has_certainly_exited(), "created": time.time()}
            )
        )

        with exclusive(lock, timeout=0.05):
            pass  # reclaimed immediately, without waiting out the timeout

    def test_an_old_lock_is_reclaimed_even_though_its_pid_is_alive(
        self, lock: Path
    ) -> None:
        """Pids are recycled, so "the pid is alive" is weaker evidence than it looks.
        Age is the backstop: nothing here holds this lock for thirty seconds."""
        lock.write_text(
            json.dumps({"pid": os.getpid(), "created": time.time() - 10_000})
        )

        with exclusive(lock, timeout=0.05):
            pass

    def test_a_fresh_lock_from_a_live_process_is_not_reclaimed(
        self, lock: Path
    ) -> None:
        """**The paired positive, and the one that makes the two above mean anything.**
        Without it, a "reclaim" that simply deleted every lock it found would pass both
        of them while providing no exclusion whatsoever."""
        lock.write_text(json.dumps({"pid": os.getpid(), "created": time.time()}))

        with pytest.raises(LockUnavailable):
            with exclusive(lock, timeout=0.05):
                pass

    def test_an_old_lock_file_that_says_nothing_usable_is_reclaimed(
        self, lock: Path
    ) -> None:
        """What a crash *during* acquire leaves: the file is created before it is
        written. Treating unreadable as "somebody's, for ever" would make the most
        fragile moment produce the most durable lock."""
        lock.write_text("half a jso")
        long_ago = time.time() - 10_000
        os.utime(lock, (long_ago, long_ago))

        with exclusive(lock, timeout=0.05):
            pass

    def test_a_fresh_lock_file_that_says_nothing_yet_is_left_alone(
        self, lock: Path
    ) -> None:
        """**The one that matters most in this class, and it was found the hard way.**

        `O_EXCL` creates the file, and the holder writes its pid a moment later. A
        contender arriving in between reads an *empty* file — which by content alone
        looks exactly like crash debris.

        The first version reclaimed it on the spot, and so excluded nobody: under real
        contention, which is the only case the lock exists for, the loser deleted the
        winner's brand-new lock and both went on to write. The concurrent-join test
        failed on its first run because of it. Age is what tells the two apart.
        """
        lock.write_text("")

        with pytest.raises(LockUnavailable):
            with exclusive(lock, timeout=0.05):
                pass

    def test_it_records_who_holds_it(self, lock: Path) -> None:
        """Not decoration — the pid is what the two checks above read, and what stops
        a holder deleting somebody else's lock."""
        with exclusive(lock):
            held = json.loads(lock.read_text())

        assert held["pid"] == os.getpid()


class TestItDoesNotDependOnAnythingPlatformSpecific:
    def test_no_posix_only_locking_module_is_imported(self) -> None:
        """Several agents here work on Windows, and `fcntl` does not exist there. This
        is why the idiom is `O_EXCL` rather than the more obvious `flock`: `flock`
        fails at *import* time on the platform least likely to be running this suite,
        so nothing here would ever catch it.

        Asserted against the imports rather than the text, because the module docstring
        names both modules while explaining why it uses neither — a search for the bare
        word fails on the very comment that proves the rule is understood.
        """
        import ast

        source = (
            Path(__file__).resolve().parents[1] / "src" / "agent_inbox" / "locking.py"
        ).read_text()
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert not imported & {"fcntl", "msvcrt", "portalocker", "filelock"}
