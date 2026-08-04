---
work_package_id: WP05
title: One connection, however many people are looking
dependencies:
- WP04
requirement_refs:
- FR-006
- FR-017
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T018
- T019
- T020
- T021
- T022
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/relay.py
create_intent:
- src/agent_inbox/relay.py
- tests/test_relay.py
execution_mode: code_change
owned_files:
- src/agent_inbox/relay.py
- tests/test_relay.py
role: implementer
tags: []
---

# WP05 — One connection, however many people are looking

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

A new module, `src/agent_inbox/relay.py`: the console holds **one** upstream stream to
the hub and re-emits it to its own subscribers.

## Why a relay exists at all

The console and the API are different origins. A browser `EventSource` pointed at the API
would need CORS plus cross-origin credentials, and would make every viewer a hub listener.
Relaying keeps `connect-src 'self'` standing, keeps the console a plain client, and makes
N operators cost the hub one listener.

It is a new module rather than part of `console.py` because it is not a page, and because
`console.py` is owned by WP07 — two packages cannot own one file.

## The requirement this package can quietly lose

**FR-016: an idle feed and a dead one must be distinguishable.** The browser sees only
what the relay tells it. If the relay's state is something the page has to *infer* — "no
events for a while, probably fine" — then a hub that has gone quiet and a connection that
has died look identical, and the feature's whole claim is false.

So the relay **publishes** its state. It is not deduced downstream.

## Subtasks

### T018 — One held upstream connection

Open the hub-wide stream via `HubClient` (WP04), parse with the existing `SseParser`, and
hold it. One connection per console process, not one per subscriber.

### T019 — Fan-out to console subscribers

Each browser subscriber gets its own queue; an upstream event goes to all of them. A slow
or vanished subscriber must not stall the others or the upstream read.

### T020 — The three-state machine

Exactly three named states: **open**, **reconnecting**, **lost**. Every transition is
published to subscribers as an event in its own right, distinct from `mail`.

Do not add a fourth state meaning "probably fine". Do not let the absence of events imply
anything.

### T021 — Reconnect with backoff

On a dropped upstream, move to `reconnecting`, retry with bounded exponential backoff, and
return to `open` on success. Prolonged failure is `lost` — and `lost` is a state the page
displays, not a silence it must interpret.

### T022 — Tests, on a driven fake stream

In `tests/test_relay.py`. **No sockets and no wall-clock sleeps** — the test drives the
fake stream directly, as `tests/test_wake_stream.py` does for the waiter.

- Ten subscribers, one upstream connection. Assert the count, because NFR-001 is the
  reason this module exists.
- An upstream event reaches every subscriber.
- A subscriber that goes away does not stall the rest.
- Killing the upstream publishes `reconnecting`, then `lost`; restoring it publishes
  `open`.
- **The paired positive**: an upstream that is merely *quiet* stays `open` and publishes
  nothing. Without this, a relay that reported `lost` constantly would pass every test
  above.

**Run the removal proof**: delete the state publication, watch the state tests fail,
restore it, watch them pass — and confirm the quiet-stays-open test held throughout.

## Definition of Done

- One upstream connection regardless of subscriber count, asserted.
- Connection state is published, never inferable.
- Tests need no socket and no real time.
- The four gates pass.

## Reviewer guidance

Look for any place a subscriber could conclude health from the absence of a message. That
is the bug this package exists to prevent, and it will not announce itself.
