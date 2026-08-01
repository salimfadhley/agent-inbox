---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: run-on-a-current-python-01KYYJG2
mission_id: 01KYYJG2FGSXDRZCG1XBEDWRER
generated_at: '2026-08-01T14:45:00.509121+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/run-on-a-current-python-01KYYJG2/spec.md
    sha256: 7f5a8bf01a02145d9e101d764b403b7fd76e491fd1a909856a0a220e8e44af1b
  plan.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/run-on-a-current-python-01KYYJG2/plan.md
    sha256: 6771a15bdefa1545de38d35cd8159d4a556a28a33bd108c0e1b69035a09f3cc1
  tasks.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/run-on-a-current-python-01KYYJG2/tasks.md
    sha256: e02d0b1d703c5ab6ea687b76904ee83dce1acb24ef35b168bf4a1fdbf94d5262
  charter:
    path: /Users/salimfadhley/workspace/agent-inbox/.kittify/charter/charter.md
    sha256: dc24f43bde1a5b81568f486f9084753c30daab2d302f1227dae097434e9e6882
verdict: blocked
issue_counts:
  low: 1
  high: 2
  medium: 1
  critical: 1
  info: 0
findings:
- id: A1
  severity: critical
  category: charter-alignment
  summary: FR-001 moves the floor to 3.14, directly contradicting the charter's stated stack of "Python 3.12+ only".
- id: A2
  severity: high
  category: correctness
  summary: FR-004's removal of `from __future__ import annotations` is not behaviour-neutral as NFR-001 assumes, and Phase 0 never tested it.
- id: A3
  severity: high
  category: coverage
  summary: Charter Directive 4 (outside model review before a mission closes) is named in plan.md but has no task and no Definition-of-Done item.
- id: A4
  severity: medium
  category: process
  summary: T001 hand-edits charter.md, contrary to the charter's own Amendment Process, which routes governance changes through /spec-kitty.charter.
- id: A5
  severity: low
  category: inconsistency
  summary: Spec open question 3 is answered in plan.md but still listed as unresolved in spec.md.
---

## Specification Analysis Report

**Mission**: `run-on-a-current-python-01KYYJG2` · **Branch**: `kitty/mission-current-python`
**Artifacts**: spec.md, plan.md, tasks.md, 3 WP prompts · **Charter**: loaded and checked

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| A1 | Charter alignment | **CRITICAL** | `.kittify/charter/charter.md:50` vs `spec.md` FR-001 | The charter states the stack as **"Python 3.12+ only"**. FR-001 moves the floor to `>=3.14`. The charter is non-negotiable within a mission's scope. | Amend the charter **before** this mission runs, as a separate explicit act, not as WP01/T001 inside it. Then FR-001 is compliant rather than conflicting. |
| A2 | Correctness | **HIGH** | `spec.md` FR-004 + NFR-001; `plan.md` "all or none"; `WP02` T006 | FR-004 is described as removing a line "PEP 649 makes redundant", and the plan calls it "mechanical". **It is not equivalent.** `from __future__ import annotations` is PEP 563 — it stringifies annotations. PEP 649 gives real objects, lazily. Removing the import changes what `__annotations__` yields at runtime, and this project hands annotated types to **pydantic, litestar, msgspec and click**, all of which introspect them. NFR-001 says "no behaviour change"; this change is not provably one. Worse: **Phase 0 proved the interpreter move, not this.** The 961-pass baseline was measured with the `__future__` imports still in place. | Do not treat T006 as a no-op. Run the full suite immediately after the removal and before anything else in WP02, and record that result as a distinct proof from the Phase 0 baseline. If FR-004 turns out to change behaviour, it is a separable mission — say so rather than absorbing it. |
| A3 | Coverage | **HIGH** | `plan.md` Charter Check; `tasks.md`; all three WP prompts | Directive 4 requires an outside model review before every mission closes, with a named invocation and the instruction to ask one narrow question. `plan.md` lists it under Charter Check and then nothing implements it: no subtask, no Definition-of-Done line, no WP. | Add a closing subtask that runs the review with a narrow question — the obvious one being *"does removing `from __future__ import annotations` change any runtime behaviour in a codebase using pydantic and litestar?"*, which is A2's question and the mission's real risk. |
| A4 | Process | MEDIUM | `WP01` T001; `.kittify/charter/charter.md:125` | T001 instructs the implementer to edit `charter.md` by hand and then update `answers.yaml` "for consistency". The charter's Amendment Process specifies the opposite order and a different mechanism: *"edit answers.yaml, regenerate, commit"* via `/spec-kitty.charter`. A hand-edited charter is overwritten the next time anyone regenerates. | Rewrite T001 to follow the documented process, or — better, per A1 — remove it from the mission and do the amendment beforehand. |
| A5 | Inconsistency | LOW | `spec.md` open question 3 | The spec lists *"Is anything actually pinned to 3.12?"* as still to check. `plan.md` answers it exhaustively: nothing is pinned; every occurrence is a declaration. | Close the question in the spec with a one-line pointer to the plan's table, as questions 1 and 2 already are. |

