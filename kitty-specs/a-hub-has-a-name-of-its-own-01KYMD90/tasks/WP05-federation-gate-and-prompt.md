---
work_package_id: WP05
title: The federation gate, and the prompt that introduces the hub
dependencies:
- WP02
- WP04
requirement_refs:
- FR-006
- FR-010
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T022
- T023
- T024
- T025
- T026
phase: Phase 3 - Consequences
agent: python-pedro
history:
- at: 2026-07-28T14:17:34Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/prompts.py
create_intent:
- src/agent_inbox/federation.py
- tests/test_hub_identity.py
execution_mode: code_change
owned_files:
- src/agent_inbox/prompts.py
- src/agent_inbox/federation.py
- tests/test_hub_identity.py
- README.md
- doc/runbook/admin.md
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP05 – The federation gate, and the prompt that introduces the hub

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

Two consequences that both depend on everything above: the rule that a hub called `local`
cannot switch federation on, and letting an arriving agent learn what the hub is.

Complete when:

- Enabling federation while `name` is `local` is refused, and the refusal says why.
- **The refusal's test fails when the rule is removed** — verified by removing it, not
  assumed.
- Renaming, then enabling, succeeds.
- With `title` and `description` set, the prompt introduces the hub with them.
- With neither set — which is every hub in existence today — the prompt reads exactly as it
  does now.

## Context & Constraints

Read before starting:

- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md` — FR-006, FR-010, and
  "`local` is a real name, and it is what blocks federation"
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/plan.md` — IC-06, which recommends
  exactly the scope taken here
- `AGENTS.md` — on rules with nothing behind them
- `src/agent_inbox/prompts.py`

### The scoping decision this package inherits

**There is no federation to gate yet.** A gate wired to nothing is precisely the shape
`AGENTS.md` warns about: it will be believed later by someone who did not write it, and
believed rules that were never exercised are how a system acquires a false floor.

So the scope is deliberate and narrow: **ship the rule and a test that fails when the rule
is removed.** Put the rule in its own module — `src/agent_inbox/federation.py` — where the
federation mission (`manual-activitypub-federation-v1-01KYJY10`) will find it and wire the
actual switch to it. Do not add a federation toggle to the console; that belongs to the
mission that owns the switch, and adding one here would be a control that does nothing.

This is why this package does not own `console.py`: WP04 owns it, and there is nothing for
this package to add there.

## Branch Strategy

- **Strategy**: Planning artifacts for this mission were generated on `main`. During
  `/spec-kitty.implement` this WP may branch from a dependency-specific base, but completed
  changes must merge back into `main` unless the human explicitly redirects the landing
  branch.
- **Planning base branch**: `main`
- **Merge target branch**: `main`

Execution worktrees are allocated per computed lane from `lanes.json`; do not create one by
hand. Assert the branch and `HEAD` before any commit.

Implementation command (depends on WP02 and WP04):

```bash
spec-kitty agent action implement WP05 --agent <name>
```

## Subtasks & Detailed Guidance

### T022 — The gate, in one place

- **Purpose**: a hub that has switched federation on without a name is a state worth not
  having.
- **Files**: `src/agent_inbox/federation.py` (new)
- **Steps**:
  1. Write one function — `check_may_enable_federation(hub_name: str) -> None`, or the
     repo's prevailing refusal convention — that refuses when `hub_name` is `local`.
  2. The refusal explains itself at the moment it appears: a hub called "local" cannot be
     told apart from every other hub called "local". That is fine until the moment it must
     not be, and that moment is federation.
  3. Note the strength of the rule in the docstring: this blocks **enabling the mode**, not
     merely federating. The distinction is the requirement (FR-006), and a later reader
     weakening it to "refuse to deliver" would be undoing a decision without knowing it.
  4. Keep the module small and free of imports it does not need. It exists to be found and
     called by the federation mission.
- **Do not**: add a `federation_enabled` setting, a toggle, or a console control. The switch
  belongs to the mission that owns it. Building half of it here leaves a control that does
  nothing — the failure mode this whole package is scoped around.

### T023 — Prove the test by removing the rule

- **Purpose**: the difference between a rule and a decoration is whether a test notices its
  absence.
- **Files**: `tests/test_hub_identity.py` (new)
- **Steps**:
  1. Write the tests: refused when the name is `local`; permitted after renaming to
     `saltclub`; the refusal message states the reason.
  2. Then **delete the rule's body** — make the function a no-op — and run the tests. At
     least one must fail. If none do, the tests are looking at nothing.
  3. Restore the rule and record the result in the commit message or the Activity Log: what
     you removed, and which test failed. This repo has found three tests that passed with
     the fix removed; the practice of checking is what found them.
