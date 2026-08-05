---
work_package_id: WP05
title: The operator's CLI
dependencies:
- WP01
- WP02
requirement_refs:
- FR-003
- FR-019
- FR-021
- FR-022
- FR-024
tracker_refs:
- '44'
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. Completed changes merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T019
- T020
- T021
- T022
- T023
agent: python-pedro
history:
- at: '2026-08-05T08:40:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/cli.py
create_intent:
- tests/test_federation_cli.py
execution_mode: code_change
owned_files:
- src/agent_inbox/cli.py
- tests/test_federation_cli.py
role: implementer
tags: []
---

# WP05 — The operator's CLI

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

Enable, disable, peers, blocklist, status — from the terminal.

## Not a reduced version of a console

Decision `01KYN8T9HXADTFM3B2TK9DZH4X`. ADR 0005 says one API and every client is a
client, and the CLI is one — so this is the same capability reached from the surface an
operator already has. The console section is its own later mission, after #21 settles
where settings live.

## Subtasks

### T019 — `federation enable` / `disable`

Enabling wires to the existing `check_may_enable_federation()` rather than
reimplementing its rule (FR-002). A refusal names the reason: no public URL, or a hub
still called `local`.

### T020 — `peers add` / `remove` / `list`

`add` runs the flow from WP01 and reports `Ready` / `Warning` / `Failed` **with the exact
reason**. A `Warning` — typically a base-URL mismatch, which is the shape of *you typed
the wrong host* — requires explicit confirmation to proceed, and the warning text goes
into the audit entry (decision `01KYN7QVXF2ADJ1W0KHZ1X89MD`).

### T021 — `blocklist add` / `remove` / `list`

Stored-only. No environment equivalent, by decision.

### T022 — `federation status`

Shows which settings the deployment has fixed and which the operator controls. **Copy
what `config list` already does** — it reports each setting with its source, and that is
the pattern rather than a second way of saying "the environment governs this" (FR-019).

### T023 — The CLI decides nothing

NFR-003 and C-006. Every command goes through the API; none recomputes policy. Assert it:
a test that fails if the client evaluates the blocklist, the mode, or visibility itself.

Otherwise C-006 is broken from the client side, and the second implementation is the one
nobody thinks to look at.

## Definition of Done

- An operator can do all of it from a terminal.
- Nothing is decided client-side.
- A `Warning` cannot be accepted silently.
- Four gates green.

## Reviewer guidance

Look for any branch in the CLI that reaches a conclusion the hub should have reached. The
giveaway is a comparison against a peer list or a mode.
