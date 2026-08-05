---
work_package_id: WP06
title: 'Retraction: one primitive, two scopes'
dependencies:
- WP03
requirement_refs:
- FR-008
- FR-010
- FR-011
- FR-014
- FR-015
- FR-016
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T021
- T022
- T023
- T024
- T025
agent: python-pedro
history:
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/retraction.py
create_intent:
- src/agent_inbox/retraction.py
- tests/test_retraction.py
execution_mode: code_change
owned_files:
- src/agent_inbox/retraction.py
- src/agent_inbox/store.py
- src/agent_inbox/sqlite_store.py
- tests/test_retraction.py
role: implementer
tags: []
---

# WP06 — Retraction: one primitive, two scopes

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`retract(object_id, by)` — the same call whoever makes it. What differs is only the
permission test:

- an **agent** may retract a message **it sent**;
- a **human** may retract **anything on this hub**.

**This is the only destructive act in the mission.** It ships last, on purpose: it is far
easier to reason about once identity is settled and there are real threads with real
humans in them to test against.

## Why one primitive and not two

The parent federation mission's C-006 said it better than this spec does:

> If the decision is made in two places they will disagree.

A disagreement here is not a disclosure — it is somebody's words destroyed by a caller
who should not have been able to. Two entry points with two permission tests is exactly
how that happens.

## The fediverse settled this, and we match it

Checked during discovery rather than recalled. Lemmy has **two acts**, and our two scopes
land on them exactly:

| Lemmy | here | who | scope |
|---|---|---|---|
| `delete` | an agent retracting its own | the author | their own message |
| `remove` | a human retracting anything | the operator | anything on this hub |

Arriving at a convention the fediverse settled years ago, from a different direction, is
the outcome the charter asks for. **What we are building is `remove`**, and Lemmy's
local-only behaviour is the behaviour we want (FR-015).

One departure, recorded rather than silent: we tombstone **immediately** rather than
after thirty days. Lemmy's delay exists to let an author change their mind; a retraction
here is often an operator act on somebody else's message, and a grace period would leave
a message the operator believes is gone readable for a month.

## Subtasks

### T021 — `retract(object_id, by)` — one primitive

One function, consulted by every path that needs it. Not a helper each caller wraps
differently.

**The test that matters is not that it returns the right answer.** It is that no second
implementation exists — include a test that fails if the permission decision is made
anywhere else, by searching for the shape of a re-derivation rather than trusting review.

### T022 — Two scopes, and a refusal that says which power is missing

FR-014 and FR-016.

An agent retracting **another agent's** message is refused **on every surface** — asserted
as a negative test, not left to a console that happens to offer no button. A console
without a button is not a rule.

The refusal **names which power the caller lacks** (FR-016). "Refused" tells an agent
nothing it can act on; "you may retract your own messages, not another agent's" does.

### T023 — The audit entry is written *before* the body goes

FR-010 and C-003: who did it, when, and which message.

**Order is the requirement.** A retraction that fails halfway must leave a trace of
itself; write the audit first and a crash between the two steps leaves an audited
non-retraction, which is recoverable. The other order leaves a destroyed body nobody can
account for.

C-003 also gives the reason this matters beyond bookkeeping: an agent must not be able to
send something and then erase that it did.

### T024 — Retraction is local, and nothing claims otherwise

FR-015. A copy already delivered to a peer hub is **not** withdrawn, and nothing in the
API, the console or the audit entry may imply it was.

Assert the wording as well as the behaviour. A message that says "deleted everywhere"
while doing something local is worse than one that says nothing.

**One consequence is deferred, and is recorded so it is not lost:** Lemmy's
author-`delete` *does* eventually federate, as an edit, while admin-`remove` does not. So
"an agent retracts its own message" is the case where propagating a retraction is
defensible — it is the author's own words — and FR-015's local-only rule may deserve an
exception it does not have today. **Not decided here**; it belongs to
`federated-identity-and-trust`, which owns what crosses a hub boundary.

### T025 — Retracted for everyone, not per-recipient

FR-011. A retracted message does not stay readable for some recipients.

The trap is the read model: a message already delivered to several mailboxes must not be
retracted in one and intact in another. Test with two recipients, and assert on both.

## Out-of-map edit

The retraction route belongs in `api.py`, which WP03 owns. Add it there with a one-line
rationale in the commit — this is the sanctioned case, not a licence to reshape the
module.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass.
- An agent retracting another's message is refused, and the refusal names the missing
  power.
- The audit entry survives a retraction that fails after it is written.
- Two recipients, one retraction, both see `[deleted]`.
- A test fails if the permission decision is re-derived anywhere.
- Nothing anywhere claims a remote copy was withdrawn.

## Risks

| Risk | Why it matters |
|---|---|
| Two entry points with two permission tests | Somebody's words destroyed by a caller who should not have been able to |
| Audit written after the body is replaced | A destroyed message nobody can account for |
| Per-recipient retraction | FR-011 broken in the way hardest to notice |
| An implied claim of remote deletion | Promises something federation cannot deliver |

## Reviewer guidance

Ask: **where is the permission decision made, and how do you know that is the only
place?** If the answer is "I looked", T021 is not done.

Then check the order of the two writes in T023 by reading them, not by reading the
docstring.
