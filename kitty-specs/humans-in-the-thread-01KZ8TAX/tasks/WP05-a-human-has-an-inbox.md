---
work_package_id: WP05
title: A human has an inbox
dependencies:
- WP02
requirement_refs:
- FR-005
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T018
- T019
- T020
agent: python-pedro
history:
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/mailbox.py
create_intent:
- tests/test_human_inbox.py
execution_mode: code_change
owned_files:
- src/agent_inbox/mailbox.py
- tests/test_human_inbox.py
role: implementer
tags: []
---

# WP05 — A human has an inbox

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

An agent can address a human, and the human reads it where they already are.

The alternative — humans speak but cannot be spoken to — makes a thread a place where the
human's words appear and their replies do not arrive.

## This is much less work than it sounds

Because of WP01. **A human's inbox *is* their actor's mailbox.** There is no second store
and no second unread model, and there must not be one: a parallel inbox would need its
own delivery, its own read semantics and its own retention, all of which already exist.

If you find yourself writing a `HumanInbox`, stop — the merge in WP01 was supposed to
make that unnecessary, and if it did not, that is the thing to report.

## What is already there

- `Mailbox.peek()`, `unread_count()`, `read()`, `mark_read_for()` — the whole model,
  per caller.
- The observe routes take no caller and consume nothing. **Looking must stay free**
  (NFR-001).

## Subtasks

### T018 — A human's inbox is their actor's mailbox

Reached by signing in — that access is what the admin role now means (FR-001, delivered
by WP01).

No new storage. The test worth writing is the negative one: **assert that no second
unread model exists**, because the failure here is not a missing feature but a duplicated
one that drifts.

### T019 — Unread state, and looking still does not consume

FR-005 gives a human unread state "as any mailbox has". NFR-001 says looking still does
not consume.

These are not in tension, and the distinction is the one the console already draws:
**observing** a mailbox marks nothing; **reading your own** message does. A human gets
both, exactly as an agent does.

Assert NFR-001 has survived: viewing a thread through the observe routes marks nothing
read, **for the human or for anyone else**. This project has broken that boundary
before by adding a caller where there was none.

### T020 — An agent can address a human and it arrives

The end-to-end proof, and the premise for the other two.

An agent sends to a human by name; it arrives; the human sees it unread. Without this,
T018 and T019 could both pass against an inbox nothing can reach — a check that passes
because it has nothing to look at, which is the failure this project keeps meeting.

## Out-of-map edit

The console needs a route or link to reach this inbox. `console.py` belongs to WP04;
make the smallest edit that wires it up and record the one-line rationale in the commit.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass.
- An agent's message to a human arrives and shows unread.
- Observing marks nothing read, asserted after this change as well as before.
- No second unread model exists, asserted.

## Risks

| Risk | Why it matters |
|---|---|
| A parallel human inbox | Two delivery and read models that will drift |
| NFR-001 quietly broken | The console starts consuming other agents' mail by looking |
| T018/T019 passing against an unreachable inbox | Vacuous — hence T020 |

## Reviewer guidance

Ask where a human's unread count comes from. If the answer is anywhere other than the
same place an agent's comes from, the merge did not do its job.
