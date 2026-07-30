# Pre-tasks review — spec and plan

**Not** spec-kitty's `analysis-report.md`. That artifact gates on `tasks.md`, which does not
exist yet: the sanctioned order is specify -> plan -> tasks -> analyze, and this mission has
reached plan. Written now because the findings are about the spec and plan, and are worth
having before work packages are cut rather than after.

Re-run `record-analysis` once tasks exist; nothing here should need changing, but the two
missing test rows below ought to be in the work packages when they are written.

---

## Specification Analysis Report

Mission `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`, spec + plan, 2026-07-30.

| ID | Category | Severity | Location | Summary | Recommendation |
|----|----------|----------|----------|---------|----------------|
| C1 | Coverage | MEDIUM | spec FR-008 | The event must be actionable "without a second round trip to decide" — no test asserts it and no plan step delivers it beyond the field list | Add a test that the event alone is sufficient to decide whether to fetch; it is otherwise satisfied by accident |
| C2 | Coverage | MEDIUM | spec FR-009 | "Nothing about the socket may change what mail is" — retention, read state and disclosure unaffected. Nothing asserts this | Add a row: a message that arrived while a client was connected expires, reads and discloses identically to one that did not |
| A1 | Ambiguity | MEDIUM | spec test matrix | "Event within a second" is the only number in the spec, and Phase 0 measures connection survival but not latency | Either measure it in Phase 0 alongside survival, or state it as an aspiration rather than a test criterion |
| I1 | Inconsistency | LOW | plan Technical Context vs spec presence section | Plan says connection state is in-memory and worth nothing across a restart; the presence section describes "recently connected" as durable history | Reconcile: *current* connections are ephemeral, *connection events* are history. They are different things sharing a word |
| U1 | Underspecification | LOW | spec FR-011, plan Phase 2 step 5 | The decision layer gates on "the recipient's own configuration" — where that lives and what it looks like is unstated | Not blocking: it is client-side and can be settled at implementation. Worth naming as a deliberate deferral |

**Coverage summary**

| Requirement | Has plan step / test? | Notes |
|---|---|---|
| FR-001 stream exists | yes | Phase 2 step 2 |
| FR-002 no body | yes | test row |
| FR-003 polling stays the floor | yes | test row |
| FR-004 one identity | yes | two test rows, treated as security |
| FR-005 dropped loses nothing | yes | step 4 reconnect |
| FR-006 harness-agnostic | yes | charter check |
| FR-007 bounded, observable | yes | step 2 |
| FR-008 actionable event | **no test** | C1 |
| FR-009 mail unchanged | **no test** | C2 |
| FR-010 decision layer | yes | step 5 |
| FR-011 no sender priority | yes | removal proof required |
| FR-012 default-safe | yes | test row |
| FR-013 rate-limited | yes | test row |
| FR-014 observable decisions | yes | test row |
| FR-015 docs change | yes | step 6 |

**Charter alignment**: no conflicts. ADR 0005, ADR 0008 and `live-session-push` rule 1 are
each named in the plan's charter check with the constraint they impose.

**Unmapped work**: none. Every plan step traces to a requirement.

**Metrics**
- Requirements: 15
- Covered by a test row or plan step: 13 (87%)
- Critical issues: 0
- Ambiguities: 1
- Duplications: 0

## Next actions

No critical or high findings; the mission is ready to implement. C1 and C2 are missing test
rows rather than missing design, and both are one line each. A1 should be settled during
Phase 0 measurement, which is already the first step.

The two strongest parts of this spec are the ones that arrived from the owner rather than
the analysis: NAT forcing the connection direction, and harness diversity forcing the
decision layer to be client-side. Both are recorded as constraints rather than preferences,
which is what stops a later reader "simplifying" them.
