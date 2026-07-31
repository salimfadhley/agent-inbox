---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: retry-delivery-to-a-sleeping-peer-01KYWFWB
mission_id: 01KYWFWBGS0KDHXVG10TMZYG8W
generated_at: '2026-07-31T17:52:04.460641+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/retry-delivery-to-a-sleeping-peer-01KYWFWB/spec.md
    sha256: a649a2665f288633a31bb7bc21405a68d49b86f4a7c02224379c6b71540cde0e
  plan.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/retry-delivery-to-a-sleeping-peer-01KYWFWB/plan.md
    sha256: de86c7658a516c75971a2d31684becc1ac7b6feaab679861e502c8436f0ca73b
  tasks.md:
    path: /Users/salimfadhley/workspace/agent-inbox/kitty-specs/retry-delivery-to-a-sleeping-peer-01KYWFWB/tasks.md
    sha256: 80b5bce5be1909dda5daeaf08dc4df4ad7c231d29b56346b8bc81d20b660299a
  charter:
    path: /Users/salimfadhley/workspace/agent-inbox/.kittify/charter/charter.md
    sha256: dc24f43bde1a5b81568f486f9084753c30daab2d302f1227dae097434e9e6882
verdict: ready
issue_counts:
  high: 0
  critical: 0
  medium: 0
  low: 0
  info: 0
findings: []
---

## Round 3 — the charter pass that rounds 1 and 2 skipped

**Rounds 1 and 2 asserted "Charter alignment: no violations" without reading the charter.**
That claim rested on recollection of the ADRs, not on `.kittify/charter/charter.md`. Reading
it produced two findings the earlier passes could not have found, both now fixed.

