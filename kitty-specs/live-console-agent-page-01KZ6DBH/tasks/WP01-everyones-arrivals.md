---
work_package_id: WP01
title: Everyone's arrivals, not just one agent's
dependencies: []
requirement_refs:
- FR-001
- FR-002
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/notify.py
create_intent:
- tests/test_notify_hubwide.py
execution_mode: code_change
owned_files:
- src/agent_inbox/notify.py
- tests/test_notify_hubwide.py
role: implementer
tags: []
---

# WP01 — Everyone's arrivals, not just one agent's

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`Listeners` fans arrivals out **per actor**. A hub-wide feed needs every arrival
regardless of who it was addressed to. Add a second subscriber kind that gets all of
them, without disturbing the per-actor behaviour that the wake stream and the MCP server
already depend on.

## Context

`src/agent_inbox/notify.py` holds `Arrival` and `Listeners`. `Listeners` today keys
queues by actor and offers `max_listeners`, `count`, `count_for`, `by_actor`,
`at_capacity`, `full_message`, `open(actor)`, `close(actor, queue)`, `listening(actor)`
and `announce(actor, arrival)`.

The consumer you are enabling is `GET /observe/events` in WP03. You are not writing that
route; you are giving it something to subscribe to.

## The decision already made, and the one you must not undo

**Do not register a reserved actor name** (`"*"`, `"__all__"`, `"everyone"`) as the
hub-wide key. It requires no new code, which is its only merit. It also puts a value into
the actor namespace that is not an actor, so `count_for`, `by_actor` and `listening` would
each report it as one — and every future reader of those methods inherits a special case
nobody documented. Plan §1 rejects it explicitly.

Use a distinct collection for hub-wide queues, fed from the same `announce` call.

## Subtasks

### T001 — Hub-wide queue set beside the per-actor map

Add a container for hub-wide subscribers. It holds queues, not actors: there is no name
to key on, which is the whole point.

### T002 — `announce()` feeds both kinds from one call

An arrival is put on the addressed actor's queues **and** on every hub-wide queue. One
call site, so the two cannot drift apart — a hub-wide feed that misses arrivals the
per-actor feed sees would be the worst outcome here and the hardest to notice.

### T003 — Open and close, with the same capacity accounting

Hub-wide subscribers count towards `max_listeners` and `at_capacity` exactly as per-actor
ones do. A hub-wide listener is a held connection and costs the same.

### T004 — The reporting methods stay honest

`count_for(actor)`, `by_actor()` and `listening(actor)` describe *actors*. A hub-wide
subscriber must not appear in any of them, because it is not listening as anybody. If a
total is wanted, `count` is the method that means "all held connections".

### T005 — Tests, including the removal proof

In `tests/test_notify_hubwide.py`:

- Two actors receive mail; a hub-wide subscriber sees **both** arrivals.
- Each per-actor subscriber still sees only its own — the paired positive, without which
  the first test would pass on an implementation that broadcast everything to everyone.
- A hub-wide subscriber does not appear in `by_actor()` or in any `count_for()`.
- Capacity: hub-wide subscribers count towards the cap.
- Closing a hub-wide queue releases its slot.

**Run the removal proof.** Delete the hub-wide leg of `announce`, watch the fan-out test
fail, restore it, watch it pass — and confirm the per-actor test passed throughout, so you
have proved the fan-out rather than proved that breaking things breaks things.

## Definition of Done

- A hub-wide subscriber receives every arrival, whoever it was addressed to.
- Per-actor behaviour is unchanged, and the existing `notify` tests pass unmodified.
- No reserved name exists in the actor namespace.
- The four gates pass: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pyright`.

## Reviewer guidance

Check `announce` has exactly one place that decides who gets an arrival. Two code paths
that each decide would be the defect this package exists to avoid.
