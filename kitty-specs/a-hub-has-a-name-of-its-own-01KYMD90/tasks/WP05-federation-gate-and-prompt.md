---
work_package_id: WP05
title: The federation gate, and the prompt that introduces the hub
dependencies:
- WP04
requirement_refs:
- FR-006
- FR-010
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
agent: ''
history: []
authoritative_surface: src/agent_inbox/prompts.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/prompts.py
- src/agent_inbox/console.py
- tests/test_console.py
role: implementer
tags: []
---

# WP05 — The federation gate, and the prompt that introduces the hub

## Objective

Two small pieces that both depend on everything above: the rule that a hub called `local`
cannot switch federation on, and letting an arriving agent learn what the hub is.

## Subtasks

- **T011 — the gate.** Federation cannot be **enabled** while `name` is `local` — not
  merely blocked from federating, so that a hub which has turned federation on without a
  name is not a reachable state. The refusal explains itself: a hub called "local" cannot
  be told apart from every other hub called "local".

  **There is no federation to gate yet**, which makes this a rule with nothing behind it —
  precisely the shape `AGENTS.md` warns about. So: ship the **rule and a test that fails
  if the rule is removed**, and leave the *switch* to the federation mission that will own
  it. A gate wired to nothing, with no test, is decoration that someone will later believe.

- **T012 — the prompt introduces the hub.** Where `title` and `description` are set, an
  arriving agent should learn what the place is rather than only how it authenticates.

  Both are optional, and **every hub today has neither** — so the wording must read
  correctly when they are absent. That is the common case, not the edge case. The prompt
  is the most-read document in the project and has twice been caught asserting something
  untrue; this must not be a third.

## Acceptance

- Enabling federation with `name` = `local` is refused, and the refusal says why.
- The refusal test fails if the rule is removed — verified by removing it.
- Renaming, then enabling, succeeds.
- With title and description set, the prompt introduces the hub with them.
- With neither set, the prompt reads exactly as it does today.
