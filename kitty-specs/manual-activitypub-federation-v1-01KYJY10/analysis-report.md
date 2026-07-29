---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: manual-activitypub-federation-v1-01KYJY10
mission_id: 01KYJY10WCA0RC9KWGXXCYX1CG
generated_at: '2026-07-28T19:25:31.546641+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/manual-activitypub-federation-v1-01KYJY10/spec.md
    sha256: c7274004ae424f4e7f918260c775d3958d9bc5e65607a2081cff942b4367d885
  plan.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/manual-activitypub-federation-v1-01KYJY10/plan.md
    sha256: 502e2ee89585dd8121912b932393a9aabbbae4215b227490ec5bd63b18b9b2d3
  tasks.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/manual-activitypub-federation-v1-01KYJY10/tasks.md
    sha256: 3c866e5080957a64284c1a7abce7ed903ba81076f05d17abe7415eb3790406a5
  charter:
    path: /Users/salimfadhley/workspace/agent-inbox/.kittify/charter/charter.md
    sha256: dc24f43bde1a5b81568f486f9084753c30daab2d302f1227dae097434e9e6882
verdict: blocked
issue_counts:
  medium: 4
  critical: 1
  high: 2
  low: 1
  info: 0
findings:
- id: S1
  severity: critical
  category: charter
  summary: 'The mission cannot be implemented: its foundation, a-hub-has-a-name-of-its-own-01KYMD90, is not merged, which charter directive 3 forbids building on.'
- id: A1
  severity: high
  category: missing-artifact
  summary: plan.md's Project Structure lists research.md, data-model.md and contracts/ as mission artefacts; none of the three exists.
- id: D1
  severity: high
  category: unresolved-decision
  summary: The async HTTP client dependency is unresolved, and WP07/WP08 cannot be implemented without it.
- id: N1
  severity: medium
  category: inconsistency
  summary: Renumbering FR-015a/017a/028a to FR-051/052/053 left the requirement table out of numeric order, with FR-050 appearing after FR-053.
- id: M1
  severity: medium
  category: coverage
  summary: Nine requirements are mapped to two or three work packages each with no recorded rationale, so the mappings read as errors.
- id: M2
  severity: medium
  category: coverage
  summary: WP01 is a test harness that ships no production code, yet claims FR-034 and FR-037 as its requirement refs.
- id: X1
  severity: medium
  category: dependency
  summary: "WP12 builds a console section on the assumption that issue #21's Settings re-org lands first, but nothing enforces that ordering."
- id: C1
  severity: low
  category: coverage
  summary: C-008 is mapped to WP03 alone despite being a standing constraint reproduced in all fourteen prompts.
---

## Specification Analysis Report

