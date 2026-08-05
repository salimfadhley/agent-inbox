"""Make sure the file we write is one git will not commit.

`join` writes ``agent-inbox.toml``, and that file may carry a device token. Whether it
reaches a shared remote is therefore not a matter of taste, and until now it was left to
the reader: the onboarding page said *"add it to `.gitignore` if it is not there
already"*, which is advice given once to somebody who cannot easily tell whether an
existing near-miss line already covers them.

**A rename made that advice wrong everywhere at once.** The file used to be called
``agent-mailbox.toml``. Repositories carrying that line still carry it, correctly
commented, one word out of date — so they read as protected on inspection and are not.
Found by `parisa_murthy` on 2026-08-04, who demonstrated it by watching `git add -A`
stage the file, then flagged it rather than committing the fix.

So this checks rather than advises. Attention does not scale, which is the same reason
the deployment-specifics rule became a test rather than a note.

**Asking git, not parsing `.gitignore`.** Ignore rules compose: a repository has nested
ignore files, a global core.excludesFile, negations, and precedence between them. A
parser here would be a second, worse implementation of something git already answers
exactly — and it would be wrong in the direction that matters, reporting protection that
does not exist.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

#: How long to wait for git. It is a local, indexless query; a second is generous, and a
#: hang here must never delay a join.
_TIMEOUT = 5.0

#: What we add, and the reason, so the next reader knows why the line is there rather
#: than deleting it as clutter.
_NOTE = "# agent-inbox: identity and possibly a device token. Never commit."


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess[str] | None:
    """Run git in *root*, or ``None`` if git is unavailable or unhappy."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],  # noqa: S607 - git from PATH is the contract everywhere else
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None


def in_a_repository(root: Path) -> bool:
    """Whether *root* is inside a git working tree."""
    done = _git(["rev-parse", "--is-inside-work-tree"], root)
    return bool(done and done.returncode == 0 and done.stdout.strip() == "true")


def is_ignored(path: Path, root: Path) -> bool:
    """Whether git would ignore *path*. Asks git; does not guess."""
    done = _git(["check-ignore", "--quiet", "--no-index", str(path)], root)
    return bool(done and done.returncode == 0)


def is_tracked(path: Path, root: Path) -> bool:
    """Whether git already has this file.

    Worth knowing separately: an ignore rule does not apply to a file already tracked,
    so adding one to a repository that has committed the config achieves nothing and
    would leave the caller believing otherwise.
    """
    done = _git(["ls-files", "--error-unmatch", str(path)], root)
    return bool(done and done.returncode == 0)


def ensure_ignored(path: Path, root: Path) -> str:
    """Make git ignore *path*, and say what happened.

    Returns one of ``"already"``, ``"added"``, ``"tracked"``, or ``""`` when there is
    nothing to do because this is not a repository.

    ``"tracked"`` is the one worth acting on: the file is already in git, so an ignore
    line will not help and somebody has to decide what to do about the history. Saying
    so is the whole point — quietly appending a rule that changes nothing would leave a
    reader more confident and no safer.
    """
    if not in_a_repository(root):
        return ""
    if is_tracked(path, root):
        return "tracked"
    if is_ignored(path, root):
        return "already"
    _append(root / ".gitignore", path.name)
    # Ask again rather than assume: reporting a protection we have not verified is the
    # failure this module exists to prevent, and the answer is one cheap local call.
    #
    # **Not covered by a test, and deliberately not claimed to be.** Deleting this line
    # fails nothing, because every case that can be constructed here ends with the file
    # genuinely ignored — git resolves by last matching pattern, and ours is appended
    # last. It is insurance against ignore rules composing in a way this author did not
    # foresee, which is exactly the sort of thing that has no test until it happens.
    return "added" if is_ignored(path, root) else "tracked"


def _append(gitignore: Path, name: str) -> None:
    """Add one entry, with its reason, leaving everything else untouched."""
    existing = gitignore.read_text() if gitignore.is_file() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(f"{existing}{prefix}\n{_NOTE}\n{name}\n")
    logger.info("event=config.gitignore.added file=%s", name)
