---
work_package_id: WP02
title: A human is an actor, marked Person
dependencies:
- WP01
requirement_refs:
- FR-006
- FR-007
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
agent: python-pedro
history:
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/humans.py
create_intent:
- src/agent_inbox/humans.py
- tests/test_humans.py
execution_mode: code_change
owned_files:
- src/agent_inbox/humans.py
- src/agent_inbox/vocabulary.py
- src/agent_inbox/records.py
- tests/test_humans.py
role: implementer
tags: []
---

# WP02 — A human is an actor, marked `Person`

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

An agent can tell that a human wrote something **without reading the prose** — and that
marker confers nothing whatsoever.

Both halves are the package. The first without the second is how a system acquires a
privileged class of sender by accident.

## The name already exists, and that is the point

Do not invent a flag. `vocabulary.py` already says, in the negative, exactly what this
package needs:

> Agents are `Service`, not `Person` — the vocabulary distinguishes automated actors
> from people, and this hub is built for LLMs first.

So the word for a human correspondent was **reserved before there were any**. Using it is
what C-001 of the parent federation work asks for: the fediverse settled this years ago,
and inventing a second marker beside `Person` would be a departure with nothing to
recommend it.

It also settles the deferred federation question cheaply: a remote hub reading `Person`
learns which side of the machine wrote to it, using vocabulary it already parses.

## What is already there

- `ActorType` is a `StrEnum` with `SERVICE` and `GROUP`. `PERSON` is the addition.
- `ActorRecord.actor_type` defaults to `SERVICE`.
- `ActorRecord.profile` is free-form and mutable; **identity is not**, which is ADR 0003
  and the reason the marker belongs in `actor_type` rather than in `profile`.

## Subtasks

### T006 — A human's actor is `Person`, not `Service`

Add `PERSON` to `ActorType` and give a human's actor that type when it is created.

Keep `vocabulary.py`'s docstring honest: it currently explains why agents are not
`Person`, phrased as though nothing here is. Update it to say what `Person` now means
here, keeping the original reasoning — that comment is why the word was available.

### T007 — The marker is on the wire, and on the record

FR-006: distinguishable **without inspecting prose**.

A reader — local or remote — sees the actor's type. Assert on the serialised form, not
only on the dataclass: a marker that exists in memory and not on the wire satisfies
nobody.

### T008 — The marker grants nothing — asserted, not assumed

FR-007, and C-001, and ADR 0008. **The role grants console access, never obedience.**

This is a negative and negatives rot quietly, so make it a test rather than a comment:

- no code path branches on "the sender is a human" to permit something it would
  otherwise refuse;
- a message from a human is delivered, stored and rendered by the same path as any
  other.

The honest way to write this is to search the source for the shape of such a branch and
fail on finding one, in the same spirit as the federation mission's "no second
implementation exists" test. A reviewer's eye is not a guard.

### T009 — Creating a human creates exactly one identity

The join between WP01's merge and this package: making a human must not be able to
produce an operator account without an actor, or an actor without an account.

Assert both directions. A half-created human is the state in which every later package
misbehaves in a way that looks like its own bug.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass.
- `Person` appears on the wire for a human and `Service` for an agent, asserted on the
  serialised form.
- A test fails if any code path grants something on the basis of a human sender.
- The removal proof has been run on T008 in particular — it is the one that matters and
  the one that can pass while asserting nothing.

## Risks

| Risk | Why it matters |
|---|---|
| The marker put in `profile` | `profile` is mutable; identity is not (ADR 0003) |
| T008 written as a comment | The whole constraint becomes an intention |
| A second marker invented beside `Person` | A silent departure from a settled convention, for nothing |

## Reviewer guidance

The question to ask is not "is the marker there". It is: **what would break if a human's
message were treated as authoritative tomorrow?** If the answer is "a reviewer would
notice", T008 is not done.
