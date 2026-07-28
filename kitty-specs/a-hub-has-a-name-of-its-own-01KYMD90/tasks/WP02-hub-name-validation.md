---
work_package_id: WP02
title: Hub-name validation
dependencies: []
requirement_refs:
- FR-002
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T004
- T005
agent: ''
history: []
authoritative_surface: src/agent_inbox/naming.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/naming.py
- tests/test_naming.py
role: implementer
tags: []
---

# WP02 — Hub-name validation

## Objective

Make `name` an address component rather than free text. It is the right-hand side of
`name@hub`, and today it is validated nowhere.

Measured, not asserted: `trevor@The Salt Club` parses **successfully** into
`trevor@the salt club`, and `hub.thesaltclub.xyz` is accepted as a hub *name* — which is
precisely the hostname/name conflation this mission exists to remove.

## Subtasks

- **T004 — reuse the agent-name rule.** `^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$`. It is
  already the rule for the left-hand side of the same address, `saltclub` satisfies it
  unchanged, and two validators that nearly agree are worse than one.

- **T005 — refuse at the write, never at startup.** An existing hub may already carry a
  name this rule would reject — its operator set it before the rule existed. Validation
  applies to *changing* the name. A running hub must not fail to start because a rule
  arrived after its configuration did.

## Acceptance

- `saltclub` accepted; `The Salt Club` and `hub.thesaltclub.xyz` refused, each with a
  message saying which rule was broken.
- `local` accepted — it is a permitted name, not a reserved word to reject here.
- A hub already configured with a now-invalid name still starts.
- One validator, shared with agent names.