- **Why this is its own subtask**: because "write a test" and "have a test that would catch
  the defect" are different pieces of work, and this project has repeatedly done the first
  while believing it did the second.

### T024 — The prompt introduces the hub

- **Purpose**: an arriving agent should learn what the place is, not only how it
  authenticates.
- **Files**: `src/agent_inbox/prompts.py`
- **Steps**:
  1. Where `title` is set, use it to name the hub. Where `description` is set, include it —
     it is the operator's own account of what the hub is for and who runs it.
  2. Read them through the resolution WP01 provides. Do not read the environment here.
  3. Keep it brief. The prompt is already long and its job is to make an arriving agent
     competent, not to advertise. One sentence of introduction is the budget.
  4. Do not let the description change what the prompt *instructs*. It is operator-supplied
     free text appearing in the most-read document in the project — it introduces the hub,
     and it must not be positioned where it could read as direction. ADR 0008's principle
     applies: content does not acquire authority by being displayed prominently.

### T025 — The prompt reads correctly when both are absent `[P]`

- **Purpose**: that is every hub in existence today. It is the common case, not the edge
  case.
- **Files**: `src/agent_inbox/prompts.py`
- **Steps**:
  1. With neither set, the prompt must read exactly as it does now — no empty heading, no
     dangling "This hub is:", no sentence that trails into nothing.
  2. Test both-absent, title-only, description-only, and both-set. Four cases, and the first
     is the one that ships to everyone.
  3. Assert on the rendered text, and compare the both-absent rendering against the current
     output. Byte-for-byte where these fields are concerned.
- **Why this is called out separately**: the prompt is the most-read document here and has
  twice been caught asserting something untrue — once about a config filename, once about a
  clash check. This must not be a third.

### T026 — Documentation `[P]`

- **Purpose**: keep the docs true. The standing instruction on this project is that
  documentation is never something to ask permission to fix.
- **Files**: `README.md`, `doc/runbook/admin.md`
- **Steps**:
  1. `README.md`: document the three settings, that the environment wins, and that they can
     be set from the console's Federation tab. Name the environment variables. No
     deployment-specific hostnames or organisation names — the charter forbids them and
     `local` is deliberately meaningless.
  2. `doc/runbook/admin.md`: how an operator sets a hub's name, what happens when the
     environment governs a field, and the `local`-blocks-federation rule.
  3. Check whether `serve.py`'s "configuration is environment only" claim is repeated in any
     document. WP01 corrects the code comment; if a doc says the same thing it is now wrong
     too, and a stale doc outlives a stale comment.
- **Do not**: document the federation switch. It does not exist.

## Test Strategy

`pytest`, in `tests/test_hub_identity.py`.

The two tests that matter:

1. **The gate's test fails when the rule is removed** (T023). Without this the rule is
   decoration.
2. **The both-absent prompt is unchanged** (T025). Without this, every existing hub gets a
   worse prompt on upgrade.

## Definition of Done

- [ ] `federation.py` holds one rule, refusing `local`, with the reason in the message.
- [ ] The docstring records that this blocks *enabling*, not merely federating.
- [ ] No federation toggle, setting, or console control was added.
- [ ] The rule was removed, a test failed, the rule was restored, and the result is
      recorded.
- [ ] The prompt introduces the hub where `title` or `description` are set.
- [ ] With both absent, the prompt is unchanged — asserted against current output.
- [ ] The description cannot read as instruction.
- [ ] `README.md` and `doc/runbook/admin.md` describe the three settings and precedence.
- [ ] `ruff`, `pyright` and `pytest` pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A rule with nothing behind it | Believed later by someone who did not write it | T023's removal check |
| Building half the switch | A control that does nothing — the recurring shape | T022 forbids it explicitly |
| The prompt reading oddly when fields are absent | That is every hub today | T025 makes it the primary case |
| Operator prose read as instruction | The prompt is the most-read document here | T024 step 4 |
| Docs left asserting environment-only config | A stale doc outlives a stale comment | T026 step 3 |

## Reviewer Guidance

- Ask for the removal result from T023. "The tests pass" is not the claim; "the tests fail
  when the rule is gone" is.
- Diff the both-absent prompt against the current one. Anything but identical, in these
  fields, is a regression for every deployment.
- Check nothing here adds a federation control. If there is a toggle, this package
  overstepped its scope and the federation mission now has a half-built switch to reconcile.
