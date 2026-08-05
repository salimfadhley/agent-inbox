---
work_package_id: WP04
title: The server descriptor
dependencies: []
requirement_refs:
- FR-009
- FR-010
tracker_refs:
- '44'
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. Completed changes merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T015
- T016
- T017
- T018
agent: python-pedro
history:
- at: '2026-08-05T08:40:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent:
- tests/test_descriptor.py
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_descriptor.py
role: implementer
tags: []
---

# WP04 — The server descriptor

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`GET /.well-known/agent-inbox` — unauthenticated, carrying what a prospective peer needs
to compatibility-check us before either side commits.

## What exists

`/.well-known/nodeinfo` (`api.py:1741`) and `/.well-known/webfinger` (`:1750`) are
already served. This is a third sibling, not a replacement for either.

## It is served even when federation is off, and that is the interesting decision

Decision `01KYN7QX8706MRGW27FF2E13N5`.

Requiring federation to be *enabled* before answering creates a **bootstrap deadlock**:
hub A cannot compatibility-check hub B until B enables, and B cannot check A until A
enables. Two fresh hubs could never peer.

The disclosure objection turns out to be empty. `GET /` already publishes
`"federates": false` to anyone, unauthenticated, today — so a descriptor served while
disabled tells a stranger nothing they cannot already learn.

## Subtasks

### T015 — The route

Software, version, base URL, `title`, `description`, mode, capabilities, supported
schemes, public key metadata. Unauthenticated.

### T016 — What it must not carry

FR-010, and this is the part to test hardest: **no actor data, no counts, no operator
information, and no hub `name`.**

The `name` exclusion is easy to get wrong because it feels like identity. Decision
`01KYMQ4GNS4B1PRD6WJ6W75DRG`: the hub `name` never crosses the wire. Federated identity
is the **domain**; the name is local and friendly, and keeping it off every federated
surface is what keeps renaming free.

### T017 — Honest about the mode

It reports `disabled` when disabled. Saying nothing, or implying otherwise, would make a
compatibility check that cannot be trusted — which is worse than one that reports a
state the caller does not like.

### T018 — Tests

In `tests/test_descriptor.py`, written as **absences** (NFR-004):

- Served with federation off, and reports `disabled`.
- Served without authentication.
- Contains no actor name, no counts, no operator field, **and no hub `name`** — asserted
  by searching the whole serialised body, not by checking named keys, so a field added
  later cannot smuggle one in.
- **The paired positive**: the fields it is supposed to carry are present, so a
  descriptor that returned `{}` would not pass.
- Renaming the hub leaves the descriptor byte-identical.

## Definition of Done

- A prospective peer can check us before either side commits.
- Nothing in FR-010's exclusion list appears, proved by absence.
- Four gates green.

## Reviewer guidance

Assert on the serialised body rather than on keys. The exclusions are the requirement;
a key-by-key check passes a body that gained a field nobody reviewed.
