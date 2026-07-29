---
work_package_id: WP08
title: Delivery, retry, and send-time re-authorization
dependencies:
- WP07
requirement_refs:
- FR-008
- FR-050
- NFR-002
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T043
- T044
- T045
- T046
- T047
- T048
phase: Phase 4 - Delivery
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/delivery.py
- tests/test_federation_delivery.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/delivery.py
- tests/test_federation_delivery.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP08 – Delivery, retry, and send-time re-authorization

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

Drain the queue: sign, send, retry with backoff, and report state.

**This package carries the outside review's finding, and it is the sharpest requirement in
the mission.** FR-050: authorization is re-derived at send time from current policy, never
carried from queue time. Read the Delivery Semantics section of the spec before starting —
it gives two concrete sequences by which a hub egresses mail it has forbidden itself to
send.

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

Implementation command (depends on: WP07):

```bash
spec-kitty agent action implement WP08 --agent <name>
```

## Subtasks & Detailed Guidance

### T043 — Re-derive the whole decision at send time

- **Files**: `src/agent_inbox/federation/delivery.py`
- Before every attempt — including every retry — ask WP03's policy function again, with
  current configuration. Mode, blocklist, peer state, scheme, **and the sending actor's
  current visibility**.
- Not a re-check of the peer. The *whole* decision. The review found that mode and visibility
  are not properties of the target, so a queue keyed by peer never notices them change; a
  per-property cancellation path left two of three cases uncovered on paper.
- A delivery refused at send time is marked suppressed with its reason, not silently
  dropped.

### T044 — Backoff, bounded

- **Files**: `src/agent_inbox/federation/delivery.py`
- Immediate first retry, exponential `1.25^n`, capped at 24h.
- Take the clock as a parameter (WP01 T004). Ambient time here is untestable and this is the
  code where timing is the requirement.

### T045 — One concurrent send per peer

- **Files**: `src/agent_inbox/federation/delivery.py`
- The spec's default, from Lemmy. A slow peer must not stall other peers, and must not be
  hammered concurrently.
- This is the constraint the new HTTP client exists for; do not hand-roll a limiter if the
  client provides one.

### T046 — Delivery state, visible

- **Files**: `src/agent_inbox/federation/delivery.py`
- pending / delivered / failed / suppressed-by-blocklist / unsupported (FR-038), each with a
  reason.
- "Failed" without a reason is what makes an operator guess.

### T047 — Blocking cancels what is pending

- **Files**: `src/agent_inbox/federation/delivery.py`
- FR-008: blocking a peer cancels or permanently fails pending deliveries to it. The reviewer
  noted this case is already specified — implement it, and let T043 be the general net
  beneath it.

### T048 — The stale-authorization tests

- **Files**: `tests/test_federation_delivery.py`
- **The mode sequence**: send while allowed; peer 503s; set mode `disabled`; let the retry
  fire; assert **nothing was attempted** — on the harness's attempt log, not merely on the
  absence of an inbox entry. An attempt that was made and refused by the peer is still a
  policy failure.
- **The visibility sequence**: actor `normal` sends; retry stalls; actor becomes `local`;
  retry fires; assert no attempt.
- **The blocklist sequence**: as FR-008.
- Then remove the send-time re-check and re-run. All three must fail. Record that they did —
  this requirement exists because a reviewer found it, and a test that does not notice its
  removal would waste that.

## Definition of Done

- [ ] Every attempt re-derives the full decision from current policy.
- [ ] Mode-change, visibility-change and blocklist sequences each attempt nothing, asserted on the attempt log.
- [ ] Removing the re-check fails all three; recorded.
- [ ] Backoff is bounded and clock-injected.
- [ ] One concurrent send per peer.
- [ ] Every delivery state carries a reason.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Authorization carried from queue time | The mission's known hole; egress after federation is disabled | T043 re-derives everything; T048 proves it by removal |
| Asserting on the inbox instead of the attempt | A refused attempt still leaked that we tried | T048 asserts on the attempt log |
| Ambient time in backoff | Untestable, so untested | T044 injects the clock |
| Per-property cancellation paths | Exactly what left two of three cases uncovered | T043 forbids it |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
