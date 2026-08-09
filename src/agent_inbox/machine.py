"""What this machine can honestly say about itself, for an agent's profile.

Three facts: which box this is, which checkout it is working in, and which client is
running. All are things the client can *read* rather than be told, which is why they are
here and the model is not — nothing in the environment names the model, so an agent that
wants its model on its profile writes it there itself.

Everything produced here lands in the free-form ``profile`` dict, so it is still a
**claim**: the hub stores it and verifies none of it. The console renders it as such.
"""

import getpass
import logging
import os
import socket
from collections.abc import Mapping
from pathlib import Path

from agent_inbox.client import project_root

logger = logging.getLogger(__name__)

#: Suppress the whole business. Current name first, as everywhere else.
OPT_OUT_VARS: tuple[str, ...] = (
    "AGENT_INBOX_NO_MACHINE_FACTS",
    "AGENT_MAILBOX_NO_MACHINE_FACTS",  # legacy, still honoured
)

#: A cap on how much of the checkout path to disclose, for roots outside the home
#: directory. Two segments name the project (``checkouts/billing``) without walking far
#: enough up a shared filesystem to describe how somebody's estate is laid out.
#:
#: **This cap is the second line, not the first** — see :func:`checkout`. Counting
#: segments alone is not a safe rule: ``/home/sal/agent-inbox`` has an account name in
#: its last two, so a project cloned straight into a home directory would have published
#: the very thing the trimming exists to withhold. The home anchor is what holds that;
#: the cap only bounds the cases the anchor does not reach.
ROOT_SEGMENTS = 2

#: Below this length an account name is matched only as a whole path segment, never as a
#: substring. Three, because a two-letter login redacts a great deal of ordinary English
#: — ``jo`` would take ``projects`` with it — and a two-letter fragment inside a longer
#: word identifies nobody. Above it, substring matching is what makes rule 2 of
#: :func:`checkout` true rather than nearly true.
MIN_REDACTED_NAME = 3

#: The keys written. Named here so a test can assert on the set rather than on prose.
FACT_KEYS: frozenset[str] = frozenset({"host", "root", "client"})


def opted_out(env: dict[str, str] | None = None) -> bool:
    """Has this machine asked to be left out of it?"""
    environ = env if env is not None else dict(os.environ)
    return any(environ.get(var, "").strip() for var in OPT_OUT_VARS)


def hostname() -> str:
    """This machine's name, or ``""`` if it will not say.

    A host that cannot name itself is not an error worth failing a join over — the
    profile simply goes without, which is the state every profile is in today.
    """
    try:
        name = socket.gethostname().strip().rstrip(".")
    except OSError:  # pragma: no cover - a hostname lookup that raises is exotic
        logger.debug("no hostname available; the profile goes without one")
        return ""
    # "localhost" names nothing and would sit in the roster looking like an answer.
    return "" if name.lower() in {"", "localhost", "localhost.localdomain"} else name


def account_names(home: Path | None = None) -> set[str]:
    """Every spelling of *this* account, casefolded. Used to redact, not to identify.

    We are trimming a path that belongs to whoever is running this, so the one thing we
    reliably know is their own name — from the login database and from the home
    directory, which disagree often enough to be worth taking both.
    """
    names: set[str] = set()
    try:
        names.add(getpass.getuser())
    except OSError, KeyError:  # pragma: no cover - a box with no login name is exotic
        pass
    try:
        names.add((home if home is not None else Path.home()).name)
    except OSError, RuntimeError:  # pragma: no cover - likewise
        pass
    return {name.casefold() for name in names if name.strip()}


