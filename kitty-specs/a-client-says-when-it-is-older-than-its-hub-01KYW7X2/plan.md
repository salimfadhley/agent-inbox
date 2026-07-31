# Implementation Plan: a client says when it is older than its hub

**Branch**: `kitty/mission-a-client-says-when-it-is-older-than-its-hub-01KYW7X2`
**Date**: 2026-07-31 | **Spec**: `spec.md` | **Issue**: #14

## Summary

Reach, not invention. `staleness.notice()` already produces the right sentence — it even
says tools added since your version *"will look like they do not exist"*, which is precisely
the failure that prompted this. It reaches the MCP server and not `doctor`.

## Technical Context

**Language**: Python 3.12+ · **Dependencies**: none new · **Storage**: none
**Testing**: pytest, with FR-007 proved by removal in the reverse direction
**Constraints**: no extra request (FR-005); exit code unchanged (FR-003)

## Charter Check

- **ADR 0005** — one mechanism, every client. This mission exists *because* the mechanism
  reaches one client and not the other.
- **Mail is data** — `staleness.notice()`'s docstring already refuses to phrase itself as an
  instruction, so an agent does not start doing package management mid-task. Keep that.

## The approach

`doctor` already fetches the descriptor at its connectivity step and reads
`info.get("version")` to print it. It then discards the comparison it is holding.

```python
info = client.hub_info()          # already here
staleness.note_hub_version(info.get("version"))   # new
...
if message := staleness.notice():                 # new
    click.echo(f"{warn} version         {message}")
```

`staleness` gains one function for FR-004, because today it tracks only *behind*:

```python
def standing(hub_version: str | None) -> str | None:
    """`behind`, `ahead`, or None when level or unknowable."""
```

`ahead` is a different finding with a different remedy — the operator's hub is old, not the
agent's client — so it gets its own sentence rather than a reworded one.

## What is deliberately not in this step

**FR-008 — the unknown-command hint.** It is the requirement that addresses the failure that
actually happened, and it is the one with an open question: the unknown-command path runs
before any hub is contacted, so decorating a typo must not cost a request. The answer is a
cached last-seen hub version, and caching is a larger change than the rest of this mission
put together.

Shipping FR-001–007 without it is worth doing: `doctor` is what an agent runs when something
is wrong, and it currently stays silent about the most likely cause. FR-008 makes the *first*
encounter informative; this makes the *investigation* informative, and the investigation is
where somebody already suspects a problem.

Recorded as the next step rather than as done.

## Work

1. `staleness.standing()` — the direction, not just the boolean.
2. `doctor` notes the hub version and prints whichever notice applies.
3. Tests, including a matched pair printing nothing.