Mission `manual-activitypub-federation-v1-01KYJY10`, analysed on `feat/federation` against
`spec.md` (53 FR, 7 NFR, 8 C), `plan.md`, `tasks.md` (14 WPs, 80 subtasks),
`research/outside-review-2026-07-28.txt` and `.kittify/charter/charter.md`.

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| S1 | Charter | CRITICAL | plan.md Complexity Tracking; tasks.md sequencing gate | Charter directive 3 — *"before building layer N, ask whether layer N−1 is settled; if it is not, settling it **is** the work"* — is in conflict with this mission's readiness. Federation depends on the hub `name`, hub settings storage, the precedence rule and the `local` gate, all owned by `a-hub-has-a-name-of-its-own-01KYMD90`. That mission is analysis-`ready` but only **WP01 T001–T002** are implemented, and it is not merged. | This is declared and mitigated in the plan rather than hidden, and the mitigation — a hard sequencing gate repeated in `tasks.md` and in all fourteen prompts — is the right one. But it is still a blocker: **the answer to "is federation ready to implement" is no, and the reason is #15.** Finish #15, then #21, then start here. |
| A1 | Missing artifact | HIGH | plan.md "Documentation (this mission)" | The structure block lists `research.md`, `data-model.md` and `contracts/` as belonging to this mission. `research/` holds only the outside-review transcript; `data-model.md` and `contracts/` do not exist. The spec-kitty plan flow's Phase 0 and Phase 1 call for all three. | For a mission that is **entirely about wire shapes**, a missing `contracts/` is the most consequential of the three. The spec carries a WebFinger JRD, a descriptor and a `Create/Note` inline, but there is no single authority for the shapes fourteen packages must agree on. Generate `contracts/` at minimum; `data-model.md` for peers, queue entries, seen-ids and audit rows is close behind. |
| D1 | Unresolved decision | HIGH | plan.md Technical Context; tasks.md "decisions still owed" | Outbound federation needs an async HTTP client with per-peer concurrency, bounded timeouts and non-blocking retry. The project declares none and uses stdlib `urllib.request`. `httpx` is proposed, flagged for the operator, and unanswered. | WP07 and WP08 cannot be implemented without resolving this, and WP08 carries FR-050 — the mission's sharpest requirement. Get the answer before implementation, not during. The alternative (threads around `urllib`) is a design decision with consequences, not a fallback. |
| N1 | Inconsistency | MEDIUM | spec.md L227, L230, L241, L262 | `FR-015a`, `FR-017a` and `FR-028a` were renumbered to `FR-051`–`FR-053` because the requirement-mapping validator rejects suffixed ids. They kept their original table positions, so the table now runs …FR-051… FR-052… FR-053… FR-050, and a reader scanning for FR-050 finds it last. | Cosmetic but genuinely confusing in a 53-requirement table that fourteen prompts cite by number. Either move the three rows to the end or renumber the whole tail. Do it before implementation, while the citations are only in planning artefacts. |
| M1 | Coverage | MEDIUM | tasks.md requirement refs | Nine requirements are claimed by more than one package: FR-008 (WP03, WP08), FR-013 (WP06, WP11), FR-015 (WP06, WP13), FR-034 (WP01, WP07), FR-037 (WP01, WP02, WP09), FR-041 (WP11, WP12), FR-042 (WP02, WP13), NFR-002 (WP08, WP09), NFR-003/004 (WP09, WP14). Most are deliberate splits — FR-013's two preconditions live in different packages — but nothing records that. | One line per split in `tasks.md`, as was done for FR-006 in the hub-identity mission. Undocumented multi-mapping reads as a mapping error, and the next reviewer will raise it again. |
| M2 | Coverage | MEDIUM | tasks/WP01 frontmatter | WP01 builds the two-hubs-in-one-process test harness and **ships no production code**. It claims FR-034 and FR-037, which are implemented by WP07 and WP02/WP09 respectively. | Either give WP01 no requirement refs and note that it is enabling infrastructure, or add an explicit "harness" requirement. As written, a coverage query for FR-034 returns a package that does not implement it. |
| X1 | Dependency | MEDIUM | tasks/WP12; issue #21 | WP12's prompt says "build a section, not a tab", on the basis that [#21](https://github.com/salimfadhley/agent-inbox/issues/21) restructures the console into a Settings tab with Federation as a section. #21 is an open issue with no mission, and `dependencies: [WP06, WP08, WP11]` cannot express a cross-mission ordering. | Record the cross-mission dependency where the finaliser can see it, or accept that WP12 may need reparenting and say so in its Definition of Done. Right now the constraint exists only in prose. |
| C1 | Coverage | LOW | tasks.md; all fourteen prompts | C-008 ("when in doubt, do what Lemmy does") is mapped to WP03 alone, but it is reproduced as a standing constraint in the Context section of every prompt and will be exercised wherever a default is chosen. | Harmless, but the mapping under-describes it. Either map it broadly or note in `tasks.md` that it is a standing constraint rather than a package-owned one. |

### Coverage Summary

All **53** functional requirements are mapped; `unmapped_functional` is empty. All 7
non-functional requirements and all 8 constraints are mapped. Coverage is **68/68 = 100%**.

