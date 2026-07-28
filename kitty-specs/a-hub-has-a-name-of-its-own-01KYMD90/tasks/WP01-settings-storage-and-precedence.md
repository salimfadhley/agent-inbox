---
work_package_id: WP01
title: Settings storage, and environment precedence
dependencies: []
requirement_refs:
- FR-003
- FR-004
- NFR-001
- NFR-002
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
- T006
phase: Phase 1 - Foundation
agent: python-pedro
history:
- at: 2026-07-28T14:17:34Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/
create_intent:
- tests/test_hub_settings.py
execution_mode: code_change
owned_files:
- src/agent_inbox/store.py
- src/agent_inbox/sqlite_store.py
- src/agent_inbox/serve.py
- tests/test_store_contract.py
- tests/test_hub_settings.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP01 – Settings storage, and environment precedence

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro`
- **Role**: `implementer`
- **Agent/tool**: `python-pedro`

If no profile is specified, run `spec-kitty agent profile list` and select the best match
for this work package's `task_type` and `authoritative_surface`.

---

## Markdown Formatting

Wrap HTML/XML tags in backticks: `` `<div>` ``. Use language identifiers in code blocks.

---

## Objectives & Success Criteria

Give the hub somewhere to keep three values about itself, and settle which source wins when
two of them speak. Everything else in this mission reads through this package, which is why
it goes first.

This is the **first persistent state the hub has ever kept about itself**. The store holds
`actors`, `objects` and `reads` — all about mail. Adding a fourth table is small, but it is
a genuine widening of what the store is for, and worth doing deliberately rather than
incidentally.

Complete when:

- Both store implementations keep and return `name`, `title` and `description`, and the
  existing contract tests exercise both.
- An existing database gains the table without losing mail — asserted, not assumed.
- The environment wins where it speaks; the stored value wins where it does not; `local` is
  the default for `name`.
- Unsetting an override restores the stored value. **This is the one that matters.**
- Resolution reports which source supplied each value, and names the variable when the
  source is the environment.
- A hub with none of this configured behaves exactly as it does today (NFR-002).

## Context & Constraints

Read before starting:

- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md` — particularly "Environment
  wins, and the UI says so"
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/data-model.md` — `HubSettings`,
  `ResolvedSetting`, and invariants 1, 2 and 4
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/research.md` — D-07, which is the
  argument for adding a second configuration source at all
- `AGENTS.md` — "establish the premise before asserting on it"

Constraints that bind this package:

- **No new mount, no config file** (NFR-001). The values live in the existing SQLite file,
  beside the mail. `serve.py` currently says configuration is environment-only because
  "anything else would need mounting" — that objection is about config *files*, and the
  volume the mail lives on is already there. Say so in the code comment you replace, so the
  next reader sees the argument rather than an unexplained reversal.
- **The container contract survives.** A deployment setting `AGENT_INBOX_HUB_NAME` must
  behave exactly as it does today. Nothing about existing deployments changes.
- **No deployment-specific values in the repo.** No hostnames, no organisation names, no
  tokens. `local` is deliberately meaningless.

## Branch Strategy

- **Strategy**: Planning artifacts for this mission were generated on `main`. During
  `/spec-kitty.implement` this WP may branch from a dependency-specific base, but completed
  changes must merge back into `main` unless the human explicitly redirects the landing
  branch.
- **Planning base branch**: `main`
- **Merge target branch**: `main`

Execution worktrees are allocated per computed lane from `lanes.json`; do not create one by
hand. Before any commit or tag, assert the branch and `HEAD` you are actually on — this
repo has had a release tagged onto the wrong branch, and the rule in `AGENTS.md` exists
because of it.

Implementation command (no dependencies):

```bash
spec-kitty agent action implement WP01 --agent <name>
```

## Subtasks & Detailed Guidance

### T001 — A `hub_settings` table on the SQLite store

- **Purpose**: somewhere durable for three values, in the file the hub already owns.
- **Files**: `src/agent_inbox/sqlite_store.py`
- **Steps**:
  1. Add the table to the schema alongside `actors`, `objects` and `reads`. A
     single-row-per-key shape (`key TEXT PRIMARY KEY, value TEXT NOT NULL`) is preferable
     to a one-row-three-columns shape: it makes "this key has never been set" the natural
     representation rather than a nullable column, and absence is the state of every hub
     that exists today.
  2. The migration is **additive**. It must not `ALTER` or rewrite `actors`, `objects` or
     `reads`. This runs against a database holding live mail.
  3. Follow whatever migration mechanism the store already uses. If schema creation is
     `CREATE TABLE IF NOT EXISTS` at startup, use that; do not introduce a migration
     framework for one table.
  4. Provide `get_hub_settings()` and `set_hub_setting(key, value)` (or the naming the
     store already favours). Reads must tolerate the table being empty.
- **Do not**: write a default row at creation time. An empty table is the correct state for
  an upgraded hub, and pre-seeding `name = "local"` would make the stored value
  indistinguishable from the default — which quietly breaks T005's ability to report the
  source honestly.

### T002 — The same surface on the in-memory store `[P]`

- **Purpose**: the contract tests run against both implementations; a feature that exists
  on only one of them is a divergence waiting to be found by a test that does not run.
- **Files**: `src/agent_inbox/store.py`
- **Steps**:
  1. Mirror T001's method signatures exactly. Same names, same argument order, same return
     types.
  2. A dict is the obvious backing structure. Absence must behave the same way it does on
     SQLite — missing key, not empty string.
- **Parallel**: this can be written alongside T001. T003 is what forces them to agree.

### T003 — Store contract tests cover settings on both stores

