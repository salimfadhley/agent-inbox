---
work_package_id: WP02
title: What an agent sent
dependencies: []
requirement_refs:
- FR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/mailbox.py
create_intent:
- tests/test_observe_outbox.py
execution_mode: code_change
owned_files:
- src/agent_inbox/mailbox.py
- src/agent_inbox/house.py
- tests/test_observe_outbox.py
role: implementer
tags: []
---

# WP02 — What an agent sent

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

The console can show what an agent *received* and has never been able to show what it
*sent*, because no such query exists anywhere in the stack. Add it, mirroring the
received-side query so closely that the two are obviously a pair.

## Context — what is actually there

This surprises people, so check it rather than assume it:

- `/actors/{name}/outbox` **is a POST for sending** (`api.py:784`). It is not a read of
  sent mail and never has been.
- `mailbox.py` has `observe_mailbox`, `observe_object`, `observe_thread`,
  `observe_reads`. **There is no sent-side query at all.**
- `Mailbox.observe_mailbox` (`mailbox.py:569`) loads every object from the store and
  filters in Python on `rules.recipients_of(...)`.
- `ObjectRecord.attributed_to` is the sender. `to` and `cc` hold names, and resolving a
  group to members is a rule rather than a storage concern.

The comment above the observe block states the invariant you must preserve: *"None of
them consumes. Watching an agent's mail must never mark it read, or the operator steals
what they were only trying to look at."*

## Subtasks

### T006 — `Mailbox.observe_outbox`

Everything one agent sent, newest last, filtering on `attributed_to`. Write it
**immediately beside `observe_mailbox`**, in the same shape, so the shared whole-store
scan is visible in one place rather than discovered twice.

Do not resolve groups or expand recipients — the sender is a single name, which makes
this the simpler half of the pair.

### T007 — `House.observe_outbox`

The delegate, matching the other four `observe_*` methods exactly.

### T008 — Tests

In `tests/test_observe_outbox.py`:

- An agent that sent two messages and received three yields exactly the two it sent.
- **The paired negative**: `observe_mailbox` for the same agent still yields the three it
  received. Without this, a query returning everything would pass the first test.
- Ordering matches `observe_mailbox`'s convention.
- **Consuming nothing**: unread counts are identical before and after. Assert it; do not
  reason about it.
- An agent that has sent nothing yields an empty result rather than raising.

## Definition of Done

- The sent side is queryable from `House`, and consumes nothing.
- `observe_mailbox` is untouched in behaviour, and its tests pass unmodified.
- The four gates pass.

## Risks

**NFR-006.** This inherits `observe_mailbox`'s whole-store scan. That is accepted and
recorded — but it must not add a *second* scan. If you find yourself loading objects
twice to answer one question, stop and simplify.

## Reviewer guidance

The two queries should read as siblings. If `observe_outbox` has a structure
`observe_mailbox` does not, ask why — divergence here is how the pair drifts apart later.
