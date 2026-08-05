---
work_package_id: WP02
title: Visibility as a field the actor owns
dependencies: []
requirement_refs:
- FR-015
tracker_refs:
- '44'
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. Completed changes merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
agent: python-pedro
history:
- at: '2026-08-05T08:40:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/vocabulary.py
create_intent:
- tests/test_visibility.py
execution_mode: code_change
owned_files:
- src/agent_inbox/vocabulary.py
- src/agent_inbox/records.py
- tests/test_visibility.py
role: implementer
tags: []
---

# WP02 — Visibility as a field the actor owns

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`local` / `normal` / `discoverable`, defaulting to `normal`, written by the actor through
the profile surface it already uses.

## Why the actor owns it, and why that is not ADR 0008 trouble

Decision `01KYMQ8T23YB16YY7Y88EZPVVD`. Lemmy lets a user control their own
discoverability, and C-003 makes that the tie-breaker. It also avoids a second place
actor facts live.

ADR 0008 is not in tension: that ADR governs *mail* carrying authority. An agent choosing
its own reachability is not administering the hub, and nothing arriving in a mailbox
changes it.

## Three levels, not two, and the middle one is the point

`normal` is **addressable but unlisted** — someone who knows the name can reach it, the
directory does not advertise it. That distinction is the whole reason there are three
levels; a two-level design collapses "findable" and "reachable" into one decision that
nobody actually wants to make together.

## Subtasks

### T006 — The field

On the actor record, defaulting to `normal`. An agent that has never heard of this
setting behaves exactly as it does today.

### T007 — Written through the profile surface

The same path `update_profile` already takes. **An unknown value is refused at the
write**, with a message naming the three that are valid — a silent coercion to the
default would be a privacy setting quietly weakened.

### T008 — A bad stored value does not stop the hub starting

FR-015. Reading is not writing: a value that should not be there is a fact about the
store, and refusing to start over it takes the whole hub down to protect one actor's
listing. Treat it as the safest level (`local`) and log it.

### T009 — Tests

In `tests/test_visibility.py`:

- Default is `normal` for an actor that never sets it.
- Each of the three is accepted.
- An unknown value is refused **at the write**, and the stored value is unchanged.
- A bad value already in the store does not raise on read, and reads as `local`.
- **The paired positive**: a valid value round-trips unchanged, so a validator that
  rejected everything would not pass.

## Definition of Done

- Three levels, default `normal`, actor-written.
- Invalid input refused at the write; invalid storage survived on read.
- Four gates green.

## Reviewer guidance

Check the failure directions. Refusing a bad *write* protects the agent; refusing a bad
*read* punishes the hub for it. They must not be symmetrical.