- **Purpose**: prove the two implementations agree, rather than assuming they do.
- **Files**: `tests/test_store_contract.py`
- **Steps**:
  1. Add settings cases to the existing parametrised contract suite so they run against
     each store without a second copy of the test.
  2. Cover: reading with nothing set; setting then reading back; overwriting; and reading a
     key that has never been set.
  3. Add the case that matters operationally: **an existing database with mail in it gains
     the table and keeps the mail.** Create a store, write a message, close, reopen with the
     new schema, and assert the message is still there and readable. This is the assertion
     that stands between this change and a data-loss incident.
- **Establish the premise**: before asserting that mail survives, assert the mail was there.
  A test that writes nothing and then finds nothing missing has looked at nothing.

### T004 — Resolution in `serve.py`: environment, then stored, then default

- **Purpose**: one place that answers "what is this hub's name", consulted by everything.
- **Files**: `src/agent_inbox/serve.py`
- **Steps**:
  1. Resolve each of the three fields in order: environment variable, then stored value,
     then default. `name` defaults to `local`; `title` and `description` have no default and
     resolve to absent.
  2. Use the existing `_env()` helper so the `AGENT_MAILBOX_` legacy prefix keeps working —
     this repo supports both prefixes deliberately and a new setting that reads only the new
     one would be an inconsistency.
  3. Update the module comment that currently states configuration is environment-only. It
     is no longer true, and a comment that argues with the code beside it is exactly the
     signal this project has learned to treat as evidence. Replace it with the D-07
     argument: the environment still wins, and the store is consulted only when the
     environment is silent.
- **Do not**: resolve at import time into a module-level constant. The stored value can
  change while the hub runs — that is the point of WP03's write route — so resolution must
  be able to see a change without a restart.

### T005 — Report which source won

- **Purpose**: the console cannot render a disabled field without knowing whether the
  environment fixed it, and an operator cannot debug configuration whose provenance they
  cannot see.
- **Files**: `src/agent_inbox/serve.py`
- **Steps**:
  1. Return a `ResolvedSetting` carrying `value`, `source` (`environment` | `stored` |
     `default`) and `variable` — the environment variable's name, present only when the
     source is `environment`.
  2. **Copy `client.effective_settings()`.** It already returns `(value, source)` for client
     configuration, for exactly this reason: "which one won" is the question people open
     config files to answer. Two nearly-identical answers to the same question is worse than
     one, and this repo has paid for near-duplicates before.
  3. `variable` exists so the console can name the variable governing a disabled field. A
     greyed box with no explanation reads as broken; one naming `AGENT_INBOX_HUB_NAME` reads
     as governed.
- **Note**: report the variable name the deployment actually used. If a hub is configured
  through `AGENT_MAILBOX_HUB_NAME`, naming `AGENT_INBOX_HUB_NAME` in the console sends the
  operator to edit a variable that is not the one in effect.

### T006 — Assert that overriding does not erase

- **Purpose**: this is the highest risk in the mission, and it is invisible to inspection.
- **Files**: `tests/test_hub_settings.py` (new)
- **Steps**:
  1. Write the full cycle as one test: store a value; set the environment variable to
     something different; resolve, and assert the environment's value is returned **and**
     that the stored value is unchanged in the store; unset the variable; resolve again and
     assert the operator's own value comes back.
  2. Assert the store contents directly, not only what resolution returns. A resolution that
     reads correctly while the store has already been overwritten passes a weaker test and
     fails the operator.
  3. Add the NFR-002 case: a hub with nothing configured at all. Assert `name` resolves to
     `local`, `title` and `description` are absent, and the descriptor's existing fields are
     unchanged.
- **Why this is a subtask and not a line in an acceptance list**: if startup writes the
  environment's value into the store, the operator's own setting is silently destroyed —
  and it looks exactly like it worked. That is this project's recurring defect shape. The
  environment *shadows* the stored value; it never replaces it.

## Test Strategy

`pytest` throughout, against both store implementations via the existing parametrised
contract suite.

The three tests that would catch a real defect here, in order of importance:

1. **Set, override, unset, restore** (T006). Catches silent data loss.
2. **Existing mail survives the schema change** (T003). Catches a destructive migration.
3. **Nothing configured behaves as today** (T006). Catches a regression in every existing
   deployment, which is all of them.

Everything else is coverage.

## Definition of Done

- [ ] `hub_settings` exists on both stores with identical surfaces.
- [ ] Contract tests exercise settings against each store.
- [ ] A database with mail in it survives the schema addition, asserted.
- [ ] Resolution prefers environment, then stored, then default.
- [ ] `ResolvedSetting` carries source and, where applicable, the governing variable name.
- [ ] The set/override/unset/restore cycle is asserted and passes.
- [ ] A hub with nothing configured is unchanged.
- [ ] The stale "environment only" comment in `serve.py` is replaced with the current
      argument, not deleted.
- [ ] `ruff`, `pyright` and `pytest` all pass. Do not commit past a failing gate — read the
      gate's own output before claiming it is green.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Startup writes the environment into the store | Silent data loss that looks like success | T006 asserts the whole cycle |
| Migration touches existing tables | Live mail | Additive only; T003 asserts mail survives |
| Pre-seeding a default row | Makes `stored` and `default` indistinguishable | T001 forbids it explicitly |
| Reading only the new env prefix | Existing deployments use the legacy one | Use `_env()` |
| Resolving once at import | The write route cannot take effect | T004 forbids it |

## Reviewer Guidance

- Delete the precedence logic and run the tests. If they still pass, the tests are looking
  at nothing — this repo has shipped three such tests and caught them all this way.
- Check that the store assertion in T006 reads the store, not the resolver.
- Check the replaced comment in `serve.py` states the argument rather than merely dropping
  the old claim. A reader six months from now needs to know the reversal was deliberate.
