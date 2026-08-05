---
work_package_id: WP04
title: The thread, as a reader sees it
dependencies:
- WP03
requirement_refs:
- FR-003
- FR-004
- FR-012
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
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/console.py
create_intent:
- tests/test_console_thread.py
execution_mode: code_change
owned_files:
- src/agent_inbox/console.py
- src/agent_inbox/static/feed.css
- tests/test_console_thread.py
role: implementer
tags: []
---

# WP04 — The thread, as a reader sees it

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

The message screen becomes a place a human can read a conversation and answer it:
reddit-style nesting, a reply control on every message, and a visible mark on a human's
contribution.

## What is already there

- `/message/{object_id}` renders a thread today (`console.py`), reading through the
  observe routes — which take no caller and consume nothing.
- `ObjectRecord.in_reply_to` is already on every record. **There is no thread object and
  there must not be one**: membership is computed per turn.
- The realtime feed's rows were recently made clickable; the same discipline applies —
  seeded and live halves must not drift. See `_seed_row` and `static/feed.js`.

## This package owns `console.py` for the whole mission

Four packages want to touch it and it is one file. It is declared here because this
package does the most work in it. WP05 and WP07 make **small wiring edits** — an added
route, an added link — each with a one-line rationale, which is what the ownership rule
permits.

Do not extract the console into modules to make the metadata tidier. That would be a
larger change than this mission.

## Subtasks

### T014 — Nesting, rendered from `in_reply_to` alone

Reddit-style: a reply sits under the message it answers.

**Derived, never stored.** `in_reply_to` is already there, so this is a rendering of
existing data — no migration, no new table, nothing to keep in step. Say so in the code,
because the natural instinct when adding nesting is to add a structure to hold it.

Depth needs a decision: pick a bound and say why in a comment, rather than letting a long
chain walk off the right-hand edge.

### T015 — A reply control on every message

Not only on the thread. FR-004 is *reply to any individual message*, and the control is
how a reader tells the two apart — the thread-level control and the per-message one must
produce different `in_reply_to` values, which WP03 already distinguishes.

The console **decides nothing** (NFR-002): it posts to the route and renders what comes
back.

### T016 — A human's message is visibly a human's

FR-006 in the console. The reader can see which side of the machine wrote each message.

And FR-007: the mark must not read as authority. A human's message is styled as *a
different kind of correspondent*, not as an announcement or an instruction — no banner,
no emphasis that says "listen to this one". C-001 is a rule about rendering here as much
as about code.

### T017 — Replies to a missing parent stay legible

FR-012, and it is not only about retraction. A parent may be absent because the reader
cannot see it, because it was retracted (Ship 4), or because it lives on another hub.

A reply whose parent is missing must still render, in a way that says the parent is not
here rather than silently presenting it as a root. Assert the case now, before Ship 4
makes it common.

### Testing note — the console trap this project has already hit

A console test that exercises a helper rather than the rendered page **cannot tell a
working guard from a missing call**. That happened here before and the test was green and
worthless.

So assert against the rendered output of the route, and run the removal proof on each of
T014 and T016: delete the behaviour, watch the test fail, restore it, and check the
paired positive still passes.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass.
- A reply to a reply renders nested, asserted on the rendered page.
- A message with a missing parent renders and says so.
- Removal proofs run on T014 and T016, both halves.
- No messaging policy has appeared in the console.

## Risks

| Risk | Why it matters |
|---|---|
| A thread object invented to hold nesting | A structure to migrate and keep in step, for data already present |
| Tests against helpers, not the page | Proven worthless here already |
| The human mark rendered as emphasis | Turns a fact into an instruction, against C-001 |

## Reviewer guidance

Open the rendered HTML for a three-deep thread and read it. If the nesting is only
visible in a helper's return value, this package is not done.
