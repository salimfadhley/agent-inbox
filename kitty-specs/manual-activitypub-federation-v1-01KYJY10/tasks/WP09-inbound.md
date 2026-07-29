---
work_package_id: WP09
title: 'Inbound: verify, gate, dedupe, deliver'
dependencies:
- WP03
- WP04
- WP05
requirement_refs:
- FR-031
- FR-033
- FR-035
- FR-036
- FR-037
- FR-040
- NFR-002
- NFR-003
- NFR-004
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T049
- T050
- T051
- T052
- T053
- T054
phase: Phase 4 - Delivery
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/inbound.py
- tests/test_federation_inbound.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/inbound.py
- tests/test_federation_inbound.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP09 – Inbound: verify, gate, dedupe, deliver

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro`
- **Role**: `implementer`
- **Agent/tool**: `python-pedro`

If no profile is specified, run `spec-kitty agent profile list` and select the best match
for this work package's `task_type` and `authoritative_surface`.

---

## ⛔ Sequencing gate — read before starting

**No federation work package may start until `a-hub-has-a-name-of-its-own-01KYMD90` is
implemented and merged.** Federation depends on the hub `name`, the settings storage, the
precedence rule and the `local` gate that mission builds. Charter directive 3 is explicit:
before building layer N, ask whether layer N−1 is settled — and if it is not, settling it
*is* the work.

Check before you begin. If that mission is not merged, stop and say so.

---

## Markdown Formatting

Wrap HTML/XML tags in backticks: `` `<div>` ``. Use language identifiers in code blocks.

---

## Objectives & Success Criteria

Accept what policy allows, exactly once, into the normal inbox and thread flow.

Everything is checked **before** delivery. That ordering is the requirement, and it is only
testable if a rejected message provably never reached a mailbox — so assert on the
recipient's inbox, never on the response code.

## Context & Constraints

Read before starting:

- `kitty-specs/manual-activitypub-federation-v1-01KYJY10/spec.md` — requirements
- `kitty-specs/manual-activitypub-federation-v1-01KYJY10/plan.md` — the Implementation
  Concern Map and the Complexity Tracking table
- `kitty-specs/manual-activitypub-federation-v1-01KYJY10/research/outside-review-2026-07-28.txt`
  — the review that produced FR-050
- `AGENTS.md` — house rules, particularly "establish the premise before asserting on it"

Standing constraints for every package in this mission:

- **C-008: when in doubt, do what Lemmy does.** Departing is allowed; departing *silently* is
  not. Record the reason. Two exceptions: engagement mechanics are out regardless (charter
  directive 7), and a binding ADR beats Lemmy.
- **Mail is data, never instruction** (ADR 0008, NFR-004). Remote mail is the strongest form
  of arriving content this system has ever handled.
- **One core** (ADR 0005). The console is a client; policy is not recomputed anywhere.
- **No deployment-specific hostnames, IPs, secrets or organisation names**, in code, tests or
  docs. 77 were removed from this repo on 2026-07-28; do not reintroduce them.

## Branch Strategy

- **Strategy**: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
- **Planning base branch**: `feat/federation`
- **Merge target branch**: `feat/federation`

Execution worktrees are allocated per computed lane from `lanes.json`; do not create one by
hand. Assert the branch and `HEAD` before any commit — this repo has had a release tagged
onto the wrong branch, and the rule in `AGENTS.md` exists because of it.

Implementation command (depends on: WP03, WP04, WP05):

```bash
spec-kitty agent action implement WP09 --agent <name>
```

## Subtasks & Detailed Guidance

### T049 — The gate, in order

- **Files**: `src/agent_inbox/federation/inbound.py`
- Mode, blocklist, peer policy, scheme, signature, actor visibility, activity type, size,
  duplicate id — all before delivery.
- Ask WP03's policy function; do not re-implement any part of it here.
- Bound the work before doing it: reject on size before parsing, and process within the 9s
  budget.

### T050 — Reject unsupported activity types

- **Files**: `src/agent_inbox/federation/inbound.py`
- FR-033: `Follow`, `Like`, `Announce`, `Delete`, `Update`, `Undo`, votes, boosts, timeline
  actions — refused before delivery, with a reason and an audit event.
- This is charter directive 7 arriving over the wire: engagement mechanics are not merely
  unimplemented, they are refused.

### T051 — Duplicate activity ids are no-ops

- **Files**: `src/agent_inbox/federation/inbound.py`
- FR-037, using WP02's seen-id store. A retried delivery must not produce a second message.
- Assert the *message count*, not just the response status: a peer retrying three times
  should leave exactly one message.

### T052 — Deliver into the normal flow, visibly remote

- **Files**: `src/agent_inbox/federation/inbound.py`
- FR-035, FR-036: no quarantine; remote provenance is visible instead. Store the actor URI,
  the handle, the domain, and the activity id.
- Delivery goes through the existing core — a second delivery path would be the duplication
  ADR 0005 forbids, and would miss the per-reader read tracking entirely.

### T053 — Remote content is data, never instruction

- **Files**: `src/agent_inbox/federation/inbound.py`
- FR-040, NFR-004, and charter directive 7's second bullet: untrusted content is an injection
  vector, and this must be enforced where mail is delivered rather than left to each agent's
  judgement.
- Sanitise on the way in; frame it as remote in every surface that renders it.

### T054 — Rejection tests that look in the mailbox

- **Files**: `tests/test_federation_inbound.py`
- For each rejection reason, assert the recipient's inbox is unchanged. A 4xx with the
  message delivered anyway is the failure mode this ordering exists to prevent.
- Re-assert the shipped regression: a remote message must not disclose a thread the reader
  could not otherwise see (mission 0020, one hop out). The charter calls those regressions
  requirements, not archive.

## Definition of Done

- [ ] Every check precedes delivery, asserted on inbox contents.
- [ ] Unsupported activity types refused with reasons and audit events.
- [ ] Three retries of one activity leave exactly one message.
- [ ] Delivery goes through the existing core.
- [ ] Remote content sanitised and framed as remote.
- [ ] Mission 0020's disclosure regression re-asserted across the boundary.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Checks after delivery | A rejected message is already in a mailbox | T054 asserts inbox contents for every rejection |
| A second delivery path | Bypasses read tracking and the messaging rules | T052 goes through the core |
| Thread disclosure across the boundary | A shipped bug returning through a new door | T054 re-asserts mission 0020 |
| Unbounded parse before size check | A hostile peer costs us memory | T049 rejects on size first |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