def checkout(start: Path | None = None, home: Path | None = None) -> str:
    """The tail of this project's root: never the whole path, and never the account
    except in the one case named below.

    Two rules, and the second exists because the first is not enough:

    1. **Nothing at or above the home directory.** That is where the account name sits
       in the ordinary layouts, and it also throws away how somebody's estate is
       arranged. What remains is the part that names the checkout.
    2. **No segment that so much as contains this account's name.** Everything up to
       and including the last such segment goes with it.

    Rule 2 is the one that took an outside reviewer to find, twice. Home-anchoring alone
    leaves ``/srv/checkouts/sal/agent-inbox``, ``/Volumes/Work/sal/agent-inbox`` and
    ``D:\\sal\\agent-inbox`` all reporting ``sal/agent-inbox`` — shared filesystems and
    second drives are laid out per-user just as home directories are, and none of them
    are *under* home. Redacting by name works there precisely because the account whose
    path this is, is the account running the code.

    It matches **substrings**, not whole segments, because whole-segment matching was
    still leaking: ``~/workspace/sal-agent-inbox`` and ``/srv/sal_projects/billing``
    both name the account without any segment being equal to it. Substring matching
    over-redacts sometimes — an account called ``sal`` loses ``salary-reports`` too —
    and that is the correct direction to be wrong in. Losing a word costs a reader some
    context; keeping it discloses a person.

    **The one accepted exception**, stated because a guarantee with a quiet hole in it
    is worse than a narrower guarantee: below :data:`MIN_REDACTED_NAME` only whole
    segments are matched, so an account called ``jo`` still reports
    ``jo-agent-inbox``. Closing it would mean substring-matching two characters, which
    blanks most paths outright. Two characters inside a directory the account holder
    named themselves identify nobody, so this is left open on purpose and pinned by a
    test rather than left to be rediscovered.

    Whatever survives is capped at :data:`ROOT_SEGMENTS`. A root with nothing below the
    redaction — the home directory itself, say — yields ``""``, which is the safe answer
    and the one the caller already omits rather than sending blank.
    """
    root = project_root(start)
    parts: tuple[str, ...] = ()
    try:
        base = (home if home is not None else Path.home()).resolve()
    except OSError, RuntimeError:  # pragma: no cover - a box with no home is exotic
        base = None
    if base is not None:
        try:
            parts = root.relative_to(base).parts
        except ValueError:
            base = None  # Outside home entirely; fall through to the whole path.
    if base is None:
        parts = tuple(
            p for p in root.parts if p not in {"/", "\\"} and not p.endswith(":\\")
        )
    mine = account_names(home)
    # Keep only what is below the *last* segment naming this account: a path may pass
    # through it more than once, and the deepest one is the one that still discloses.
    for index in range(len(parts) - 1, -1, -1):
        if _names_the_account(parts[index], mine):
            parts = parts[index + 1 :]
            break
    return "/".join(parts[-ROOT_SEGMENTS:])


def _names_the_account(segment: str, mine: set[str]) -> bool:
    """Does this one path segment give the account away?"""
    folded = segment.casefold()
    return any(
        name in folded if len(name) >= MIN_REDACTED_NAME else name == folded
        for name in mine
    )


def machine_facts(
    start: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Host and checkout for a profile, or ``{}`` if suppressed or unknowable.

    Empty values are omitted rather than written blank: a key present with nothing in
    it reads as "asked and got nothing", which is not what happened.
    """
    if opted_out(env):
        return {}
    facts = {"host": hostname(), "root": checkout(start), "client": client_version()}
    return {key: value for key, value in facts.items() if value}


def client_version() -> str:
    """Which agent-inbox this agent is running.

    **Recorded at join, and therefore a claim about a moment rather than a fact about
    now.** It goes stale the instant the agent upgrades, and the console renders it in
    the self-declared panel for that reason.

    It is worth having anyway. On 2026-08-05 `igor_laszlo` found that an install on an
    interpreter older than our floor silently resolves to an old release rather than
    failing — two agents on one machine sat on 0.34.0 without knowing, unable to be
    woken by the release that added waking. Nobody could see that from the hub, because
    nothing anywhere recorded which client an agent was using.

    A stale answer is more than none, and an agent that re-joins corrects it. The
    version the hub *observes* on every call would be strictly better and is a larger
    piece of work: it needs a request header, a place to put it, and a write on a path
    that currently has none.
    """
    from agent_inbox import __version__

    return str(__version__ or "")


def merged_into(profile: Mapping[str, object], facts: dict[str, str]) -> dict[str, str]:
    """Only the facts this profile does not already state.

    **The agent's own word wins.** ``host`` is already in informal use as a human
    description — one live profile reads ``"host": "SFadhley Hartree workstation"`` —
    and overwriting that with a hostname would replace something somebody chose with
    something a library guessed. So this only ever fills a gap.
    """
    return {
        key: value
        for key, value in facts.items()
        if not str(profile.get(key, "") or "").strip()
    }
