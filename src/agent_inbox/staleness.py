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

from __future__ import annotations

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
    except (TypeError, ValueError):
        return
    if theirs and ours and theirs > ours:
        _behind = (__version__, hub_version)
    elif _behind and theirs <= ours:
        # An upgrade mid-session, or a hub rolled back. Stop saying it.
        _behind = None


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