### Coverage Summary

| Requirement | Has task? | Task IDs | Notes |
|---|---|---|---|
| FR-001 (floor `>=3.14`) | Yes | T002 | Blocked by A1 until the charter is amended |
| FR-002 (CI on 3.14) | Yes | T012 | Plan correctly reads this as *collapse* the matrix, not edit it |
| FR-003 (image runs 3.14, gates pass inside) | Yes | T010, T011 | T011 is the half that is usually skipped; the WP calls that out |
| FR-004 (`__future__` removal, complete) | Yes | T006, T007 | See A2 — coverage exists, the risk assessment does not |
| FR-005 (docs state the version) | Yes | T013 | Correctly excludes `doc/session_logs/` as dated records |
| FR-006 (no pinned exception) | Yes | T005 | Phase 0 already demonstrates this is achievable |
| NFR-001 (no behaviour change) | Partial | T004, T009 | The 961/18 baseline is recorded, but see A2 — it does not cover FR-004 |

**Coverage: 7/7 requirements have at least one task (100%).** The gap is not coverage; it is
that one requirement's risk is understated.

### Charter Alignment Issues

- **A1** — `charter.md:50` vs FR-001. Critical, and the mission's own remediation route (A4)
  does not follow the charter's Amendment Process.
- **A3** — Directive 4 unimplemented.
- Directive 6 (repay debt completely) is **well served**: FR-004's all-or-none rule and
  T007's grep proof are exactly what the directive asks for.
- Directive 1's coding standards mention "mature pinned dependencies"; FR-006 forbids adding
  a pin. These do not actually conflict — the project uses `>=` floors throughout, and FR-006
  forbids a *cap added as a workaround*, which is a different thing. Noted so it is not
  raised again.

### Unmapped Tasks

None. All 13 subtasks map to a requirement.

### Metrics

- Requirements: 6 functional + 1 non-functional = **7**
- Work packages: **3** (5 / 4 / 4 subtasks — all within the 3–7 target)
- Subtasks: **13**
- Coverage: **100%**
- Ambiguity count: **1** (A2 — "mechanical" understates a semantic change)
- Duplication count: **0**
- Critical issues: **1**

### Notable strength

Phase 0 was run empirically rather than assumed, and it **overturned the spec's own risk
ranking**: dependency wheels — named as the biggest hazard — installed cleanly with no pin,
while an intermittent 3.14-only `UnicodeDecodeError` that nobody had predicted is now the
mission's one open technical unknown. Recording the 961/18 baseline in the plan is what makes
NFR-001 falsifiable instead of decorative.

## Next Actions

1. **Amend the charter first, outside this mission** (A1, A4). One line, and it unblocks
   everything.
2. **Re-scope T006's risk** (A2) — add an explicit post-removal suite run, distinct from the
   Phase 0 baseline.
3. **Add the Directive 4 review subtask** (A3), with the narrow question already identified.
4. **Close spec open question 3** (A5).

None of these require re-planning. A1 and A4 are one act; A2, A3 and A5 are edits.
