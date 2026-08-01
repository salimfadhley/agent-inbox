---
work_package_id: WP02
title: 'The code: PEP 649 removal, and the failure only 3.14 shows'
dependencies:
- WP01
requirement_refs:
- FR-004
- NFR-001
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/13
planning_base_branch: kitty/mission-current-python
merge_target_branch: kitty/mission-current-python
branch_strategy: Planning artifacts for this mission were generated on kitty/mission-current-python. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into kitty/mission-current-python unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
phase: Phase 2 - The code
agent: python-pedro
history:
- at: 2026-08-01T14:45:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/
create_intent:
- tests/test_annotations_convention.py
execution_mode: code_change
owned_files:
- src/agent_inbox/**
- tests/**
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP02 – The code

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer` · **Agent/tool**: `python-pedro`

---

## Objective

Two things, and only the first is mechanical.

1. Remove `from __future__ import annotations` from all 90 files that carry it, because
   PEP 649 makes it the default in 3.14.
2. Explain the failure that appears only on 3.14 — intermittently, in capture teardown —
   instead of tolerating it.

## Prerequisites

**WP01 must have landed.** The floor, the charter and pyright's `pythonVersion` are all set
there; doing T006 first means removing a `__future__` import while the type checker still
believes it is needed.

## Subtasks

### T006 — Remove `from __future__ import annotations`, all 90 files

Ninety of the ninety-two Python files under `src/` and `tests/` open with it. Under PEP 649
every one is dead code.

The edit is mechanical. **The discipline is not.** FR-004 is worded to forbid a partial job,
and the reason is worth holding in mind while you work: a codebase where some modules opt in
and others rely on the default cannot be read, because the next person cannot tell which
files were considered and which were simply missed.

Two files do **not** have it. Find out why before you finish — either they were missed when
the convention was adopted, or they genuinely differ. Either way the end state is uniform.

After the removal, run `uv run ruff check` and `uv run ruff format --check`: removing the
import can leave a blank line or an import-ordering artifact at the top of a module.

### T007 — The grep proof, as a test

Add a test that asserts no file under `src/` or `tests/` contains
`from __future__ import annotations`.

**Make it proof against the trivial pass.** The plan says this explicitly: "no file imports
future annotations" is satisfied by an empty `src/`. Assert a plausible **lower bound on the
number of files scanned** in the same test, so that a search which finds nothing because it
looked nowhere fails rather than passes.

This test is the reason FR-004 cannot quietly become 88 files. Eyes do not count to 90.

### T008 — Characterise the intermittent `UnicodeDecodeError` [P]

`tests/test_operators.py::TestRemoval::test_any_operator_can_be_removed` fails on 3.14 in
roughly one full-suite run in two, and never on 3.12:

```
self = <contextlib._GeneratorContextManager object at 0x...>, typ = None
    def __exit__(self, typ, value, traceback):
        if typ is None:
            try:
>               next(self.gen)
E               UnicodeDecodeError: 'utf-8' codec can't decode byte 0x94 in position 0
  .../python3.14/contextlib.py:148: UnicodeDecodeError
```

What Phase 0 established, so you do not repeat it:

- It **passes every time in isolation** — `pytest tests/test_operators.py` is clean. So it is
  an interaction with the rest of the suite.
- It is in **capture teardown**, not the assertion. The test body has already succeeded.
- `0x94` at position 0 is a continuation byte with no lead byte — the signature of a
  **buffer split mid-character**, not of genuinely non-UTF-8 data.
- It reproduced twice in four full-suite runs. Budget for repeat runs; a single green run
  proves nothing.

Useful next moves: `-p no:randomly` (if ordering plugins are active) and `-x` with a fixed
seed to find a minimal reproducing subset; `--capture=no` and `--capture=sys` to see whether
it is fd-level capture specifically; and check whether the preceding tests write non-ASCII
to a captured stream.

Three outcomes are possible, and you must say which: a pytest-capture bug on 3.14, an
interaction with our logging configuration, or a latent defect of ours that 3.12 hid.

### T009 — Fix it, or record the upstream issue and scope a workaround

**Do not silence it.** An intermittent failure that gets marked flaky and skipped is how a
real defect acquires a permanent home.

- **Ours** → fix it. That may enlarge this mission, and that is the correct outcome.
- **Upstream** → link the issue in the commit message and add the narrowest possible
  test-side workaround, with a comment naming the condition under which it can be removed.

Then prove it: **ten consecutive full-suite runs, green.** One run is not evidence for a
failure that appears half the time.

## Definition of Done

- [ ] `grep -rl 'from __future__ import annotations' src tests` returns nothing
- [ ] A test enforces that, and fails if it scanned fewer files than the codebase has
- [ ] The four gates pass — pytest, ruff check, ruff format --check, pyright — with real
      exit codes
- [ ] The intermittent failure is explained in writing, and either fixed or linked upstream
- [ ] Ten consecutive full-suite runs are green
- [ ] Test count is **at least** the 961 passed / 18 skipped baseline (NFR-001: no behaviour
      change means no tests lost)

## Risks

| Risk | What to do |
|---|---|
| T006 is done to 88 of 90 files | T007 exists precisely for this. Write it before you believe the removal is complete |
| The flake gets skipped to finish the WP | Explicitly forbidden. Report instead — an enlarged mission beats a hidden defect |
| Ten green runs are declared after one | The failure appears in ~50% of runs. One green run is a coin toss reported as a result |

## Reviewer guidance

Check T007 fails when a `from __future__ import annotations` line is added back to any file
— a test that cannot fail is not proof. Check the flake has a written verdict, not a
disposition; "seems flaky" is not an explanation.
