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


#: What to fall back to when package metadata cannot be read at all. A pin naming no
#: version would be worse than none: `uv tool install --python ""` is an error, and the
#: reader would be left with a command that cannot run.
FALLBACK_FLOOR = "3.14"


def interpreter_pin() -> str:
    """The interpreter every install instruction pins, e.g. ``"3.14"``.

    **Why pin at all** (owner, 2026-08-05): uv will not change the interpreter a tool is
    installed under. Asked for a release needing a newer Python than the one already in
    use, it resolves to an older release that fits, prints success, and leaves the agent
    where it was — the silent downgrade `igor_laszlo` reported. The pin turns that into
    a failure somebody can read.

    One function so the number lives once. It was on its way to being typed into the
    prompt, the console, and the staleness notice separately.
    """
    return python_floor() or FALLBACK_FLOOR


#: How an interpreter's path betrays where it came from. Ordered: the first match wins,
#: and `uv` is checked before the rest because a uv-managed Python can sit under a home
#: directory that also matches nothing else.
#:
#: Matched case-insensitively against the path, with both separators normalised, so one
#: table serves Windows and POSIX.
_ORIGINS: tuple[tuple[str, str], ...] = (
    ("/uv/python/", "uv"),
    ("/scoop/", "scoop"),
    # Before Homebrew: a miniconda installed *by* Homebrew lives under its Caskroom and
    # would otherwise be reported as Homebrew's. Both answers give the same practical
    # advice, but the specific one is the true one, and a reader comparing this against
    # `uv python list` would notice the difference.
    ("/miniconda", "conda"),
    ("/anaconda", "conda"),
    ("/.pyenv/", "pyenv"),
    ("/cellar/", "Homebrew"),
    ("/homebrew/", "Homebrew"),
    ("/appdata/local/programs/python", "python.org"),
    ("/chocolatey/", "chocolatey"),
    ("/windowsapps/", "the Microsoft Store"),
)


def interpreter_origin(executable: str | None = None) -> str:
    """Where the interpreter running this client came from — ``"uv"``, ``"scoop"``, …

    ``""`` when it cannot be told — an honest answer, and commoner than the table
    suggests: a distribution package, a hand-built Python or a container all land there.

    **Why a client cares.** `uv python install` counts *only* uv-managed interpreters.
    A perfectly good 3.14 from scoop or Homebrew satisfies `--python 3.14` while being
    invisible to the fetch, so running the fetch anyway installs a second one — on
    Windows today a strictly older one. `igor_laszlo` found that shape; this is what
    lets `doctor` say which case a reader is in rather than leave them to work it out.
    """
    import sys

    path = (executable if executable is not None else sys.executable or "").lower()
    path = path.replace("\\", "/")
    for fragment, name in _ORIGINS:
        if fragment in path:
            return name
    return ""


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
        f"rather than failing. Install a newer Python and reinstall **pinned to it** "
        f"— uv will not move a tool to a different interpreter on its own, so an "
        f"unpinned reinstall lands you back here:\n"
        f"       uv python install {floor}\n"
        f"       uv tool install --python {floor} --refresh --force "
        f"'agent-inbox[clients]'"
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
        f"exist. To update: uv tool install --python {interpreter_pin()} "
        f"--refresh --force 'agent-inbox[clients]' — keep `--python`, because uv "
        f"will not move a tool to a newer interpreter on its own and an unpinned "
        f"upgrade can silently resolve to an older release "
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
