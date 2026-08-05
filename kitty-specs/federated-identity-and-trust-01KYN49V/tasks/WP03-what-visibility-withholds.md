---
work_package_id: WP03
title: What visibility actually withholds
dependencies:
- WP01
- WP02
requirement_refs:
- FR-012
- FR-014
- FR-016
tracker_refs:
- '44'
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. Completed changes merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T010
- T011
- T012
- T013
- T014
agent: python-pedro
history:
- at: '2026-08-05T08:40:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/house.py
create_intent:
- tests/test_visibility_withholds.py
execution_mode: code_change
owned_files:
- src/agent_inbox/house.py
- src/agent_inbox/mailbox.py
- tests/test_visibility_withholds.py
role: implementer
tags: []
---

# WP03 — What visibility actually withholds

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

The directory lists `discoverable` only, and a `local` actor **does not resolve at all**.

This is the sharpest package in the mission and the one most likely to be done wrong.

## The failure mode, named so it can be avoided

**Filtering the directory is necessary and nowhere near sufficient.** `House.directory()`
returns every actor today (`house.py:448`), so filtering it is the obvious first move —
and an implementation that stops there has built a listing preference, not a visibility
control.

FR-012 is the real requirement: a `local` actor must not resolve through WebFinger, not
by actor-document lookup, and not in the directory. **A hit is itself the disclosure.**

## The rule that makes it hard

**A refusal must be indistinguishable from "no such actor".** If a `local` actor 404s
differently from a name nobody has ever held — a different status, a different message, a
measurably different response — then the refusal is an oracle and the actor is
discoverable by the shape of the denial.

## Subtasks

### T010 — The directory lists `discoverable` only

`normal` actors are addressable and unlisted. That is the middle level doing its job.

### T011 — A `local` actor does not resolve, anywhere

WebFinger (`api.py:549`), the actor document, and the directory. All three.

### T012 — Visibility is a ceiling, never a grant

FR-016. Server policy still wins: a `discoverable` actor on a `disabled` hub is
unreachable, and one behind the blocklist is unreachable to that peer. Evaluation order
is hub mode, then blocklist, then visibility — and **any refusal produces the same
answer**, because a differently-worded refusal is the oracle above.

### T013 — Refusals are indistinguishable from absence

Assert it directly: the response for a `local` actor and the response for
`nobody_has_ever_held_this_name` must match.

### T014 — Tests, written as absences

In `tests/test_visibility_withholds.py`. NFR-004 says disclosure tests are asserted as
**absences, not presences** — a test that checks a field is present cannot catch a field
that should not be.

- WebFinger for a `normal` actor resolves; for a `local` actor it does not.
- The directory lists `discoverable` only — assert both that `discoverable` is present
  **and** that `normal` and `local` are absent.
- A `discoverable` actor on a `disabled` hub is unreachable.
- A `local` actor's refusal is byte-identical to an unknown name's.

**Run the removal proof, and check the paired positive.** Delete the visibility filter
and the absence tests must fail — but a `normal` actor must still resolve throughout, or
you have proved only that hiding everything hides everything.

## Definition of Done

- `local` resolves nowhere; `normal` is reachable but unlisted; `discoverable` is listed.
- Server policy overrides actor preference, never the reverse.
- No refusal distinguishes an existing actor from an absent one.
- Four gates green.

## Reviewer guidance

Two things to be unkind about. Is the directory the *only* place filtered? And does any
refusal path — status, body, or timing — differ between "hidden" and "never existed"?
