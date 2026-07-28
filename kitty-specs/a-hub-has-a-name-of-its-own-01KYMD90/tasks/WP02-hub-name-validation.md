---
work_package_id: WP02
title: Hub-name validation
dependencies: []
requirement_refs:
- FR-002
- FR-006
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/hub-identity
merge_target_branch: feat/hub-identity
branch_strategy: Planning artifacts for this mission were generated on feat/hub-identity. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/hub-identity unless the human explicitly redirects the landing branch.
subtasks:
- T007
- T008
- T009
- T010
phase: Phase 1 - Foundation
agent: python-pedro
history:
- at: '2026-07-28T14:17:34Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/naming.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/naming.py
- tests/test_naming.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP02 – Hub-name validation

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

Make `name` an address component rather than free text. It is the right-hand side of
`name@hub`, and today it is validated nowhere.

The asymmetry is the whole point. The left-hand side of that address is rigorously
designed — assigned by the hub, opaque, unique, stable forever, and validated against
`^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$`. The right-hand side is free text with a default
of `local`. ADR 0003 was written about identity built from mutable facts "so the mistake is
not repeated"; this package applies its argument one level up.

Measured, not asserted: `trevor@The Salt Club` parses **successfully** today into
`trevor@the salt club`, and `hub.thesaltclub.xyz` is accepted as a hub *name*. That second
one is precisely the hostname/name conflation this mission exists to remove, which is why
it earns a named test rather than a general "invalid input is refused".

Complete when:

- `saltclub` is accepted; `The Salt Club` and `hub.thesaltclub.xyz` are refused, each with
  a message naming the rule that was broken.
- `local` is accepted — it is a permitted name, and the default. Refusing it here would be
  the wrong place for that constraint; see WP05.
- A hub already configured with a now-invalid name still starts.
- One validator, shared with agent names. Not two that nearly agree.

## Context & Constraints

Read before starting:

- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md` — FR-002 and the "Four things,
  not two" table
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/data-model.md` — invariants 3 and 4
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/research.md` — D-02, on the asymmetry
- `doc/decisions/0003-identity-is-a-surrogate-key.md`

Constraints:

- **One rule, not two.** Reuse the agent-name rule. Two validators that nearly agree is a
  worse state than one, because the disagreement surfaces later, in a case nobody chose.
- **`local` is a name, not a sentinel.** It passes validation. What it blocks is *enabling
  federation*, and that rule lives in WP05 where the consequence is.
- **Validation is about writes.** A rule that arrives after a configuration must not stop
  the configured hub from starting.

## Branch Strategy

- **Strategy**: Planning artifacts for this mission were generated on `main`. During
  `/spec-kitty.implement` this WP may branch from a dependency-specific base, but completed
  changes must merge back into `main` unless the human explicitly redirects the landing
  branch.
- **Planning base branch**: `main`
- **Merge target branch**: `main`

Execution worktrees are allocated per computed lane from `lanes.json`; do not create one by
hand. Assert the branch and `HEAD` before any commit.

Implementation command (no dependencies — this may run concurrently with WP01):

```bash
spec-kitty agent action implement WP02 --agent <name>
```

## Subtasks & Detailed Guidance

### T007 — A hub-name validator, reusing the agent-name rule

- **Purpose**: make the right-hand side of an address obey the same rule as the left.
- **Files**: `src/agent_inbox/naming.py`
- **Steps**:
  1. Find the existing agent-name validation. Reuse the pattern
     `^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$` by **referring to it**, not by copying the
     literal into a second constant. If it is currently inlined, lift it to a named constant
     and have both callers use it.
  2. Add `validate_hub_name(name: str) -> None` (or the module's existing convention —
     match whatever agent names already do, including whether refusal is an exception or a
     returned error).
  3. `saltclub` must satisfy it unchanged. So must `local`.
- **Do not**: add hub-specific relaxations. A dot is refused because a hostname is not a
  name — that is the point, not an oversight to work around.

### T008 — The refusal names the rule that was broken

- **Purpose**: an operator typing "The Salt Club" into a form should learn what a hub name
  is, not merely that theirs is wrong.
- **Files**: `src/agent_inbox/naming.py`
- **Steps**:
  1. State the rule in the message: lowercase letters, digits and underscores; must start
     and end with a letter or digit; 64 characters at most.
  2. Where the input suggests a specific confusion, say so. `hub.thesaltclub.xyz` should
     draw a message distinguishing the hub's **address** from its **name** — they are
     different fields and the operator has supplied one where the other belongs. This is
     the confusion the mission exists to remove, so the error message is where the
     distinction gets taught.
  3. Follow the repo's existing refusal style. `_parse_profile()` in `cli.py` already
     distinguishes two refusals rather than collapsing them into one message; that is the
     house pattern.
- **Do not**: silently normalise. Lowercasing "The Salt Club" into `the salt club` is what
  the system does today and is the bug.

### T009 — Validation applies at writes, never at startup

- **Purpose**: a hub configured before this rule existed must still start.
- **Files**: `src/agent_inbox/naming.py`, and confirm the call sites
- **Steps**:
  1. Validate in the write path only — the route in WP03, and any CLI or console path that
     sets a name.
  2. Do **not** validate the resolved value at startup. An operator who set
     `AGENT_INBOX_HUB_NAME=my.hub.example` before this release must find their hub running,
     not refusing to boot on a rule that postdates their configuration.
  3. If it is worth surfacing, surface it where surfacing is free: `doctor` can report a
     name the current rule would refuse, as a warning rather than a failure. That matches
     how `doctor` already reports clashes.
- **Why**: this is data-model invariant 4, and it is the difference between a validation
  rule and an outage.

### T010 — Tests

- **Purpose**: pin the two worked examples from the spec, and the start-with-a-legacy-name
  case.
- **Files**: `tests/test_naming.py`
- **Steps**:
  1. Accepted: `saltclub`, `local`, `a`, a 64-character name, names containing underscores
     and digits.
  2. Refused, each asserting on the message and not merely on the exception type:
     - `The Salt Club` — spaces and capitals
     - `hub.thesaltclub.xyz` — a hostname is not a name
     - the empty string
     - a 65-character name
     - a name starting or ending with an underscore
  3. **The legacy case**: construct a hub whose resolved name would fail validation, and
     assert it starts and serves. This is the test that stops the rule becoming an outage.
  4. Assert that hub names and agent names are checked by the same rule — for instance by
     asserting the two validators refuse and accept an identical set of tricky inputs. If
     they ever diverge, this test is what says so.
- **Establish the premise**: before asserting the legacy hub starts, assert its name really
  would be refused by the new rule. Otherwise the test proves that a *valid* name starts,
  which was never in doubt.

## Test Strategy

`pytest`, table-driven. The two named refusals from the spec are the tests that matter;
everything else is boundary coverage.

The failure this package could ship without noticing is **two validators that nearly
agree** — no single test fails, and the divergence surfaces months later in a case nobody
chose. T010 step 4 is the guard against it.

## Definition of Done

- [ ] One shared rule; the agent-name pattern is referred to, not copied.
- [ ] `saltclub` and `local` accepted.
- [ ] `The Salt Club` and `hub.thesaltclub.xyz` refused, with messages naming the rule.
- [ ] The hostname refusal distinguishes address from name.
- [ ] Validation runs at writes only.
- [ ] A hub with a now-invalid configured name starts, asserted, with the premise
      established.
- [ ] All four charter gates pass: `uv run pytest`, `uv run ruff check`,
      `uv run ruff format --check`, `uv run pyright`.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A second copy of the pattern | Diverges silently, later | T007 refers; T010 step 4 asserts agreement |
| Validating at startup | Breaks a running deployment on upgrade | T009 |
| Refusing `local` here | Puts the constraint in the wrong place, breaking the quickstart | `local` is in the accepted list |
| Normalising instead of refusing | Is the current bug | T008 forbids it |

## Reviewer Guidance

- Grep for the pattern literal. More than one occurrence is the defect this package is
  meant to avoid.
- Check the legacy-start test constructs a name the rule actually refuses. If it uses a
  valid name, it asserts nothing.
- Check `local` is accepted here and gated in WP05. A constraint in the wrong place is
  harder to find than a missing one.
