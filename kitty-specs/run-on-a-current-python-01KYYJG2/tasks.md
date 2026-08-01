# Tasks: Run on a current Python

**Mission**: `run-on-a-current-python-01KYYJG2` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)
**Branch**: `kitty/mission-current-python` · **Supersedes**: issue #13
**Status: complete.** Shipped in two releases, both proved running on both hubs —
**v0.35.0** (the floor: WP01 + WP03, one unit because the charter requires it) and
**v0.36.0** (WP02, the annotation removal). T008 was pulled forward into the first ship,
because the floor move is what exposed the failure it deals with.

**The charter was amended first, on `main` (2026-08-01, commit `6393e2b`)** — it now says the
floor is 3.14 and the ambition is the latest Python. That was the mission's blocking
conflict, and it was deliberately settled *outside* this mission: a mission that resolves a
charter conflict by editing the charter is a mission where the charter stopped governing
anything.

So there is no charter subtask here. The mission now implements a policy that already exists.

| WP | Goal | Depends on |
|---|---|---|
| WP01 | The floor says 3.14, and the gates pass at 3.14 semantics | — |
| WP02 | The code: PEP 649 removal, the 3.14-only failure, and the outside review | WP01 |
| WP03 | The image, CI, and every sentence that states a version | WP01 |

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | `requires-python` and the trove classifiers | WP01 | |
| T002 | ruff `target-version` and pyright `pythonVersion` | WP01 | |
| T003 | Re-run the four gates at 3.14 semantics and triage pyright | WP01 | |
| T004 | Regenerate the lock with the same dependency set | WP01 | |
| T005 | Remove `from __future__ import annotations` — all 90 files | WP02 | |
| T006 | Prove the removal changed no behaviour | WP02 | |
| T007 | The grep proof, as a test | WP02 | |
| T008 | Characterise and settle the intermittent `UnicodeDecodeError` | WP02 | [P] |
| T009 | Directive 4 — outside model review before the mission closes | WP02 | |
| T010 | Both `Dockerfile` stages move to `python:3.14-slim` | WP03 | [P] |
| T011 | The gates pass **inside** the container | WP03 | |
| T012 | Collapse the CI matrix to 3.14 alone | WP03 | [P] |
| T013 | README, CONTRIBUTING, `.kittify/metadata.yaml` | WP03 | [P] |

**The floor moves as one change or not at all.** The charter now states this explicitly:
`requires-python`, the classifiers, ruff's `target-version`, pyright's `pythonVersion`, both
`Dockerfile` stages and CI — all of them, or none. They are split across WP01 and WP03 for
ownership reasons, not because either half is shippable alone.

---

## WP01 — The floor says 3.14

**Goal**: the build metadata says 3.14 and all four gates pass with pyright analysing 3.14
semantics rather than 3.12's.
**Independent test**: `uv sync` on a machine with only 3.12 available refuses, naming 3.14.

- [x] T001 `requires-python` and the trove classifiers (WP01)
- [x] T002 ruff `target-version` and pyright `pythonVersion` (WP01)
- [x] T003 Re-run the four gates at 3.14 semantics and triage pyright (WP01)
- [x] T004 Regenerate the lock with the same dependency set (WP01)

**Risks**: T003 is the only step whose size is genuinely unknown. Phase 0 saw pyright report
zero errors — but it was still configured as 3.12, so that number proves nothing about T002's
effect. Expect churn and treat each complaint as a finding.

---

## WP02 — The code

**Goal**: no module carries a redundant `__future__` import, the removal is shown not to
change behaviour, the 3.14-only failure is explained rather than tolerated, and an outside
model has reviewed the result.
**Independent test**: the full suite runs ten times consecutively without a failure.

- [x] T005 Remove `from __future__ import annotations` — all 90 files (WP02)
- [x] T006 Prove the removal changed no behaviour (WP02)
- [x] T007 The grep proof, as a test (WP02)
- [x] T008 Characterise and settle the intermittent `UnicodeDecodeError` (WP02) [P]
- [x] T009 Directive 4 — outside model review before the mission closes (WP02)

**T006 exists because the plan was wrong to call T005 mechanical.** `from __future__ import
annotations` is PEP 563 — it stringifies annotations. PEP 649 hands over real objects.
Removing the import changes what `__annotations__` yields at runtime, and this project gives
annotated types to **litestar, msgspec, click and mcp**, all of which introspect them. NFR-001
claims no behaviour change; that is a claim to be proved, not assumed. Phase 0's 961/18
baseline was measured **with those imports still in place**, so it does not cover this.

**T009 runs last and covers the whole mission.** Directive 4 wants one narrow question, and
this mission has an obvious one: *"does removing `from __future__ import annotations` change
any runtime behaviour in a codebase that hands annotated types to litestar and msgspec?"*

---

## WP03 — The image, CI, and the words

**Goal**: everything that states a Python version states 3.14, and the container is proved
rather than assumed.
**Independent test**: `docker run` the built image and the four gates pass inside it.

- [x] T010 Both `Dockerfile` stages move to `python:3.14-slim` (WP03) [P]
- [x] T011 The gates pass **inside** the container (WP03)
- [x] T012 Collapse the CI matrix to 3.14 alone (WP03) [P]
- [x] T013 README, CONTRIBUTING, `.kittify/metadata.yaml` (WP03) [P]

**Risks**: T010 has two `FROM` lines — build and runtime — and changing only one produces an
image that builds on 3.14 and runs on 3.12. T011 is what catches that, and it is not
satisfied by a laptop run.

**T012 deletes a matrix rather than editing it.** The charter now settles this: CI runs one
version, "because a matrix on an application tests a configuration nobody ships".

## MVP scope

WP01 alone is coherent: the floor moves and the gates pass. WP02 and WP03 make it complete
and honest. If the mission is cut short, stop after a whole WP — a partial T005 is the worst
state available, because the codebase then has two annotation conventions and no way to tell
which file follows which.
