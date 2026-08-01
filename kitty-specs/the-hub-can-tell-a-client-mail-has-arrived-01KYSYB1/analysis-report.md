---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1
mission_id: 01KYSYB1Z1AQ10BRB4Z4JT2X4A
generated_at: '2026-08-01T21:00:53.778154+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1/spec.md
    sha256: 70d8f98270f154f537500d55961d5cb495a2f1abcda52333ed4c29ac67e30408
  plan.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1/plan.md
    sha256: 5ef05512cb26151d5bd6c8cea06262aee1d99b4c774bcea56d16c0368f838b16
  tasks.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1/tasks.md
    sha256: d3e759c81aa5659eb63d9f28ee081f3648405d42d31d7bb16a7d5945d400b949
  charter:
    path: /Users/salimfadhley/workspace/agent-inbox/.kittify/charter/charter.md
    sha256: 60d2cf409053f355263370262c9ac83e2b45cc91c21b18b68a3b0f8a47d7a26a
verdict: ready
issue_counts:
  critical: 0
  low: 2
  high: 0
  medium: 3
  info: 0
findings:
- id: A1
  severity: medium
  category: coverage
  summary: The spec's presence section describes connection events becoming history; no FR states it and no work package delivers it.
- id: A2
  severity: medium
  category: inconsistency
  summary: T017 names prompts.py, but the mid-turn promise also lives in mcp_client.py, which WP03 does not own.
- id: A3
  severity: medium
  category: coverage
  summary: WP01 ships before it is known whether a held connection survives the deployments in use; T008 can only run afterwards.
- id: A4
  severity: low
  category: inconsistency
  summary: The plan's Technical Context still says Python 3.12+, stale since the floor moved to 3.14.
- id: A5
  severity: low
  category: ambiguity
  summary: "'An event within a second' stays the spec's only number and stays unmeasured until T008 runs."
---

## Specification Analysis Report

Mission `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`, spec + plan + tasks,
2026-08-01. This supersedes nothing in [pre-tasks-review.md](pre-tasks-review.md); that
document was written before `tasks.md` existed and asked to be re-run once it did. Its C1
and C2 are now subtasks (T005), and its A1 survives here as A5.

| ID | Category | Severity | Location | Summary | Recommendation |
|----|----------|----------|----------|---------|----------------|
| A1 | Coverage | MEDIUM | spec "presence stops being a guess"; tasks.md | The spec accepts a **history change** — the hub starts recording sessions as well as actions — as a net bonus. No FR states it and no subtask delivers it. It is currently a paragraph of consequence with nothing behind it | Decide explicitly: either say it is out of scope for this mission and belongs with issue #7, or add an FR. Do not leave it as prose that reads like a deliverable |
| A2 | Inconsistency | MEDIUM | WP03 T017 vs WP02 `owned_files` | T017 says the promise lives in `prompts.py` and `mcp_client.py`. It does: `mcp_client.py:73` ("Mail cannot reach you mid-turn") and `prompts.py:382` ("…interrupt you, so looking is how you notice mail"). But WP03's `owned_files` lists only `prompts.py`, so the WP that must fix the promise cannot touch half of it | Add `src/agent_inbox/mcp_client.py` to WP03's ownership, or note the crossing. The WPs ship sequentially so there is no collision risk — the risk is a promise corrected in one file and left standing in the other, which is worse than not correcting it |
| A3 | Coverage | MEDIUM | plan Phase 0 Q1; WP01 T008 | WP01 ships **before** anyone knows whether a held stream survives Fly's TLS termination and a scale-to-zero host. This is forced — there is no streaming route to measure until WP01 builds one — but it means the first release carries an unproved transport assumption | Accepted, and recorded here so it is not discovered as a surprise. T008 runs immediately after the WP01 deploy, against both hubs, and a bad answer changes WP02 rather than invalidating WP01 |
| A4 | Inconsistency | LOW | plan Technical Context | "Language/Version: Python 3.12+, as the rest of the codebase". The floor moved to 3.14 on 2026-08-01 (v0.35.0) and the charter now requires every statement of it to agree | One-line correction to `plan.md` |
| A5 | Ambiguity | LOW | spec test matrix; WP01 T008 | "Event within a second" is still the only number in the spec and still nothing measures it. Carried from the pre-tasks review's A1 | T008 measures it. Either the measurement supports it as a criterion or the spec should call it an aspiration — settle it there rather than in a later mission |

**Coverage summary**

| Requirement | Has a subtask? | Where |
|---|---|---|
| FR-001 stream exists | yes | T002 |
| FR-002 no body | yes | T005 |
| FR-003 polling stays the floor | yes | T005, T011 |
| FR-004 one identity | yes | T002, T004 |
| FR-005 a drop loses nothing | yes | T010, T011 |
| FR-006 harness-agnostic | yes | T003, T013 |
| FR-007 bounded, observable | yes | T006 |
| FR-008 actionable event | yes | T005 — was the review's C1 |
| FR-009 mail unchanged | yes | T005 — was the review's C2 |
| FR-010 decision layer | yes | T013 |
| FR-011 no sender priority | yes | T016, proved by removal |
| FR-012 default-safe | yes | T013 |
| FR-013 rate-limited | yes | T014 |
| FR-014 observable decisions | yes | T015 |
| FR-015 docs change | yes | T017 — see A2 |

**Charter alignment**: no conflicts. ADR 0005, ADR 0008 and `live-session-push` rule 1 are
each named in the plan's charter check with the constraint each imposes, and FR-011 is ADR
0008 restated at the layer where it would otherwise be lost. The charter's ship-early rule is
satisfied by construction: three work packages, three releases, each proved on both hubs.

**Unmapped subtasks**: none. Every subtask traces to a requirement or is a Directive 4
review.

**Metrics**
- Requirements: 15
- Covered by a subtask: 15 (100%)
- Work packages: 3 · Subtasks: 18
- Critical issues: 0 · High: 0
- Ambiguities: 1 · Duplications: 0

## Next actions

Nothing blocks implementation. A2 is worth fixing before WP03 starts rather than during it —
it is a two-word edit to a file list, and the failure it prevents (one file corrected, the
other left promising the opposite) is the kind that reads as done. A4 is one line. A1 is a
decision rather than an edit, and it can wait until WP01 has shipped, since the connection
count it depends on does not exist yet.

The strongest thing about this breakdown is that WP01 and WP02 are **inert on purpose**. A
mission that changes what agents experience only in its final package is one where the first
two releases cannot surprise anybody, and where the behaviour change and the documentation
that describes it land in the same commit.
