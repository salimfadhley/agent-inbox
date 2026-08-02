---
work_package_id: WP02
title: The waiter listens
dependencies:
- WP01
requirement_refs:
- FR-002
- FR-004
- FR-006
- FR-007
- FR-009
- NFR-001
- NFR-002
- NFR-003
- NFR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
- T010
- T011
agent: python-pedro
history:
- at: '2026-08-02T20:55:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/wake.py
create_intent:
- tests/test_wake_stream.py
execution_mode: code_change
owned_files:
- src/agent_inbox/wake.py
- tests/test_wake_stream.py
role: implementer
tags: []
---

# WP02 — The waiter listens

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`_wait_for_wake` sleeps on the reader instead of on the clock. Nothing else about it
moves — same lock, same watermark, same `wake_response`, same fail-silent wrapper.

## Context

Today the loop ends each pass with `sleep(min(poll_interval, remaining))`, where `sleep` is
an injected `Sleeper`. That injection point is why the existing tests can run eight
simulated hours instantly, and it is the seam this whole mission turns on: replace the
*implementation* passed in, not the loop.

**The stream can only ever shorten a sleep.** If the reader cannot connect, dies, or
connects to a hub that then says nothing, what is left is today's poll loop with a bounded
interval. That property is what makes it impossible for this change to make things worse,
and every subtask below either uses it or proves it.

## Subtasks

### T006 — The loop sleeps on the reader, and the reader is closed

Start the reader **after** the single-waiter lock is taken — the lock is what stops one
connection per turn (FR-009), and starting before it would open a connection only to
discover another waiter already holds the project.

Hand the reader's `wait` in as the sleeper. Close it in the `finally` that already releases
the lock, so it closes on a wake, on timeout, and on an error alike (FR-007).

An arrival must reach `_run_once` by exactly the path a poll tick takes (FR-002) — the
event is a prompt to re-check, and `wake_response` is still the only thing that decides
what is said (FR-003).

### T007 — The interval lengthens, and stays bounded

With a stream held, five seconds is pointless. The plan proposes sixty; justify it or
change it, and say which in a comment.

It must stay **bounded** (FR-006). A stream that connects and then silently delivers
nothing — a buffering proxy is the ordinary cause — looks exactly like a healthy one from
this side, and the poll underneath is the only thing that catches it.

If the reader is not streaming, the interval must stay at today's value. A hub with no
event route must not get a slower wake than it gets today.

### T008 — The existing wake tests pass unmodified

**The subtask that matters most.** The existing tests inject `sleep` and never mention a
stream, so they exercise the no-stream path and prove the decision did not move (SC-004).

Run them. Do not edit them. If one needs editing to pass, the change went further than
intended — stop and look at why, rather than adjusting the test to agree with the code.

### T009 — Removal proof for FR-004

Delete the fallback poll from the loop and a hub with no event route must stop waking
entirely. If it still wakes, the thing you deleted was not the fallback and the test proves
nothing.

Then restore it, and the paired positive — that same hub waking — must pass again.

### T010 — Removal proof for FR-006

Make the interval unbounded and a stream that connects, then says nothing, must stop
waking. Restore the bound and it must wake again.

This is the buffering-proxy case, and it is the reason the interval cannot simply become
"however long the wait has left".

### T011 — Directive 4

An outside model reviews this before the mission closes. One narrow question, not a general
audit. Candidates, pick the sharpest:

- can the reader thread outlive the process, or hold the CLI open at exit?
- is there any interleaving of `close()` and a signal in flight that drops a wake?
- can a stream that connects and immediately drops produce a reconnect spin, given the
  settle logic was reused rather than the loop?

## Definition of done

- An arrival wakes the loop without waiting out the interval, proved with a fake stream.
- With no stream, behaviour is today's, proved by today's tests unmodified.
- Both removal proofs fail without their guard and pass with it.
- Four gates green, then Directive 4.

## Reviewer guidance

The lock ordering (T006) and T008 are where a mistake would hide. Everything else announces
itself.
