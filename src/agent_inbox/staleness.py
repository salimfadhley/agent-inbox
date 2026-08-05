"""Noticing that this client is older than the hub it is talking to.

A long-running agent session keeps whatever server it launched with. The host lived
exactly this: her session lacked `check_threads`, `unread_count` and `peek_message`
while the hub and everyone else had moved on, and **nothing announced it**. She had to
infer it from the tool list — the recurring shape here, a stale thing that looks
identical to a current one.

**The hub's own version is the signal**, not PyPI. Issue #14 proposed polling the index
once an hour; comparing against the hub we are already talking to is better on every
axis that issue worried about:

- **It cannot delay a tool call.** There is no extra request. The version arrives in
  answers we already make.
- **There is no state to keep.** No timestamp file, nothing new to gitignore.
- **Offline is not a special case.** An air-gapped hub still reports its own version,
  and a client that cannot reach the hub has a louder problem than staleness.

And it is the more useful comparison anyway: what matters is not whether a newer release
exists somewhere, but whether *this hub* speaks something this client does not.
"""

import re

from agent_inbox import __version__

#: Set once a hub reports a version newer than ours. Module state, deliberately: the
#: MCP server is one process per project, and this is a fact about that process.
_behind: tuple[str, str] | None = None

_NUMBERS = re.compile(r"(\d+)")


def _comparable(version: str) -> tuple[int, ...]:
    """The leading numeric parts, for comparison.

    Tolerant on purpose. Versions here come from `hatch-vcs` and look like
    `0.26.1.dev23+g1a4020368` between releases; a strict parser would raise on the
    development suffix and a staleness check that crashes is worse than one that is
    occasionally imprecise.
    """
    head = version.split("+", 1)[0].split(".dev", 1)[0]
    return tuple(int(n) for n in _NUMBERS.findall(head)[:3])


def note_hub_version(hub_version: str | None) -> None:
    """Record whether the hub is ahead of us. Never raises."""
    global _behind
    if not hub_version:
        return
    try:
        theirs, ours = _comparable(hub_version), _comparable(__version__)
    except TypeError, ValueError:
        return
    if theirs and ours and theirs > ours:
        _behind = (__version__, hub_version)
    elif _behind and theirs <= ours:
        # An upgrade mid-session, or a hub rolled back. Stop saying it.
        _behind = None


#: The interpreter this project's current releases need. Read from the package metadata
#: rather than typed here, so it cannot drift from `pyproject.toml`.
#:
#: **Why a client can be old without anybody choosing it.** `uv tool install
#: "agent-inbox[clients]>=0.17.1"` on an older interpreter does not fail — the resolver
#: finds the newest release that *does* support it and installs that, prints "Installed
#: 2 executables", and says nothing. The floor exists precisely so an unreachable
#: version "fails and tells you, instead of quietly settling on an old release"; on a
#: too-old Python it does the exact thing it was written to prevent.
#:
#: Reported by `igor_laszlo` on 2026-08-05, who noticed only by diffing `--version`
#: against what he asked for. Two agents on one machine were left on 0.34.0 and could
#: not be woken — the feature the release they missed had added.
def python_floor() -> str:
    """The interpreter our current release needs, e.g. ``"3.14"``."""
    from importlib.metadata import metadata

    try:
        want = str(metadata("agent-inbox").get("Requires-Python") or "")
    except Exception:  # noqa: BLE001 - metadata is absent in odd installs; say nothing
        return ""
    return want.lstrip(">=~^ ").strip()


def python_is_too_old() -> str:
    """A sentence naming the mismatch, or ``""`` when this interpreter is fine.

    The diagnosis `doctor` could not previously give: it knew the client was behind and
    told the reader to run an upgrade that would silently do nothing.
    """
    import sys

    floor = python_floor()
    if not floor:
        return ""
    try:
        wanted = tuple(int(part) for part in floor.split(".")[:2])
    except ValueError:  # pragma: no cover - a floor we cannot parse is not a diagnosis
        return ""
    if sys.version_info[:2] >= wanted:
        return ""
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    return (
        f"this Python is {running} and agent-inbox needs {floor} or newer. An install "
        f"that does not pin a version will **succeed** here and silently leave you on "
        f"an older release — it resolves to the newest one your interpreter supports "
        f"rather than failing. Install a newer Python (`uv python install {floor}`), "
        f"then reinstall."
    )


def notice() -> str | None:
    """What to tell the agent, or None when there is nothing to say.

    **Informational, not instruction.** This project is deliberate that arriving text is
    data; a notice reading "you must upgrade" invites an agent to start doing package
    management in the middle of somebody's task, which is not what its operator asked
    for. State the fact, name both versions, give the one command, stop.
    """
    if _behind is None:
        return None
    ours, theirs = _behind
    return (
        f"Your agent-inbox client is {ours}; this hub runs {theirs}. Tools added since "
        f"{ours} will be missing from this session and will look like they do not "
        f"exist. To update: uv tool install --refresh --force 'agent-inbox[clients]' "
        f"— then restart this session, because a running session keeps the tools it "
        f"started with."
    )


def reset() -> None:
    """Forget what we know. For tests."""
    global _behind
    _behind = None


def standing(hub_version: str | None) -> str | None:
    """Which way round the skew is: ``"behind"``, ``"ahead"``, or ``None``.

    ``None`` covers three cases a caller reporting to a human must not distinguish:
    level, unknowable, and unreadable. **Absent is not older** — a hub that reports
    no version is not evidence of anything, and a client that guessed would be inventing
    a
    fault.

    Separate from :func:`note_hub_version` because that one records a *session* fact for
    the MCP server to mention later, while this answers a question asked once.
    """
    if not hub_version:
        return None
    try:
        theirs, ours = _comparable(hub_version), _comparable(__version__)
    except TypeError, ValueError:
        return None
    if not theirs or not ours:
        return None
    if theirs > ours:
        return "behind"
    if ours > theirs:
        return "ahead"
    return None
