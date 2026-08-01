# Tasks: Run on a current Python

**Mission**: `run-on-a-current-python-01KYYJG2` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)
**Branch**: `kitty/mission-current-python` · **Supersedes**: issue #13

Three work packages. **WP01 is a gate, not a phase** — until the charter says 3.14, every
other edit in this mission contradicts the project's own governing document. After WP01,
WP02 and WP03 are genuinely independent and run in parallel.

| WP | Goal | Depends on |
|---|---|---|
| WP01 | The charter and the floor say 3.14 | — |
| WP02 | The code: PEP 649 removal, and the failure only 3.14 shows | WP01 |
| WP03 | The image, CI, and every sentence that states a version | WP01 |

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | Amend the charter's stated stack to 3.14+ | WP01 | |
| T002 | `requires-python` and the trove classifiers | WP01 | |
| T003 | ruff `target-version` and pyright `pythonVersion` | WP01 | |
| T004 | Re-run the four gates at 3.14 semantics and triage pyright | WP01 | |
| T005 | Regenerate the lock with the same dependency set | WP01 | |
| T006 | Remove `from __future__ import annotations` — all 90 files | WP02 | |
| T007 | The grep proof, as a test | WP02 | |
| T008 | Characterise the intermittent `UnicodeDecodeError` | WP02 | [P] |
| T009 | Fix it, or record the upstream issue and scope a workaround | WP02 | |
| T010 | Both `Dockerfile` stages move to `python:3.14-slim` | WP03 | [P] |
| T011 | The gates pass **inside** the container | WP03 | |
| T012 | Collapse the CI matrix to 3.14 alone | WP03 | [P] |
| T013 | README, CONTRIBUTING, `.kittify/metadata.yaml` | WP03 | [P] |

---

## WP01 — The charter and the floor say 3.14

**Goal**: the project's governing document and its build metadata agree that the floor is
3.14, and the four gates pass with pyright analysing 3.14 semantics.
**Independent test**: `uv sync` on a machine with only 3.12 available refuses, with a
message naming 3.14.

- [ ] T001 Amend the charter's stated stack to 3.14+ (WP01)
- [ ] T002 `requires-python` and the trove classifiers (WP01)
- [ ] T003 ruff `target-version` and pyright `pythonVersion` (WP01)
- [ ] T004 Re-run the four gates at 3.14 semantics and triage pyright (WP01)
- [ ] T005 Regenerate the lock with the same dependency set (WP01)

**Risks**: T004 is the only step in this mission whose size is genuinely unknown. Phase 0
saw pyright report zero errors — but it was still configured as 3.12, so that number proves
nothing about T003's effect. Expect churn and treat each complaint as a finding.

**T001 is not paperwork.** `.kittify/charter/charter.md:50` currently says "Python 3.12+
only". Leave it and the mission ships a codebase that its own charter forbids.

---

## WP02 — The code

**Goal**: no module carries a redundant `__future__` import, and the failure that only
appears on 3.14 is explained rather than tolerated.
**Independent test**: the full suite runs ten times consecutively without a failure.

- [ ] T006 Remove `from __future__ import annotations` — all 90 files (WP02)
- [ ] T007 The grep proof, as a test (WP02)
- [ ] T008 Characterise the intermittent `UnicodeDecodeError` (WP02) [P]
- [ ] T009 Fix it, or record the upstream issue and scope a workaround (WP02)

**Risks**: T006 is 90 files of mechanical edit, which is exactly the shape of change that
gets done to 88 of them. T007 exists because eyes do not count to 90; the grep does.

**T009 may enlarge this mission, and that is the correct outcome** if the cause turns out to
be ours. A blanket skip on `test_any_operator_can_be_removed` would close the mission and
leave a defect with a permanent home.

---

## WP03 — The image, CI, and the words

**Goal**: everything that states a Python version states 3.14, and the container is proved
rather than assumed.
**Independent test**: `docker run` the built image and the four gates pass inside it.

- [ ] T010 Both `Dockerfile` stages move to `python:3.14-slim` (WP03) [P]
- [ ] T011 The gates pass **inside** the container (WP03)
- [ ] T012 Collapse the CI matrix to 3.14 alone (WP03) [P]
- [ ] T013 README, CONTRIBUTING, `.kittify/metadata.yaml` (WP03) [P]

**Risks**: T010 has two `FROM` lines — build and runtime — and changing only one produces an
image that builds on 3.14 and runs on 3.12. T011 is what catches that, and it is not
satisfied by a laptop run.

**T012 deletes a matrix rather than editing it.** FR-002 says "the four gates on 3.14",
singular; a `["3.12","3.14"]` matrix would keep testing a configuration nobody ships and
tell the next reader the floor is still 3.12.

## MVP scope

WP01 alone is coherent: the floor moves and the gates pass. WP02 and WP03 make it complete
and honest. If the mission is cut short, stop after a whole WP — a partial T006 is the worst
state available, because the codebase then has two annotation conventions and no way to tell
which file follows which.
