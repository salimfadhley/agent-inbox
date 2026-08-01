---
work_package_id: WP01
title: 'The floor says 3.14'
dependencies: []
requirement_refs:
- FR-001
- FR-006
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/13
planning_base_branch: kitty/mission-current-python
merge_target_branch: kitty/mission-current-python
branch_strategy: Planning artifacts for this mission were generated on kitty/mission-current-python. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into kitty/mission-current-python unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
phase: Phase 1 - The floor
agent: python-pedro
history:
- at: 2026-08-01T14:45:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: pyproject.toml
execution_mode: code_change
owned_files:
- pyproject.toml
- uv.lock
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP01 – The floor says 3.14

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer` · **Agent/tool**: `python-pedro`

---

## Objective

Move the floor from Python 3.12 to 3.14 in `pyproject.toml`, and find out what pyright says
once it is analysing 3.14 semantics rather than 3.12's.

Nothing else in this mission may start first. WP02 and WP03 both build on the floor this WP
sets.

## Context you need before you start

**The charter has already been amended** (`main`, 2026-08-01, commit `6393e2b`). It now says
the floor is 3.14+ and the ambition is the latest Python. **Do not edit the charter** — that
was settled outside this mission on purpose, and it is not yours to revisit. You are
implementing a policy that already exists.

The charter also states a rule this WP is half of:

> the floor moves as one change: `requires-python`, the classifiers, ruff's
> `target-version`, pyright's `pythonVersion`, both `Dockerfile` stages and CI, or none of
> them

The `Dockerfile` and CI half is WP03's. Neither half ships alone.

**Phase 0 has already been run**, on 2026-08-01, against a scratch environment at 3.14.2.
Read `plan.md` for the detail; the parts that change what you do:

- **The dependencies are fine.** The full dev + `clients` + `ui` set resolved and installed
  on 3.14.2 with no pinned exception and no source build. You are not expected to fight
  wheels. If you find yourself adding a pin, stop — FR-006 forbids it, the charter now
  forbids it in general, and the plan's evidence says you should not need one.
- **`ruff check`, `ruff format --check` and `pytest` already pass on 3.14.** Baseline:
  **961 passed, 18 skipped**.
- **pyright reported zero errors — and that number is worthless to you.** It was still
  configured `pythonVersion = "3.12"`. T002 changes that, and T003 is where the real answer
  arrives.

## Subtasks

### T001 — `requires-python` and the trove classifiers

`pyproject.toml`:

- Line 12: `requires-python = ">=3.12"` → `">=3.14"`
- Lines 33-34: the two `Programming Language :: Python :: 3.12` / `3.13` classifiers become
  a single `3.14`

**The classifiers are a claim about what this package supports**, published to PyPI. Leaving
`3.12` there after the floor moves is a false statement that installers act on.

### T002 — ruff `target-version` and pyright `pythonVersion`

`pyproject.toml`:

- Line 111: `target-version = "py312"` → `"py314"`
- Line 127: `pythonVersion = "3.12"` → `"3.14"`

These two are the ones that change what the tools *think*, as opposed to what they run on.
T003 is their consequence.

### T003 — Re-run the four gates at 3.14 semantics and triage pyright

The four gates, and there is no fifth — there is **no black in this project**:

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

**Capture real exit codes.** Do not pipe a gate into `tail` and read `$?` — that reports
the exit status of `tail`, and it has already caused one false "all green" in this project.

`ruff` may now report new findings: `target-version = "py314"` enables rules and
auto-fixes that were suppressed at py312 (`UP` rules in particular). Apply them.

**pyright is the unpredictable one.** At 3.14 semantics it may infer differently — expect
churn. The spec's instruction is binding: *treat any new complaint as a real finding rather
than noise to silence.* A `# type: ignore` added to make this WP finish is a defect with a
comment on it. If a complaint is genuinely a pyright limitation, say so in the commit
message and link the upstream issue.

**One failure you may see is already known and is not yours to fix here**:
`tests/test_operators.py::TestRemoval::test_any_operator_can_be_removed` fails intermittently
on 3.14 with a `UnicodeDecodeError` in capture teardown — roughly one run in two. It is
**WP02's T008**. Note it if you see it; do not chase it, and do not skip it.

### T004 — Regenerate the lock with the same dependency set

```bash
uv lock
```

Then **diff the resolved package set against the previous lock**. Versions moving is
expected. A package appearing or disappearing is not, and means something in T001 changed
more than the floor.

FR-006 in one line: no pinned exception. If the lock needs a `< x.y` to resolve, this WP
stops and reports rather than adding it.

## Definition of Done

- [ ] `pyproject.toml` states 3.14 in all four places (requires-python, classifiers, ruff,
      pyright)
- [ ] All four gates pass, with **real** exit codes recorded in the commit message
- [ ] `uv.lock` resolves with the same set of packages and no new pin
- [ ] Any pyright complaint is either fixed or documented with a reason — none silenced

## Risks

| Risk | What to do |
|---|---|
| pyright churn is larger than expected | Report it; do not silence it. Enlarging this WP is the right outcome |
| A dependency needs a pin | Stop. FR-006 says a single "temporarily pinned" is the seed of the next stuck migration |
| Gate exit codes read through `tail` | Capture them directly. This has produced a false green here before |

## Reviewer guidance

Check the four `pyproject.toml` sites individually — it is easy to move `requires-python`
and forget `pythonVersion`, and the result looks green because pyright is then simply
checking the wrong language. The charter is not in scope — if this WP touched
`.kittify/charter/`, that is a defect.