| ID | Severity | Finding | Resolution |
|----|----------|---------|------------|
| C1 | **critical** | **Directive 4** — "have an outside model review every mission before it closes", a standing instruction — appeared nowhere in this mission. Charter conflicts are CRITICAL by definition. | **T017** added to WP03, with the charter's prescribed narrow question ("can a message queued for retry be delivered to a peer that is no longer trusted?"), its hard-lid invocation, and its "treat findings as leads" rule |
| C2 | high | All three WP prompts named **`black`** as a quality gate. The charter names four: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`. Black is not installed, so a WP following the prompt would have "passed" a gate that never ran. | All three corrected, with a note that piping a gate to `tail` yields the pipe's exit status rather than the tool's — the mistake that produced a meaningless `black=0` during WP01 |

C1 is the more serious. Directive 4 exists because "our own tests pass because they were
written by the mind that wrote the code", and this mission is unusually exposed to that:
**T009 can pass for the wrong reason**, and whoever wrote it is the least likely to notice.

C2 is the plan writing down a gate that does not exist, which then produced a green signal
over a check that never ran — the same shape of failure as the deploy work earlier the same
day.

The carrier lists no findings because none remain open. Rounds 1 and 2 follow.

---

# Round 2 — findings A1–A6 (historical record)

## Round 2 — all six findings resolved

The first pass returned **blocked** on two HIGH findings. All six have since been applied
to `spec.md`, `plan.md`, `tasks.md` and the WP prompts (commit on this branch). The carrier
above lists no findings because none remain **open** — the record of what was found is kept
below, because the reasoning is worth more than the verdict.

| ID | Was | Resolution |
|----|-----|------------|
| A1 | HIGH — schedule overshot NFR-001 by 50% and rounded it away in prose | Tail shortened to `2s, 8s, 30s, 60s, 90s` (3m10s). The ceiling was kept and the design made to fit it, rather than the reverse |
| A2 | HIGH — FR-008's disclosure half had no subtask | **T016** added to WP01: a queued receipt carries the disclosure in its detail |
| A3 | MEDIUM — NFR-004 read per-peer, design was per-message | Decided 2026-07-31: per-message. NFR-004 reworded, and the cost (ten waiting messages → ten concurrent attempts) named in both plan and WP02 |
| A4 | MEDIUM — "one attempt" hid a 15s cost | NFR-002 now states it, and cross-references issue #34 |
| A5 | MEDIUM — T014 named no audit-log interface | T014 now requires confirming the call shape, and states that a logging failure must not fail the retry |
| A6 | LOW — mission could complete with its open question open | WP03's done-criteria accept a filed issue as an answer |

**A1 and A2 were both self-inflicted by the plan**, which is the point of running analysis
against your own design rather than treating it as a formality.

---

# Round 1 — original findings (historical record)

## Specification Analysis Report

Mission: `retry-delivery-to-a-sleeping-peer-01KYWFWB` — Federation Step 7.

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| A1 | Inconsistency | HIGH | spec.md NFR-001; plan.md "RetryingDelivery" | NFR-001 says give up after **≈5 minutes** across ~6 attempts. The plan's schedule is `2s, 8s, 30s, 2m, 5m` after an inline attempt — **≈7m40s**, roughly 50% over — and reconciles this in prose as "which NFR-001 rounds to about five minutes". An NFR exists to be measurable; a threshold the design openly exceeds is not one. | Pick one and make them agree. Either restate NFR-001 as ≈8 minutes, or shorten the tail (`2s, 8s, 30s, 60s, 90s` ≈ 3m10s). Prefer shortening: the bound was chosen to stay honest about an in-memory queue, and a longer window makes the C-001 promise weaker, not stronger. |
| A2 | Coverage | HIGH | spec.md FR-008; tasks.md WP03 | FR-008 requires two distinct things: (a) a `queued` receipt **says** the queue is not durable, and (b) a hub shutting down fails what it holds. Only (b) has a subtask (T012). Nothing in T011–T015 makes a queued receipt disclose volatility, and WP01 — which owns `Receipt` — does not mention it either. | Add a subtask, most naturally in WP01 alongside T001, populating the queued receipt's `detail` with the disclosure. FR-008 is the entire justification for accepting C-001; half-implementing it removes the basis for the in-memory choice. |
| A3 | Ambiguity | MEDIUM | spec.md NFR-004; plan.md "RetryingDelivery" | NFR-004 reads "a queued message is in flight **to a given peer** at most once at a time". "To a given peer" suggests a per-peer constraint, but one asyncio task per queued *delivery* only bounds concurrency per message — ten messages to one sleeping peer would produce ten simultaneous attempts. Given the NFR's stated purpose ("must not amplify load against a peer that is already struggling"), the per-message reading defeats it. | Decide which is meant. If per-peer, the design needs a per-peer lock or a single worker per peer, which is more machinery than the plan currently allows for — and would also change the NFR-003 argument. If per-message, reword the NFR to say so plainly. |
| A4 | Underspecification | MEDIUM | spec.md NFR-002; `outbound.py:167` | NFR-002 bounds the caller to "the time of one attempt". That attempt uses `urlopen(..., timeout=15)`, so a send to a sleeping peer blocks the caller for up to 15 seconds. For an agent, 15 seconds inside one tool call is a significant cost, and the spec never states it. | State the actual figure in NFR-002 rather than leaving "one attempt" to be discovered. Consider a shorter connect timeout on the inline attempt specifically, since its whole purpose is to fail fast into the queue. Overlaps issue #34. |
| A5 | Underspecification | MEDIUM | tasks.md T014; `policy.py:222`, `house.py:92` | T014 says to write outcomes to "the existing audit log". The facility exists, but as a **policy** evaluated on the send path — not obviously something a detached retry task can call minutes later, possibly after the request context is gone. The plan does not name the interface. | Confirm the call shape before implementation. `house.py:92` already notes the hazard of "a broken audit logger failing a message that was already sent" — the same reasoning applies here and suggests a logging failure must not fail the retry. |
| A6 | Process | LOW | spec.md open question; tasks.md T015 | T015 is instructed to raise an issue rather than fix a defect if our inbox does not de-duplicate. Correct scoping, but it means the mission can be marked complete with its own open question unresolved. | Acceptable. Make it explicit in the WP03 Definition of Done that "answered, either way" includes "answered by a filed issue". |

## Coverage summary

| Requirement | Has task? | Task IDs | Notes |
|---|---|---|---|
| FR-001 | Yes | T006, T007 | |
| FR-002 | Yes | T009 | Removal proof required |
| FR-003 | Yes | T001, T003 | |
| FR-004 | Yes | T005, T008 | Removal proof required |
| FR-005 | Yes | T009 | Shares the FR-002 proof |
| FR-006 | Yes | T007 | |
| FR-007 | Yes | T013 | Removal proof required |
| FR-008 | **Partial** | T012 | **A2** — disclosure half uncovered |
| FR-009 | Yes | T011 | |
| NFR-001 | Yes | T007, T010 | **A1** — threshold disagrees with design |
| NFR-002 | Yes | T006 | **A4** — real cost understated |
| NFR-003 | Yes | T007 | |
| NFR-004 | Yes | T007, T010 | **A3** — ambiguous |

**Unmapped tasks**: none. Every subtask traces to a requirement or to an explicitly
recorded open question.

## Charter alignment

No violations. ADR 0005 is actively served: the queue sits below `House`, so console, CLI
and MCP inherit it from one place, and WP03 explicitly refuses to build a second
notification path. ADR 0008 is untouched — nothing in a message influences whether it is
retried.

Worth noting positively: **C-003 turns the parent spec's outbound-authorization finding
into a structural property** rather than a remembered rule, which is the strongest thing in
this plan.

## Metrics

- Requirements: 13 (9 functional, 4 non-functional) + 4 constraints
- Tasks: 15 across 3 work packages
- Coverage: 12 of 13 fully, 1 partial → **96%**
- Ambiguity findings: 1
- Duplication findings: 0
- Critical issues: 0

## Next actions

No CRITICAL issues, so nothing blocks work absolutely — but **A1 and A2 should be settled
before implementation**, and both are small:

- **A1** is a one-line decision about the backoff tail.
- **A2** is one subtask added to WP01.

A3 is the only finding that could change the design rather than the documents, and it is
worth a decision now rather than discovering it in review.

Suggested: amend `spec.md` (NFR-001, NFR-002, NFR-004 wording), add one subtask to
`tasks.md`/WP01, then proceed to `/spec-kitty.implement`.
