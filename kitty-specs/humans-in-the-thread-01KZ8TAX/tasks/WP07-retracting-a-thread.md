---
work_package_id: WP07
title: Retracting a thread, and what a reader sees
dependencies:
- WP06
requirement_refs:
- FR-009
- FR-012
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T026
- T027
- T028
agent: python-pedro
history:
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/threads.py
create_intent:
- src/agent_inbox/threads.py
- tests/test_thread_retraction.py
execution_mode: code_change
owned_files:
- src/agent_inbox/threads.py
- tests/test_thread_retraction.py
role: implementer
tags: []
---

# WP07 — Retracting a thread, and what a reader sees

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

"Delete the thread" is **the same primitive applied to a set**, and a retracted message
reads `[deleted]` while keeping its place in the conversation.

## Not a separate mechanism

There is no thread *object* here — membership is computed per turn — so "delete the
thread" means retracting each message in the set the reader is looking at.

If this package grows its own permission test, its own audit format, or its own idea of
what a retraction is, it has gone wrong. It is a loop over WP06.

## Subtasks

### T026 — Retracting a thread is the primitive applied to a set

FR-009: by the **same path** as a single retraction.

Two things follow and both need asserting:

- **The permission test runs per message.** A human may retract anything on this hub, so
  a thread-wide retraction succeeds for them; an agent may retract only its own, so the
  same call over a mixed thread must retract theirs and refuse the rest rather than
  refusing everything or retracting everything.
- **Each retraction is audited separately** (FR-010). One audit entry saying "a thread"
  loses which messages were destroyed, which is the thing an audit is for.

Partial outcomes are therefore normal, not an error state. Report what was retracted and
what was refused; do not collapse it to a single success or failure.

### T027 — `[deleted]` in place, keeping position, sender and time

FR-008. The body goes; the record stays.

Reddit's convention, and it is the right one: the message keeps its position, its sender,
its timestamp and its `in_reply_to`, so the shape of the conversation survives the removal
of its content.

Rejected in discovery, and neither may creep back: **removing it from the store** (an
operator tidying up silently empties other agents' inboxes) and **hiding it from the
console only** (a button labelled delete that deletes nothing, which this project would
not ship).

### T028 — Replies beneath a retraction survive

FR-012. A reply to a retracted message still makes sense and still renders in place.

This is why T027 keeps `in_reply_to`. WP04 already asserted the missing-parent case
before retraction made it common — check that test still passes here rather than writing
a second one, and if it does not, that is the bug.

## Out-of-map edit

The console needs the thread-level control and the `[deleted]` rendering. `console.py`
belongs to WP04; make the smallest edit that adds them and record the one-line rationale
in the commit.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass.
- A thread-wide retraction by an agent over a mixed thread retracts theirs and refuses
  the rest, reporting both.
- Every retracted message has its own audit entry.
- A retracted message keeps position, sender, time and `in_reply_to`.
- WP04's missing-parent test still passes, unmodified.

## Risks

| Risk | Why it matters |
|---|---|
| A second permission test written here | The disagreement C-006 warns about, in the destructive path |
| One audit entry for a whole thread | Loses which messages were destroyed |
| All-or-nothing on a mixed thread | Either refuses a legitimate act or performs an illegitimate one |
| Rows removed rather than tombstoned | Silently empties other agents' inboxes |

## Reviewer guidance

Retract a thread containing one message you own and one you do not, as an agent. The
right outcome is *partial*, reported clearly. Anything else means the permission test
moved.
