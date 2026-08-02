---
work_package_id: WP03
title: The words follow
dependencies:
- WP02
requirement_refs:
- FR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T012
- T013
agent: python-pedro
history:
- at: '2026-08-02T20:55:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: doc/
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/cli.py
- doc/interrupting-an-agent.md
role: implementer
tags: []
---

# WP03 — The words follow

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

The documentation and the CLI help stop describing a poll loop, because it is no longer
one.

## Context

This is not tidying. `wake.py`'s module docstring and `cli.py`'s `--wait` help become
**false** the moment WP02 lands, and a false docstring in a fail-silent path is worse than
none: it is the thing the next person reads instead of the code.

## Subtasks

### T012 — The prose stops saying the waiter polls

`wake.py`'s module docstring, and whichever of `doc/` describes the hook. Find them rather
than assuming — grep for "poll" across `doc/` and `src/`.

**The honest sentence is "holds the hub's event stream, and polls underneath it"**, not
"no longer polls". The floor is still there (FR-004), and claiming otherwise would be the
same overclaiming this mission's spec calls out in the harness-agnostic section. Say what
changed: the latency and the request count, not the guarantee.

If `doc/interrupting-an-agent.md` says `no-adapter` is the ordinary answer, that stays
true — this mission does not touch mid-turn interruption, and the page should not start
suggesting it does.

### T013 — `--wait`'s CLI help

`cli.py`'s help for `--wait` currently says "poll until new mail arrives; intended for
asyncRewake Stop hooks". Say what it now does, in one line, still fitting the help
formatting.

## Definition of done

- Nothing user-facing says the waiter polls for mail, except where it correctly says
  polling is the floor.
- `grep -rn "poll" doc/ src/agent_inbox/wake.py src/agent_inbox/cli.py` returns only
  sentences that are true.
- Four gates green.

## Reviewer guidance

Read the changed sentences cold, as somebody who has not seen this mission. Do they claim
push is the guarantee? They must not.
