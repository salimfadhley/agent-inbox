---
work_package_id: WP03
title: Three routes that take no caller
dependencies:
- WP01
- WP02
requirement_refs:
- FR-001
- FR-002
- FR-003
- FR-004
- FR-005
- FR-020
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T009
- T010
- T011
- T012
- T013
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent:
- tests/test_observe_events.py
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_observe_events.py
role: implementer
tags: []
---

# WP03 — Three routes that take no caller

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

Serve the hub-wide stream, a bounded snapshot, and the observed outbox — all three as
`/observe/*` routes, which means they take no caller and consume nothing.

## Context

The existing per-actor stream is `Api.events` at `api.py:989`, registered around
`api.py:1872`. **Read it before writing anything.** It carries a comment recording a real
bug:

> Registered *inside* the generator — an earlier version registered above and leaked a
> slot when the response was never iterated.

Copy that shape. Registering the listener above `stream()` looks tidier and leaks a
listener slot for every response the client never reads.

The `/observe/*` routes sit at `api.py:2072–2086`, all `guards=[guard_enforce]`.
`guard_enforce` (~`api.py:1599`) is a no-op unless the hub enforces; when it does, it
requires *a* valid credential rather than a particular one.

## Subtasks

### T009 — `GET /observe/events`

Hub-wide SSE, subscribing to WP01's hub-wide subscriber kind. Mirror `Api.events`:
capacity check before streaming, `TooManyListeners` handled inside the generator,
keep-alive comment frames on the same interval, `mail` events carrying
`Arrival.as_event()`, and `finally:` closing the subscription.

**Reuse `Arrival.as_event()` unchanged.** Do not add a direction field — direction is a
property of the viewer, not of the message, and baking it in is what would stop one event
serving both the hub-wide feed and both halves of an agent page (plan §2).

### T010 — `GET /observe/recent`

A `Collection` of the most recent arrivals, newest last, so a page can fill before its
first event and after a reconnect.

**The bound belongs to the API, not the caller.** A caller-supplied limit with no ceiling
is a whole-store dump wearing a small name. If you accept a parameter at all, clamp it.

### T011 — `GET /observe/outbox/{name}`

Wraps `House.observe_outbox` from WP02. Same `Collection` shape as
`/observe/mailbox/{name}`, same guard, same name resolution via `self.wire.name_from`.

### T012 — Registration, keep-alives, capacity

Register all three beside the existing observe routes with `guards=[guard_enforce]`.
Capacity refusal on the stream matches the per-actor route's behaviour, including its
status and message.

### T013 — Tests

In `tests/test_observe_events.py`:

- Under enforce, each of the three refuses without a credential and answers with one.
- **Consuming nothing**: read all three, then assert every unread count is unchanged.
- The stream delivers an arrival addressed to *any* actor.
- `/observe/recent` is bounded even when the caller asks for more.
- A listener slot is released when the response is never iterated — the regression the
  per-actor route already carries a comment about.
- An unknown event type on the wire is ignored rather than raising, so the hub can add
  one later (FR-020).

## Definition of Done

- Three routes, all guarded, none consuming.
- The bound on `/observe/recent` is enforced server-side and tested.
- No listener slot leaks.
- The four gates pass.

## Reviewer guidance

Diff `Api.events` against the new hub-wide handler. They should differ only in *which*
subscription they open. Any other difference is either a bug in the new one or an
improvement that belongs in both.
