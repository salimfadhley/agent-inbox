---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: a-hub-has-a-name-of-its-own-01KYMD90
mission_id: 01KYMD908KH6MDBBNCC13RR1S2
generated_at: '2026-07-28T14:45:54.147754+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md
    sha256: 6e604f421733f9b0fc671ce40cdeff7215e25197156a8728c5bd07d9c80d0764
  plan.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/plan.md
    sha256: 59e38be4cd3b390831b49ac34326c89acfe32b704be8ed615ae6f093235b5d54
  tasks.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/tasks.md
    sha256: 17a815f049dc2857baa6956c5d8c5420ee85d42e32a112836bf69fe5fc8b860a
  charter:
    path: /Users/salimfadhley/workspace/agent-inbox/.kittify/charter/charter.md
    sha256: 3c756388898e6362505fb4d4b997aba27194075e9331f6992e5a1a6a6a1c2792
verdict: blocked
issue_counts:
  medium: 4
  critical: 2
  low: 2
  high: 4
  info: 0
findings:
- id: D1
  severity: critical
  category: charter
  summary: Charter mandates agent-mailbox / AGENT_MAILBOX_* and declares agent-inbox history with no back-compat; every mission artefact and the shipped code use agent_inbox / AGENT_INBOX_* with deliberate fallbacks.
- id: D2
  severity: critical
  category: charter
  summary: Deployment-specific hostnames (halob, halob.local:8081, localhost:8080) appear in spec.md, research.md and source-register.csv; the charter forbids them in code, docs or tests.
- id: G1
  severity: high
  category: charter
  summary: Charter mandates four quality gates; all five work packages name only three, omitting ruff format --check.
- id: G2
  severity: high
  category: coverage
  summary: Charter directive 4 requires an outside model review before a mission closes; no subtask in tasks.md represents it.
- id: C1
  severity: high
  category: coverage
  summary: NFR-003 is mapped to WP03 but no subtask asserts it; the spec's 'two addresses, one hub' and 'public URL changed' rows are uncovered.
- id: I1
  severity: high
  category: inconsistency
  summary: The contract settles GET /hub/settings as operator-gated; WP03 T012 hands that decision back to the implementer.
- id: I2
  severity: medium
  category: inconsistency
  summary: 'Unset title/description have two wire shapes: GET / omits them, while the GET /hub/settings example emits an empty string with source default.'
- id: I3
  severity: medium
  category: inconsistency
  summary: spec.md anchors 'the identity survives the address' to the last-but-one test-matrix row, which is about enabling federation after renaming.
- id: C2
  severity: medium
  category: coverage
  summary: Test-matrix row 'renaming back to local with federation on' has no functional requirement and no subtask.
- id: I4
  severity: medium
  category: inconsistency
  summary: plan.md's Project Structure omits src/agent_inbox/federation.py, which WP05 creates, and IC-07 still names test_console.py where WP05 uses tests/test_hub_identity.py.
- id: A1
  severity: low
  category: ambiguity
  summary: The contract's 422 row reads 'body names the rule, in the shape unknown_recipient set', which does not parse to a definite error shape.
- id: U1
  severity: low
  category: duplication
  summary: FR-006 is mapped to both WP02 and WP05 without a note explaining the deliberate split between the default name and the federation gate.
---

## Specification Analysis Report

