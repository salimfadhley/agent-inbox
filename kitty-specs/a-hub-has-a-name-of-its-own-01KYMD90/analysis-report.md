---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: a-hub-has-a-name-of-its-own-01KYMD90
mission_id: 01KYMD908KH6MDBBNCC13RR1S2
generated_at: '2026-07-28T14:57:19.549917+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md
    sha256: 6ee61d943208d2bcc4d9a26d612499c9ed363d7fdad064b55a7d037414ac6480
  plan.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/plan.md
    sha256: 7fcc794d3a9e1e3002d4a40a8fdfe4b0f542044e87359c70eefd661c0b328e2b
  tasks.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/tasks.md
    sha256: bc6d400e5206fcd023690437dee63a97c3a2c69144887446e721bb353005bea8
  charter:
    path: /Users/salimfadhley/workspace/agent-inbox/.kittify/charter/charter.md
    sha256: 1dd7de897aa496a1548e038f9fb9e0c214bfffedd241429e90e32c57d3aeec0f
verdict: ready
issue_counts:
  critical: 0
  high: 0
  low: 0
  medium: 0
  info: 0
findings: []
---

## Specification Analysis Report

Second pass on mission `a-hub-has-a-name-of-its-own-01KYMD90`, branch `feat/hub-identity`,
after remediating all twelve findings from the first pass. Same artefacts, same charter,
same detection passes.

**No findings survive.** Detail below is the disposition of the first pass, kept so the
verdict change is auditable rather than merely asserted.

| ID | First pass | Disposition |
|----|-----------|-------------|
| D1 | CRITICAL — charter named the project `agent-mailbox` and forbade the back-compat the product ships | Charter's Naming & consistency clause rewritten: project is `agent-inbox`, back-compat is deliberate and enumerated, `agent-mail` carries no alias. Stale `src/agent_mailbox_old/` path and the contradicting `pyproject.toml` comment corrected in the same change. |
| D2 | CRITICAL — deployment-specific hostnames in committed artefacts | 77 occurrences across 35 tracked files replaced with generic placeholders. Repo-wide sweep confirms zero remaining. No secrets or IPs were present. |
| G1 | HIGH — three of four charter gates named in every DoD | All five Definitions of Done now name `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`. |
| G2 | HIGH — charter directive 4 unrepresented | T028 added to WP05, carrying the narrow question to ask and the invocation the charter specifies. |
| C1 | HIGH — NFR-003 mapped but unasserted | T027 added to WP03: public URL changes, `name` does not; two addresses, one `name`; asserted in the store as well as the response. |
| I1 | HIGH — contract settled the `GET /hub/settings` gate, WP03 reopened it | T012 now follows the contract and says the decision is settled. |
| I2 | MEDIUM — two wire shapes for unset | Settled in the contract: omitted on `GET /`, `null` with `source: default` on `/hub/settings`; deliberately-cleared stays distinguishable as `stored` with an empty value. WP03 and WP04 follow it. |
| I3 | MEDIUM — thesis anchored to the wrong test-matrix row | Re-anchored to the two address rows, which are the ones that would have caught the original misidentification. |
| C2 | MEDIUM — a test-matrix row with no requirement and no task | Recorded as deferred with the federation switch, in both `spec.md`'s Out of scope and `tasks.md`'s WP05 section. |
| I4 | MEDIUM — `plan.md` had not caught up with WP05's rescoping | Structure block lists `federation.py` and `test_hub_identity.py`; IC-06 and IC-07 surfaces corrected; Structure Decision no longer claims "no new modules". |
| A1 | LOW — `422` row did not resolve to a definite shape | Now "the same error envelope as `unknown_recipient`". |
| U1 | LOW — FR-006 split across two WPs, unexplained | Explained in `tasks.md`: `local` is a permitted name in WP02, and blocks enabling federation in WP05, where the consequence is. |

### Coverage Summary

| Requirement Key | Has Task? | Task IDs |
|-----------------|-----------|----------|
| FR-001 `hub-reports-name-title-description` | yes | T011 |
| FR-002 `name-validated-as-address-component` | yes | T007, T008, T010 |
| FR-003 `all-three-settable-and-persistent` | yes | T001, T002, T003 |
| FR-004 `environment-overrides-without-erasing` | yes | T004, T006 |
| FR-005 `governed-field-renders-disabled` | yes | T019, T021 |
| FR-006 `local-default-and-federation-gate` | yes | T010, T022, T023 |
| FR-007 `federation-tab-holds-fields` | yes | T017, T021 |
| FR-008 `editing-is-operator-gated` | yes | T013, T016 |
| FR-009 `title-description-free-text-may-be-empty` | yes | T011, T012 |
| FR-010 `prompt-introduces-the-hub` | yes | T024, T025 |
| NFR-001 `no-new-mount-no-config-file` | yes | T001 |
| NFR-002 `unconfigured-hub-behaves-as-today` | yes | T006, T011 |
| NFR-003 `identity-survives-the-address` | yes | **T027** |

### Charter Alignment Issues

None. The naming clause now matches the shipped product, the repository carries no
deployment-specific hostnames, all four quality gates are named in every work package, and
directive 4's outside-model review has an owner.

The binding ADRs remain honoured: ADR 0005 (the console reads and writes through the API and
is forbidden from recomputing precedence), ADR 0008 (the write is operator-gated and asserted
with a real device token), ADR 0003 (the mission is that ADR's argument one level up).

### Unmapped Tasks

- **T026** (documentation) serves charter directive 2 rather than a functional requirement.
- **T023** (prove the gate's test by removing the rule) and **T028** (outside review) are
  process rather than product. All three are correct as written.

### Metrics

- Total requirements: **13** (10 functional, 3 non-functional)
- Total tasks: **28** across 5 work packages (WP01 6, WP02 4, WP03 7, WP04 5, WP05 6)
- Coverage: **13 / 13 = 100%**
- Ambiguity count: **0**
- Duplication count: **0**
- Critical issues: **0**

### Verification performed

Remediation touched `src/` and `tests/`, so the charter's gates were run rather than assumed:
`uv run pytest` 640 passed / 11 skipped, `uv run ruff check` clean, `uv run ruff format
--check` clean, `uvx pyright src` 0 errors. Three lines exceeded the 88-column limit after
the hostname substitution and were rewrapped.

### Next Actions

Verdict is **ready**. `/spec-kitty.implement` — WP01 and WP02 have no dependencies and can
run concurrently.

One item deliberately left open, and it is not a finding: agent handles (`ludmila_coe`,
`pablo_fantomas`, `nicole_ruzickova`) appear ~110 times across source comments and docs as
provenance for bugs they found. The charter's enumerated list is "hostnames, IPs, secrets,
or organisation names", which handles are not — but its next clause says agent names are
config. Stripping them would remove attribution from a hundred places, so it is the
operator's call rather than a change to make silently.
