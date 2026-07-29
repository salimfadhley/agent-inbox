---
work_package_id: WP07
title: 'Outbound: resolution and queueing'
dependencies:
- WP03
- WP05
- WP06
requirement_refs:
- FR-031
- FR-032
- FR-034
- FR-047
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T037
- T038
- T039
- T040
- T041
- T042
phase: Phase 4 - Delivery
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/outbound.py
- tests/test_federation_outbound.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/outbound.py
- src/agent_inbox/addressing.py
- tests/test_federation_outbound.py
- tests/test_addressing.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP07 – Outbound: resolution and queueing

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

A local send that names a remote actor succeeds locally and queues delivery behind
itself. The sender never waits on a remote server (FR-034).

The addressing change is the delicate part. `addressing.py` says outright that the split
exists so *"federation later widens this one function rather than the whole engine"* — so
widen `local_name()`, and nothing else.

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

Implementation command (depends on: WP03, WP05, WP06):

```bash
spec-kitty agent action implement WP07 --agent <name>
```

## Subtasks & Detailed Guidance

### T037 — Widen `local_name()`, and only that

- **Files**: `src/agent_inbox/addressing.py`
- Today a non-local address raises `RemoteMailbox`. Now it may resolve to a remote target
  instead — but only when policy permits and federation is on.
- **`@local` still never egresses** (C-007). The module calls that a promise of non-egress
  "visible by inspection, with no configuration to get wrong"; keep it exactly that.
- Do not spread address knowledge into the messaging rules. That boundary is why this change
  is small.

### T038 — Resolve recipients to actor URIs and inboxes

- **Files**: `src/agent_inbox/federation/outbound.py`
- Use WP05's resolution. Cache within a send so one message to three actors on one peer does
  not fetch the descriptor three times.
- A recipient that cannot be resolved is a **failure of that recipient**, not of the message.
  Partial delivery is normal and must be visible (FR-038).

### T039 — Persist locally first, then queue

- **Files**: `src/agent_inbox/federation/outbound.py`
- FR-034. The local copy is the source of truth; the queue references it.
- If queueing fails, the local send must still have succeeded. Losing a local message because
  a remote server is unreachable would be the worst possible trade.

### T040 — `Create` wrapping `Note`, with `to`, `cc`, `inReplyTo`

- **Files**: `src/agent_inbox/federation/outbound.py`
- FR-031, FR-032. `summary` carries the subject, `content` the body.
- `bto`/`bcc` are already refused by `_refuse_blind_addressing` — do not quietly start
  honouring them at the federation boundary.

### T041 — One queue entry per target inbox

- **Files**: `src/agent_inbox/federation/outbound.py`
- Two recipients on one peer is one delivery, not two, and a shared inbox must not receive
  the same activity twice.
- Store no authorization decision on the row (WP02 T007, FR-050).

### T042 — Tests, including the one that must not regress

- **Files**: `tests/test_federation_outbound.py`, `tests/test_addressing.py`
- A send to a remote actor returns success without waiting; the queue holds one entry.
- `@local` addressing is refused at the boundary even with federation fully enabled and the
  peer allowed. **Delete the `@local` guard and watch this fail**; record it.
- A message to two actors on one peer produces one delivery.

## Definition of Done

- [ ] `local_name()` widened; nothing else learned about addresses.
- [ ] `@local` never egresses, proved by removing the guard.
- [ ] Local persistence precedes queueing.
- [ ] Create/Note with to, cc, inReplyTo; bto/bcc still refused.
- [ ] One delivery per target inbox.
- [ ] No authorization decision stored on the row.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| `@local` egressing once federation is on | Breaks a guarantee agents rely on by inspection | T042 removes the guard and asserts failure |
| Address knowledge spreading beyond `local_name()` | Undoes the seam the module was built around | T037 restricts the change |
| A local send failing because a peer is unreachable | Loses mail for a remote problem | T039 orders persistence first |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