The findings above are about the *quality* of some mappings (M1, M2, C1), not about gaps.

| Requirement group | Mapped to | Notes |
|---|---|---|
| FR-001–FR-003 (tab, defaults, trust) | WP12, WP06 | |
| FR-004–FR-008, FR-012 (modes, blocklist, schemes) | WP03 | plus FR-008 in WP08 for cancellation |
| FR-009–FR-011, FR-015 (transport, warnings, URL change) | WP06, WP12, WP13 | |
| FR-013, FR-014, FR-051 (preconditions, profile, rename) | WP06, WP11 | see M1 |
| FR-016–FR-022, FR-029, FR-030, FR-048, FR-052 (discovery) | WP05 | the largest single-package group |
| FR-023–FR-028, FR-053 (visibility) | WP10, WP03 | ceiling enforced in policy, chosen in profile |
| FR-031–FR-038, FR-047, FR-050 (delivery) | WP07, WP08, WP09 | FR-050 is WP08's centre |
| FR-039 (signatures) | WP04 | |
| FR-040–FR-046, FR-049 (audit, storage, switch) | WP02, WP11, WP13 | |
| NFR-001–NFR-007 | WP08, WP09, WP11, WP12, WP14 | |
| C-001–C-008 | WP03, WP05, WP06, WP10, WP11, WP14 | see C1 |

### Charter Alignment Issues

- **S1 — directive 3.** The only charter conflict, and it is declared in Complexity Tracking
  with a stated mitigation rather than smoothed over. It nonetheless blocks implementation.

Everything else aligns, and two alignments are worth naming because they were designed for
rather than inherited:

- **Directive 7 (built for LLMs first)** is enforced *at the protocol boundary*: FR-033
  rejects `Follow`, `Like`, `Announce`, votes and boosts before delivery. Engagement
  mechanics do not arrive merely because ActivityPub carries them.
- **ADR 0008** holds under the hardest case this system has faced. Remote mail is the
  strongest form of arriving content, and NFR-004 with FR-040 require it be framed as
  untrusted data at the point of delivery rather than left to each agent's judgement.
- **Regression tests as requirements** is carried explicitly: WP09 T054 re-asserts mission
  0020's thread disclosure across the federation boundary.

### Unmapped Tasks

None. All 80 subtasks belong to exactly one work package, and every package carries
requirement refs. WP01's refs are questionable in kind rather than absent (M2).

### Metrics

- Total requirements: **68** (53 functional, 7 non-functional, 8 constraints)
- Total tasks: **80** across 14 work packages (5–7 subtasks each)
- Coverage: **68 / 68 = 100%**
- Prompt sizes: 190–222 lines, average ~202 — all within the 200–500 target
- Lanes computed: 14
- Ambiguity count: **0**
- Duplication count: **0** (9 deliberate multi-mappings — see M1)
- Critical issues: **1**

### Next Actions

Verdict is **blocked**, on one critical and two high findings. The critical one is not a
defect in the planning — it is the honest answer to whether this can be built yet.

Recommended order:

1. **S1** — implement and merge `a-hub-has-a-name-of-its-own-01KYMD90` (WP01 T003–T006 then
   WP02–WP05), then #21. Nothing here starts before that.
2. **D1** — settle the HTTP client with the operator. Blocks WP07 and WP08.
3. **A1** — generate `contracts/` for the wire shapes fourteen packages must agree on, and
   `data-model.md` for peers, queue entries, seen-ids and audit rows.
4. **N1, M1, M2, X1, C1** — planning-artefact corrections, safe to batch, cheapest now while
   the requirement numbers are cited only in planning documents.

The task breakdown itself is sound: 100% coverage, prompts in range, a clean dependency DAG,
and the mission's sharpest requirement (FR-050, from the outside review) isolated in WP08
with tests that must be proved by removing the code they guard.
