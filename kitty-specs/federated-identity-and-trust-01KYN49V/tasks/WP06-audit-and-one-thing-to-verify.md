---
work_package_id: WP06
title: Audit, and one thing to verify
dependencies:
- WP01
requirement_refs:
- FR-020
- FR-023
tracker_refs:
- '44'
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. Completed changes merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T024
- T025
- T026
agent: python-pedro
history:
- at: '2026-08-05T08:40:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation.py
create_intent:
- tests/test_federation_audit.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation.py
- tests/test_federation_audit.py
role: implementer
tags: []
---

# WP06 — Audit, and one thing to verify

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

Every administrative action and every automated refusal recorded — and one requirement
checked rather than built.

## Where this lives

`src/agent_inbox/federation.py`, **not** `house.py` — which WP03 owns. Two packages
cannot own one file, and the ownership check exists because two agents editing the same
file in parallel lanes collide. Federation's own audit belongs beside federation anyway.

## Subtasks

### T024 — Audit the administration and the refusals

Timestamp, the acting human where there is one, action, target, before and after **where
safe**, and the reason.

**The automated refusals matter as much as the deliberate acts.** An operator asking
"why did that peer not get my mail" is asking about something nobody typed, and an audit
log that records only human actions cannot answer it.

### T025 — It never carries a secret

No key, no token, no message content. Append-only.

Assert as an absence over the whole serialised entry, not by checking named fields: the
point is that nothing sensitive is present, and a field-by-field check passes an entry
that gained one.

### T026 — Verify FR-020 rather than building it

The spec asks that the federation inbox stop answering `501 Not Implemented` and stop
citing superseded missions 0024 and 0025 in its body.

**Neither `501` nor those numbers appear in `api.py` today.** So this may already be
satisfied — check first. If it is, close it with the evidence; a requirement satisfied
before you start should be closed, not re-satisfied.

If it is not: `403` with a reason. `501` says *this software cannot*, which becomes false
the moment this mission ships; a hub in `disabled` mode is saying *this hub will not*,
and those are different sentences.

## Definition of Done

- Administrative acts and automated refusals are both recorded.
- No entry carries a key, a token, or message content — proved by absence.
- FR-020 verified, and closed or fixed on the evidence.
- Four gates green.

## Reviewer guidance

Check that a refusal nobody typed produces an entry. That is the half that gets missed,
and it is the half an operator actually asks about.
