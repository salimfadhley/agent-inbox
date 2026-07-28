---
work_package_id: WP04
title: The Federation tab, with governed fields shown not offered
dependencies:
- WP03
requirement_refs:
- FR-005
- FR-007
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T008
- T009
- T010
agent: ''
history: []
authoritative_surface: src/agent_inbox/console.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/console.py
- tests/test_console.py
role: implementer
tags: []
---

# WP04 — The Federation tab, with governed fields shown not offered

## Objective

Somewhere to see and edit the three fields — and to be honest about which of them the
operator actually controls.

## Subtasks

- **T008 — a Federation tab.** It ships as a **placeholder for federation itself**, on the
  operator's instruction: get the settings system working before the feature that needs
  it, and there are no non-developer users to confuse. The page should say so plainly
  rather than implying federation exists. Peers, modes and blocklists join it later —
  pablo's `manual-activitypub-federation-v1-01KYJY10` FR-001 already plans that tab.

- **T009 — environment-fixed fields render disabled**, saying so and **naming the
  variable**. A greyed box with no explanation reads as broken; one that says
  "`AGENT_INBOX_HUB_NAME` is set by this deployment" reads as governed.

- **T010 — do not offer a control that does nothing.** The rule behind T009, and worth
  stating separately because it is the general principle: an editable field that silently
  loses its value on restart is the same family as a check that passes with nothing to
  look at, or a send that succeeds and reaches nobody. It looks like it worked.

## Acceptance

- The tab renders with all three fields, and the values come from the API rather than
  being recomputed in the console (ADR 0005).
- With an environment variable set, the field is disabled, names the variable, and cannot
  be submitted.
- With nothing set, all three are editable and persist across a restart.
- The page says federation itself is not built yet.
- On an enforcing hub, a caller without an operator session cannot reach the tab's write.
