---
work_package_id: WP02
title: Three routes in, three out
dependencies:
- WP01
requirement_refs:
- FR-002
- FR-003
- FR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T007
- T008
- T009
- T010
- T011
- T012
phase: Phase 2 - the API
agent: python-pedro
history:
- at: '2026-08-02T12:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_auth_api.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP02 — Three routes in, three out

## ⚡ Do This First: Load Agent Profile

Load `python-pedro` via `/ad-hoc-profile-load` before reading further.

---

## Objective

One operator-only API for tokens, and **no surviving route that can mint one bound to an
agent**. The second half is the point: leaving a second way to mint is the thing the
mission exists to stop.

## Subtasks

### T007 — `POST /auth/tokens`

Body `{"label": "…"}`. Operator-only, as the three routes it replaces are. Returns the
secret **once**.

**An empty label is refused** (FR-002). A list of unlabelled tokens is a list nobody can
act on, and inventing a label for an operator who gave none puts a claim in a column that
is supposed to hold theirs. Refuse with a reason, do not invent.

Nothing about minting names an agent — no `actor` in the body, no actor in the response.

### T008 — `GET /auth/tokens`

Every token on the hub. Per token:

| Field | Is |
|---|---|
| `id`, `label`, `created`, `revoked` | as today |
| `lastUsed` | the date, or **null for never** — "never" and "a year ago" are different facts leading to different actions (FR-008) |
| `boundTo` | `null` for a shared token, a name for a legacy row (FR-006) |
| `admitted` | `[{name, firstSeen, lastSeen, uses}]`, most recent first (FR-005) |

`boundTo` and `admitted` must stay separate fields. One is what the row was created with;
the other is what the hub observed. Collapsing them is FR-010's failure in JSON rather than
in HTML.

### T009 — `DELETE /auth/tokens/{token_id}`

Revoking already takes effect on the next call — `resolve_token` raises `TokenRevoked`
first. What is new is honesty about consequence: the response says **which agents that
token had admitted**, so the operator learns what they have just cut off.

Revoked tokens stay listed and marked. A revoked token that vanishes takes the record of
what it did with it.

### T010 — Remove the three per-agent routes

`POST`, `GET` and `DELETE` on `/auth/agents/{name}/tokens…` go. Removed, not deprecated.

This is the irreversible half, and it breaks callers at once rather than degrading — which
is the right failure, but it has to be found now. The console calls these today; WP03 fixes
that. Expect the console's token screens to break in this package and be repaired in the
next, and say so in the commit rather than leaving somebody to discover it.

### T011 — Tests

`tests/test_auth_api.py`, rewritten. Operator-only on all three; the secret returned
exactly once; an empty label refused; revocation refusing on the next call; the removed
routes returning 404 — that last one is the proof that a second minting path is actually
gone rather than merely unused.

### T012 — Directive 4

One narrow question. The strongest: whether any request shape can still produce a token
bound to a single actor, by any route or field.

## Definition of Done

- The four gates pass.
- No route can mint a token bound to an agent, proved by the old paths returning 404.
- An empty label is refused rather than invented.
- `boundTo` and `admitted` are separate fields.
- Released and deployed to **both** hubs, proved with `verify-deployment`.

## Reviewer guidance

Ask what an operator can do with the response that they could not do before. If the answer
is "nothing", `admitted` is not being returned properly — that field is the entire reason
this API changed shape.
