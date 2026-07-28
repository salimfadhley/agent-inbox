---
work_package_id: WP01
title: Settings storage, and environment precedence
dependencies: []
requirement_refs:
- FR-003
- FR-004
- NFR-001
- NFR-002
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
agent: ''
history: []
authoritative_surface: src/agent_inbox/store.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/store.py
- src/agent_inbox/sqlite_store.py
- src/agent_inbox/serve.py
- tests/test_store_contract.py
- tests/test_serve.py
role: implementer
tags: []
---

# WP01 — Settings storage, and environment precedence

## Objective

Give the hub somewhere to keep three values about itself, and settle which source wins.
Everything else in this mission reads through this, so it goes first.

This is the **first hub-level state the hub has ever kept about itself**. The store holds
`actors`, `objects` and `reads` — all about mail. Adding a fourth table is small but it is
a genuine widening of what the store is for, and worth doing deliberately.

## Subtasks

- **T001 — a settings table, on both stores.** `sqlite_store.py` and the in-memory
  `store.py`, so `test_store_contract.py` covers both. The migration is **additive** and
  must not touch the existing tables: this runs against a database holding live mail.

  A hub upgrading with no settings row is the ordinary case, not an error.

- **T002 — precedence in `serve.py`.** Environment over stored, always. The container
  contract is unchanged: a deployment setting `AGENT_INBOX_HUB_NAME` behaves exactly as it
  does today, and the stored value is consulted only when the environment is silent.

- **T003 — report which source won.** The console cannot render a disabled field without
  knowing whether the environment fixed it, so resolution returns the value *and* its
  origin. `client.effective_settings()` already does exactly this for client config,
  returning `(value, source)` — copy that shape rather than inventing a second one.

## The risk that matters

**Overriding must not erase.** An operator who sets an environment variable, restarts,
then unsets it, must get their configured value back.

If startup writes the environment's value into the store, the operator's own setting is
silently destroyed — and it looks exactly like it worked, which is this project's
recurring defect shape. The environment *shadows* the stored value; it never replaces it.

Assert it directly rather than trusting the design: set stored, override by environment,
restart, unset, restart, and check the stored value is still there.

## Acceptance

- Both stores keep and return the three values; the contract tests pass against each.
- An existing database gains the table without losing mail — asserted, not assumed.
- Environment wins where set; stored wins where it does not.
- Unsetting an override restores the stored value.
- Resolution reports which source supplied each value.
- **A hub with none of this configured behaves exactly as today** (NFR-002).
