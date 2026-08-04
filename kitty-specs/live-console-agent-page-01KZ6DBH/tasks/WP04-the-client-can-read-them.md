---
work_package_id: WP04
title: The client can read them
dependencies:
- WP03
requirement_refs:
- FR-003
- FR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T014
- T015
- T016
- T017
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/client.py
create_intent:
- tests/test_client_observe.py
execution_mode: code_change
owned_files:
- src/agent_inbox/client.py
- tests/test_client_observe.py
role: implementer
tags: []
---

# WP04 — The client can read them

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`HubClient` gains readers for the three new routes. Nothing else in the project talks to
the hub directly, and this package is what keeps that true (ADR 0005 — one core, every
client is a client).

## Context

`client.py` already has `observe_mailbox` (`client.py:1009`) as the model to follow, and
already knows how to hold a stream: `events_url` and `stream_headers` exist for the
per-actor stream, along with `SseParser` for the wire format. **Reuse all three.**

The consumer is WP05's relay, which is not written yet. Give it a clean seam.

## Subtasks

### T014 — `HubClient.observe_recent()`

Reads `/observe/recent`. Same error handling and return shape as `observe_mailbox`.

### T015 — `HubClient.observe_outbox(name)`

Reads `/observe/outbox/{name}`. Written beside `observe_mailbox` so the pair is visible.

### T016 — The hub-wide events URL

A property alongside `events_url` giving the hub-wide stream's address, reusing
`stream_headers` unchanged — the credential and the identity header are the same ones
every other call from this client already uses.

Do **not** add a second SSE parser. `SseParser` exists and is tested.

### T017 — Tests

In `tests/test_client_observe.py`:

- Each reader hits the expected path and returns the decoded collection.
- The hub-wide events URL is derived from the configured hub, not hard-coded.
- Credentials are sent — asserted, because a reader that silently works only against a
  non-enforcing hub would pass every other test here.
- A non-JSON body produces a `MailboxError` naming the content type rather than a raw
  `JSONDecodeError`. See #50: `doctor` currently prints a traceback when the hub returns
  HTML, which is the single most likely misconfiguration because the console is the URL
  a human bookmarks. **If fixing this properly reaches beyond these two files, do not
  widen the package — note it and leave #50 open.**

## Definition of Done

- Three readers, using the existing credential path and the existing parser.
- No new dependency.
- The four gates pass.

## Reviewer guidance

Check nothing here decides anything. A client method that filters, sorts or interprets is
a client making a messaging decision, which is the thing ADR 0005 forbids.

## After this package

**Ship 1 is complete.** Release, deploy to the hub, and prove it with
`agent-inbox verify-deployment` before WP05 begins. The console work is developed against
a live hub that already serves these routes.
