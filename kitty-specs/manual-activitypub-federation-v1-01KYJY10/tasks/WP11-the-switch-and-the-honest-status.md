---
work_package_id: WP11
title: The switch, and the honest status code
dependencies:
- WP03
- WP09
requirement_refs:
- C-005
- FR-002
- FR-013
- FR-041
- FR-046
- NFR-001
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T060
- T061
- T062
- T063
- T064
- T082
phase: Phase 5 - Control
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent:
- tests/test_federation_api.py
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_federation_api.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP11 – The switch, and the honest status code

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

Turn federation on, and make the inbox route mean what it says.

Two preconditions gate enabling: a stable public URL, and a hub `name` that is not `local`.
The second **already exists** as `check_may_enable_federation()`, shipped with a test that
fails if the rule is removed. Wire the switch to it. Do not reimplement the check — a second
copy is how the two start disagreeing.

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

Implementation command (depends on: WP03, WP09):

```bash
spec-kitty agent action implement WP11 --agent <name>
```

## Subtasks & Detailed Guidance

### T060 — Register the federation routes

- **Files**: `src/agent_inbox/api.py`
- Mount WP05's routes and WP09's inbound handler. Registration only — no logic here.
- The descriptor, WebFinger, actor documents and the directory are unauthenticated; the
  inbox is signature-verified. Two different postures on one router, so be explicit.

### T061 — The enable/disable route, operator-gated

- **Files**: `src/agent_inbox/api.py`
- Administrative, so it is gated like the other administrative routes (ADR 0008).
- Call `check_may_enable_federation()`. On refusal, say why in the words the rule already
  uses: a hub called "local" cannot be told apart from every other hub called "local".
- Refuse **enabling the mode**, not merely federating — a hub with federation on and no name
  must not be a reachable state (FR-013).

### T062 — `501` becomes `403` when the meaning changes

- **Files**: `src/agent_inbox/api.py`
- Today the inbox returns `501` with a body citing superseded mission numbers (0024, 0025).
- `501 Not Implemented` says *this software cannot*; once this mission ships that is false. A
  hub in `disabled` mode, or refusing a blocked or non-allowlisted peer, is saying *this hub
  will not* — which is `403`.
- Add every new code to `STATUS_BY_CODE` explicitly. This repo has shipped a code missing
  from that map, where `.get(code, 500)` turned a clean refusal into a `500` and the generic
  handler made it look handled.

### T063 — `federates` tells the truth

- **Files**: `src/agent_inbox/api.py`
- `GET /` already carries `"federates": false`. It must now reflect the actual mode.
- Decide whether it stays boolean while the descriptor carries the mode (FR-017), and write
  the reason down either way.

### T064 — Tests

- **Files**: `tests/test_federation_api.py`
- Enabling on a hub named `local` is refused, and the refusal says why.
- Renaming, then enabling, succeeds.
- Enabling with a non-operator credential is refused.
- The inbox returns `403` with a reason under `disabled`, and no longer mentions 0024/0025.
- Assert **status codes**, not exception types — the `500`-instead-of-`422` defect in this
  repo was invisible at the exception layer and obvious at the wire.

### T082 — A fresh hub federates with nobody, asserted

- **Files**: `src/agent_inbox/api.py`, `tests/test_federation_api.py`
- FR-002 and NFR-001: a newly started hub has no peers and no remote ingress or egress
  without operator action.
- Establish the default in code — mode `disabled`, empty peer list — and then **assert it on
  a hub that has had nothing done to it**: no peers listed, outbound refused, inbound
  refused, and the descriptor reporting federation off.
- **Found missing by outside review, 2026-07-28.** FR-002 was mapped to the peer add flow,
  which is where peers *arrive*; nothing established or tested what is true before anyone
  adds one. The default is the single most load-bearing behaviour in the mission, because it
  is what every unconfigured hub does forever.

## Definition of Done

- [ ] Federation routes registered, with their two auth postures explicit.
- [ ] Enable is operator-gated and calls the existing rule.
- [ ] A hub named `local` cannot enable, with the reason given.
- [ ] Inbox returns 403 with a reason; no superseded mission numbers remain.
- [ ] Every new code is in STATUS_BY_CODE, asserted at the wire.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Reimplementing the `local` check | Two rules that will disagree | T061 calls the shipped function |
| A new code missing from `STATUS_BY_CODE` | Becomes a 500; the generic handler hides it | T062 adds explicitly; T064 asserts codes |
| Enabling permitted, federating blocked | Leaves a half-configured hub reachable, which FR-013 forbids | T061 gates the mode |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
