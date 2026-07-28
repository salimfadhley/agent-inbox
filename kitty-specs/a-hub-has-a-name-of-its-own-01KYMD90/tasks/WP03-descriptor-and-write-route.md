---
work_package_id: WP03
title: The descriptor, and an operator-gated write
dependencies:
- WP01
- WP02
requirement_refs:
- FR-001
- FR-008
- FR-009
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
agent: ''
history: []
authoritative_surface: src/agent_inbox/api.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_api.py
role: implementer
tags: []
---

# WP03 — The descriptor, and an operator-gated write

## Objective

Let the hub say what it is, and let an operator change it.

## Subtasks

- **T006 — `title` and `description` on `GET /`,** beside the existing `name`, `version`,
  `id` and `authenticated`. Both optional and both may be empty: only `name` is
  load-bearing. A hub that has set neither must produce a descriptor indistinguishable
  from today's.

- **T007 — an operator-gated write.** Administrative, so it hangs off `provide_operator`
  exactly as `revoke_token` does. **No agent credential may reach it** — ADR 0008 is that
  administration happens out of band and nothing arriving in a mailbox can change the
  mailbox, and a hub's own identity is the clearest case of that.

  On an unauthenticating hub the console is already open and this changes nothing, which
  matches how the console's `_gate` already behaves.

## Acceptance

- `GET /` carries all three; absent values are absent rather than empty strings pretending
  to be values.
- A hub with nothing configured returns what it returns today.
- The write succeeds for an operator, and is refused with an agent's device token.
- An invalid name is refused by the route, not only by the form — the API is where the
  decision lives (ADR 0005), and a second client must not be able to write what the
  console would reject.