Mission `a-hub-has-a-name-of-its-own-01KYMD90`, analysed on branch `feat/hub-identity`
against `spec.md`, `plan.md`, `tasks.md`, `research.md`, `data-model.md`,
`contracts/hub-settings.md`, `quickstart.md` and `.kittify/charter/charter.md`.

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| D1 | Charter | CRITICAL | charter.md:62; spec.md, plan.md, all WPs | The charter states the project is `agent-mailbox` (package `agent_mailbox`, command `agent-mailbox`, env `AGENT_MAILBOX_*`) and that "earlier names (`agent-mail`, `agent-inbox`) are history, not aliases — the new system carries no back-compat for them". The shipped system is `agent_inbox` with `AGENT_INBOX_*` and deliberate legacy fallbacks (v0.25.0, operator-directed), and every artefact here follows the shipped system. | The mission is right and the charter is stale. Update the charter's Naming & consistency clause in a separate charter change; do not dilute the mission. Until then this analysis is blocked on a governance document that contradicts the product. |
| D2 | Charter | CRITICAL | spec.md:17-18,27-28; research.md:16-17,22-23; research/source-register.csv:14 | `halob`, `halob.local:8081` and `localhost:8080` appear in committed mission artefacts. The charter's policy summary requires the project to remain generic with "no deployment-specific hostnames, IPs, secrets, or organisation names in code, docs, or tests". | Generalise to placeholders (`hub.example:8081`, "a second address on the same machine") while keeping the incident narrative, which is what gives the mission its evidence. The source register can cite "the deployed hub" without naming the host. |
| G1 | Charter | HIGH | WP01:272, WP02:215, WP03:236, WP04:223, WP05:236 | Every Definition of Done reads "`ruff`, `pyright` and `pytest` pass". The charter mandates four gates: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`. `ruff format --check` is named nowhere. | Add the fourth gate to each DoD. CI enforces it regardless, so the risk is wasted round-trips rather than a bad merge — but a DoD that under-states the bar is the wrong document to leave wrong. |
| G2 | Coverage | HIGH | tasks.md (whole); charter.md:75-89 | Charter directive 4 is a standing instruction to have an outside model review every mission before it closes, with a worked method (one narrow question, `codex exec` under a hard alarm). No work package or subtask carries it. | Add a closing subtask to WP05, or an explicit note in tasks.md that the review runs outside the WP structure. The directive names two live bugs it caught; leaving it implicit is how it gets skipped. |
| C1 | Coverage | HIGH | tasks.md:WP03; spec.md test matrix rows 7-8; NFR-003 | NFR-003 ("identity survives the address changing") is mapped to WP03, but none of T011–T016 asserts it. The spec's own matrix rows — "Two addresses, one hub → both report the same `name`" and "Public URL changed → `name` unchanged" — have no subtask. This is the mission's headline claim and the exact mistake that prompted it. | Add a subtask to WP03: change `AGENT_INBOX_PUBLIC_URL`, assert `name` is unchanged; request the descriptor by two different addresses, assert both report the same `name`. |
| I1 | Inconsistency | HIGH | contracts/hub-settings.md (GET /hub/settings); WP03 T012 | The contract states the route is operator-gated. WP03 T012 instructs the implementer to "decide the read gate deliberately and record why". A contract that settled a decision and a task that reopens it will not both be obeyed. | Make T012 follow the contract. If the contract's choice is wrong, change the contract — but one of the two must stop being authoritative. |
| I2 | Inconsistency | MEDIUM | contracts/hub-settings.md (both examples); data-model.md:20; WP03 T011; WP04 T018 | `GET /` omits an unset `title`, and the text is emphatic ("omitted, not empty"). The `GET /hub/settings` example emits `"description": { "value": "", "source": "default" }`. FR-009 says the fields "may be empty". Three artefacts describe unset differently. | Decide once: absent everywhere, or `""` with `source: default` on the settings route only, stated explicitly. WP04's rendering depends on telling unset from cleared. |
| I3 | Inconsistency | MEDIUM | spec.md:161 | "The last-but-one row is the mission in a line: **the identity survives the address.**" The last-but-one row is "Enabling federation after renaming → permitted". The address rows are 7 and 8. | Re-anchor the sentence to the "Public URL changed" row, or move that row. The sentence carries the mission's thesis, so a wrong pointer is worse here than elsewhere. |
| C2 | Coverage | MEDIUM | spec.md test matrix row 12 | "Renaming back to `local` with federation on → refused, or federation disabled — must be deliberate, not incidental" has no FR and no subtask. WP05 covers only *enabling*. | Either record it as out of scope alongside the federation switch (consistent with WP05's deliberate narrowing) or give it a subtask. Right now it is neither. |
| I4 | Inconsistency | MEDIUM | plan.md:63-76,163 | The Project Structure block does not list `src/agent_inbox/federation.py`, which WP05 creates, and IC-07's affected surfaces still name `test_console.py` where WP05 now uses `tests/test_hub_identity.py`. Both are drift introduced when WP05 was rescoped to resolve file-ownership overlap. | Update plan.md's structure block and IC-07. The rescoping was correct; the plan simply has not caught up. |
| A1 | Ambiguity | LOW | contracts/hub-settings.md (responses table) | The `422` row reads "body names the rule, in the shape `unknown_recipient` set". This does not resolve to a definite error shape. | Restate as "the same error envelope as `unknown_recipient`", or name the envelope directly. |
| U1 | Duplication | LOW | WP02 and WP05 `requirement_refs` | FR-006 is claimed by both packages. The split is deliberate — WP02 accepts `local` as a name, WP05 blocks federation on it — but nothing records that, so it reads as a mapping error. | Add one line to tasks.md noting the split. |

### Coverage Summary

| Requirement Key | Has Task? | Task IDs | Notes |
|-----------------|-----------|----------|-------|
| `hub-reports-name-title-description` (FR-001) | yes | T011 | |
| `name-validated-as-address-component` (FR-002) | yes | T007, T008, T010 | |
| `all-three-settable-and-persistent` (FR-003) | yes | T001, T002, T003 | |
| `environment-overrides-without-erasing` (FR-004) | yes | T004, T006 | The strongest-covered requirement, correctly |
| `governed-field-renders-disabled` (FR-005) | yes | T019, T021 | |
| `local-default-and-federation-gate` (FR-006) | yes | T010, T022, T023 | Split across WP02/WP05 — see U1 |
| `federation-tab-holds-fields` (FR-007) | yes | T017, T021 | |
| `editing-is-operator-gated` (FR-008) | yes | T013, T016 | |
| `title-description-free-text-may-be-empty` (FR-009) | yes | T011 | Wire shape for "empty" is unsettled — see I2 |
| `prompt-introduces-the-hub` (FR-010) | yes | T024, T025 | |
| `no-new-mount-no-config-file` (NFR-001) | yes | T001 | |
| `unconfigured-hub-behaves-as-today` (NFR-002) | yes | T006, T011 | |
| `identity-survives-the-address` (NFR-003) | **no** | — | Mapped to WP03; no subtask asserts it — see C1 |

### Charter Alignment Issues

- **D1** — naming. The charter names a package, command and environment prefix the product
  no longer uses, and forbids back-compat the product deliberately ships. This is a stale
  governance document, not a mission defect, but it is the charter that is authoritative
  until changed, so it must be changed.
- **D2** — deployment specifics. Committed artefacts name the operator's actual machine.
- **G1** — quality gates. Three of four named.
- **G2** — outside review. Directive 4 unrepresented in the task breakdown.

Nothing in this mission conflicts with the binding ADRs. ADR 0005 (one API, every client
is a client) is honoured — the console reads and writes through the API and WP04 forbids it
recomputing precedence. ADR 0008 (no actor has authority) is honoured, and WP03 T016 asserts
it with a real device token rather than a mocked dependency. ADR 0003 is the mission's own
argument, applied one level up.

### Unmapped Tasks

- **T026** (documentation) maps to charter directive 2 rather than to a functional
  requirement. Correct as written; noted so the mapping does not read as an omission.
- **T023** (prove the gate's test by removing the rule) serves FR-006 indirectly. It is
  process rather than product, and belongs where it is.

### Metrics

- Total requirements: **13** (10 functional, 3 non-functional)
- Total tasks: **26** across 5 work packages
- Coverage: **12 / 13 = 92%** (NFR-003 uncovered)
- Ambiguity count: **1**
- Duplication count: **1**
- Critical issues: **2**

### Next Actions

Verdict is **blocked**, on two charter conflicts and four high findings.

Neither critical finding is a defect in the mission's design, which is worth stating
plainly: D1 is a charter that has not caught up with an operator-directed rename, and D2 is
a hostname left in narrative prose. Both are cheap to fix and neither implies rework.

Recommended order:

1. **D2** — generalise the hostnames in `spec.md`, `research.md` and
   `research/source-register.csv`. Editing only; no design change.
2. **C1** — add the NFR-003 subtask to WP03. This is the one finding that would otherwise
   ship a mission whose headline claim is untested.
3. **I1, I2** — settle the `GET /hub/settings` gate and the unset-field wire shape in
   `contracts/hub-settings.md`, then make WP03/WP04 follow it.
4. **G1, G2** — add the fourth gate to each DoD, and place the outside-model review.
5. **I3, I4, C2, A1, U1** — documentation corrections, safe to batch.
6. **D1** — raise separately as a charter amendment via `/spec-kitty.charter`. It is outside
   this command's remit and should not be folded into the mission.

Items 1–5 are edits to mission artefacts and can be made without re-running `/specify` or
`/plan`. Item 6 is governance.
