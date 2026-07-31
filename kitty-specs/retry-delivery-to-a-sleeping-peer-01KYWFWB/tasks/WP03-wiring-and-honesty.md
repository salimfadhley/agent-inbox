---
work_package_id: WP03
title: 'Wiring, lifecycle, and where the outcome is visible'
dependencies:
- WP02
requirement_refs:
- FR-007
- FR-008
- FR-009
- NFR-002
tracker_refs: []
planning_base_branch: kitty/mission-retry-delivery-to-a-sleeping-peer
merge_target_branch: kitty/mission-retry-delivery-to-a-sleeping-peer
branch_strategy: Planning artifacts for this mission were generated on kitty/mission-retry-delivery-to-a-sleeping-peer. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into kitty/mission-retry-delivery-to-a-sleeping-peer unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
- T014
- T015
phase: Phase 3 - Honesty
agent: python-pedro
history:
- at: 2026-07-31T16:40:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/house.py
create_intent:
- tests/test_retry_lifecycle.py
execution_mode: code_change
owned_files:
- src/agent_inbox/house.py
- tests/test_retry_lifecycle.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP03 – Wiring, lifecycle, and where the outcome is visible

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro`
- **Role**: `implementer`
- **Agent/tool**: `python-pedro`

If no profile is specified, run `spec-kitty agent profile list` and select the best match
for this work package's `task_type` and `authoritative_surface`.

---

## Objective

Make the queue part of a running hub, make it **stop honestly** when the hub does, and
leave a trace an operator can read.

**This package is what makes an in-memory queue acceptable rather than irresponsible.**

## Context: the bargain C-001 struck

The queue is in memory, by deliberate choice, as the smallest first slice. The mission spec
permits that on one condition, which is now yours to keep:

> the queue survives a restart, **or it is honest that it does not** — a queue that silently
> empties on deploy is worse than no queue, because the sender was told `queued`.

We deploy on **every release**. So the restart case is not a rare edge; it is a scheduled
event. A sender told `queued` at 14:10 and a deploy at 14:12 must not leave that promise
hanging.

## Subtasks

### T011 — Build the queue into `House`

`House.__init__` already takes `deliver=None`. Wrap whatever it is given in
`RetryingDelivery`, and have `send` mint a `queued` receipt when `deliver` raises `Queued`.

`House.send` already splits local from remote and already stores the local copy before
attempting any delivery. **Do not disturb that order** — FR-009 depends on it: queueing
changes when a message arrives elsewhere, never whether the sender keeps their own copy.

A `House` built without a delivery collaborator must keep refusing remote recipients exactly
as it does today. Retrying is not a reason to soften that: a send that succeeds and reaches
nobody is still the worst failure shape available.

### T012 — Fail outstanding deliveries on close

`House` is an async context manager. On close, **fail everything still queued** rather than
letting the tasks die with the loop.

Not merely cancelling: the queued item's final state must become `failed`, with a reason
saying the hub stopped while it was waiting. The difference matters because `queued` is a
promise, and a process that exits holding promises has lied.

Cancel the tasks too — a close that hangs waiting for a five-minute backoff is its own bug.

### T013 — `@local` never enters the queue: the removal proof for FR-007

`split_recipients` guarantees `@local` never leaves the machine. That guarantee is
structural today. The queue must not become a second route around it.

**Passes trivially if the queue is never reached at all.** Prove it by removal: write the
test so a *remote* recipient in the same send demonstrably does queue, then assert the
`@local` one did not. Now remove the split and watch it fail.

### T014 — Audit-log the outcome

Write the final outcome — delivered after N attempts, or gave up — to the existing audit
log.

**This is the only place a late outcome becomes visible.** Receipts are returned at send
time and not persisted, so once `House.send` returns, nothing else records that a queued
message later arrived.

**The sender is not notified, deliberately.** Pushing a later outcome to a client is the
`the-hub-can-tell-a-client-mail-has-arrived` mission. Building a second notification path
here is the duplication ADR 0005 exists to prevent.

Note in the log line how many attempts it took. "Delivered on attempt 4" is the evidence
that the retry window is set sensibly; if everything succeeds on attempt 1 or fails at 6,
the backoff schedule is wrong and nobody will otherwise know.

### T015 — Does our own inbox de-duplicate a retried activity?

The mission's one open question. An attempt can fail *after* the peer received it — a
timeout on a POST that in fact succeeded is indistinguishable, from our side, from one that
never arrived. Retrying then delivers twice.

`FederatedDelivery` builds the activity id as `{public_url}/act/{record.id}` — derived from
the record, therefore **identical across attempts**. A receiver that de-duplicates on
activity id already handles this.

Using the two-hub federation harness, deliver the same activity twice and assert the
recipient has one copy.

**If it produces two copies, stop and raise an issue.** That is a defect in the receiving
half, and the fix belongs there — not a compensating hack in the sender. Report it; do not
widen this package to fix it.

## Definition of Done

- [ ] A hub retries in normal operation, end to end
- [ ] Closing a `House` with mail queued marks it failed, and close does not hang
- [ ] `@local` provably still cannot be queued, proved by removal
- [ ] Outcomes appear in the audit log with an attempt count
- [ ] The duplicate question is answered by a test, either way
- [ ] `pytest`, `ruff`, `pyright`, `black` green — capture each exit code separately

## Reviewer guidance

Ask one question first: **what happens to a queued message when this process exits?** If the
answer is anything other than "it is failed, and the log says why", the package is not done,
regardless of what the tests report.
