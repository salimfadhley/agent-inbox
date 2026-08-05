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

from agent_inbox.client import CONFIG_NAMES

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


#: Keys that make a file deployment-specific rather than merely configuration. A hub
#: address names somebody's infrastructure; a token admits a machine to it. Either one
#: in a shared repository is a disclosure, and `token` is the one that is also a
#: credential.
LOCATION_KEYS = ("hub", "token")

#: How deep to look for identity files. An agent may be working several directories into
#: a checkout, so the repository root is not always where the file is — but an unbounded
#: walk of somebody's monorepo inside `doctor` is a cost nobody asked for.
_MAX_DEPTH = 4


def declares_location(path: Path) -> bool:
    """Whether this file actually carries a hub or a token.

    Read rather than assumed, because the whole warning rests on it: an empty or
    placeholder config is not a disclosure, and crying wolf about one teaches the reader
    to skip the line that matters.

    Deliberately a cheap textual check rather than a TOML parse. A file that cannot be
    parsed is exactly the case where we should still warn — malformed today, committed
    all the same — and a parser would return False for it.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # noqa: PERF203 - unreadable is not evidence of safety, see below
        # An unreadable file is not proof of anything, and this runs inside `doctor`
        # where a crash costs the reader every check after it. Warn rather than claim
        # safety: the failure this whole module exists to prevent is confident silence.
        return True
    return any(
        line.lstrip().startswith(f"{key} ") or line.lstrip().startswith(f"{key}=")
        for line in text.splitlines()
        for key in LOCATION_KEYS
    )


def is_staged(path: Path, root: Path) -> bool:
    """Whether *path* is staged for the next commit.

    Reported separately from *tracked* because the remedies differ and so does the
    urgency: a staged file has not been committed yet, so `git restore --staged` is the
    whole fix. A tracked one is in the history, and somebody has to decide about that.
    """
    done = _git(["diff", "--cached", "--name-only", "--", str(path)], root)
    return bool(done and done.returncode == 0 and done.stdout.strip())


def exposed_configs(root: Path) -> list[tuple[Path, str]]:
    """Identity files in this checkout that git is not protecting.

    Each entry is the file and one of ``"staged"``, ``"tracked"`` or ``"unignored"``,
    worst first — those are three different conversations and collapsing them into
    "there is a problem" leaves the reader to work out which.

    **Why this exists as a check rather than as advice.** `join` already adds an ignore
    rule, but that only helps the project it ran in, at the moment it ran: a file may
    predate the rule, or have been committed before anybody thought about it, or sit in
    a sibling directory the rule does not reach. `parisa_murthy` and `igor_laszlo` each
    found a repository whose `.gitignore` named the *pre-rename* file and read as done
    on inspection. Attention does not scale; this asks git every time.

    Empty when git is unavailable or this is not a repository — an honest "cannot say",
    not a claim of safety. The caller says which.
    """
    if not in_a_repository(root):
        return []
    found: dict[Path, str] = {}
    for name in CONFIG_NAMES:
        for path in _candidates(root, name):
            if not declares_location(path):
                continue
            if is_staged(path, root):
                found[path] = "staged"
            elif is_tracked(path, root):
                found[path] = "tracked"
            elif not is_ignored(path, root):
                found[path] = "unignored"
    order = {"staged": 0, "tracked": 1, "unignored": 2}
    return sorted(found.items(), key=lambda pair: (order[pair[1]], str(pair[0])))


def _candidates(root: Path, name: str) -> list[Path]:
    """Every file called *name* within :data:`_MAX_DEPTH` of *root*, `.git` aside."""
    hits = [root / name] if (root / name).is_file() else []
    for depth in range(1, _MAX_DEPTH + 1):
        pattern = "/".join(["*"] * depth) + f"/{name}"
        hits.extend(
            path
            for path in root.glob(pattern)
            if path.is_file() and ".git" not in path.parts
        )
    return hits
