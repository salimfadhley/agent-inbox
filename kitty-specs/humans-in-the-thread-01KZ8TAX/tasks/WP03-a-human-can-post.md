---
work_package_id: WP03
title: A human can post, to a thread and to a message
dependencies:
- WP02
requirement_refs:
- FR-003
- FR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T010
- T011
- T012
- T013
agent: python-pedro
history:
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent:
- tests/test_human_posting.py
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- src/agent_inbox/house.py
- tests/test_human_posting.py
role: implementer
tags: []
---

# WP03 — A human can post, to a thread and to a message

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

The routes and the core. A signed-in human posts to a thread, or to **one message** in
it, and the result is attributed to that human.

No rendering here — WP04 owns the screen. This package is what the screen will call.

## What is already there

- `Mailbox.send()` and `Mailbox.reply()` exist and already carry `in_reply_to`.
- `Mailbox.thread()` already walks `in_reply_to`, so membership is computed, not stored.
- The console reads through `/observe/*`, which **takes no caller and consumes nothing**.
  That is observation. This package adds *acting*, which is a different thing and must
  carry an identity.

## The decision you are implementing

**A human is a real identity, not the console speaking for them.**

Two cheaper options were rejected in discovery and neither may creep back in:

- the `console` agent sending on a human's behalf — which makes every operator
  indistinguishable from one shared robot;
- letting the human speak *as* the agent whose page they are on — which is
  impersonation, and is the exact thing the observe routes were built to remove.

## Subtasks

### T010 — A human posts to a thread, as themselves

FR-003. The message is attributed to the human, by the same path any message takes.

"The same path" is load-bearing: this must not become a parallel send with its own rules
about recipients, groups or delivery. If the existing path cannot carry it, that is worth
reporting rather than routing around.

### T011 — A human replies to one message, and it nests

FR-004. Replying to a **specific** message sets `in_reply_to` to that message, not to the
thread's root.

The distinction between T010 and T011 is exactly `in_reply_to`, and it is the whole of
what makes reddit-style nesting possible in WP04. Assert both, and assert they differ —
a route where both produce the same record would satisfy a careless test of either.

### T012 — The console decides nothing about any of it

NFR-002 and ADR 0005. Every action goes through the API; the console holds no policy.

Concretely: who may post, what they may post to, and what the message looks like are all
settled here. A console that computed any of it would be a second implementation of a
messaging rule, which is the thing ADR 0005 exists to prevent.

### T013 — A human never sends as an agent

C-002, as a negative test. The attribution must be the signed-in human's, and there must
be no parameter, header or body field by which a caller can choose to be somebody else.

Try it in the test — construct the request that would impersonate, and assert it is
refused or ignored. A constraint nobody attacked is a constraint nobody tested.

## Out-of-map edits

WP06 will add a retraction route to `api.py`, which this package owns. That is expected
and permitted with a one-line rationale in that package's commit.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass.
- Posting to a thread and posting to a message produce records that differ **only** in
  `in_reply_to`, and a test asserts the difference.
- An attempted impersonation is refused, asserted directly.
- No messaging policy has moved into the console.

## Risks

| Risk | Why it matters |
|---|---|
| A parallel send path for humans | Two implementations of delivery; they will disagree |
| `in_reply_to` set to the thread root for both cases | Nesting becomes impossible and WP04 cannot tell |
| Impersonation left untested | C-002 becomes an intention |

## Reviewer guidance

Ask what happens if a human posts to a thread they cannot see. The answer should come
from the same visibility rule that governs everything else, not from a new one written
here.
