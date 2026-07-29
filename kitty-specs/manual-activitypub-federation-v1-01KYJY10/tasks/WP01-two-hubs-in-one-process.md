---
work_package_id: WP01
title: 'Two hubs in one process: the federation harness'
dependencies: []
requirement_refs:
- NFR-008
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
phase: Phase 1 - Foundation
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/federation/
create_intent:
- tests/federation/__init__.py
- tests/federation/harness.py
- tests/federation/test_harness.py
execution_mode: code_change
owned_files:
- tests/federation/__init__.py
- tests/federation/harness.py
- tests/federation/test_harness.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP01 – Two hubs in one process: the federation harness

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

Federation is two hubs talking. Every delivery requirement in this mission is a
statement about what hub B ends up holding after hub A does something, and none of it can be
asserted without two hubs. Build that first.

The charter forbids external services in the suite and requires it to run in normal CI, so
this is **two Litestar apps in one process, with distinct stores, wired to each other by a
transport stub**. No sockets, no ports, no network.

This package ships no production code. It exists so that the twelve packages after it can
assert on a recipient's inbox instead of on a status code.

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

Implementation command (depends on: none):

```bash
spec-kitty agent action implement WP01 --agent <name>
```

## Subtasks & Detailed Guidance

### T001 — Two apps, two stores, one process

- **Files**: `tests/federation/harness.py`
- Build a fixture that returns two independently configured hubs, each with its own store,
  its own hub `name`, its own public URL, and its own signing key.
- They must be genuinely independent. A shared store would make every isolation assertion in
  this mission vacuous — and "a test that passes because it had nothing to look at" is this
  project's recurring defect.
- Give each hub a distinct name (`alpha`, `beta`) and assert at fixture-build time that the
  two stores are not the same object and the two names differ. Establish the premise.

### T002 — A transport that carries A's outbound to B's inbound

- **Files**: `tests/federation/harness.py`
- Outbound federation makes an HTTP request to a peer's inbox. In the harness that request
  must be routed to the other app's ASGI handler directly.
- Route by the peer's base URL, so that an unknown or blocked host **fails the way a real
  unreachable host would** rather than silently succeeding. A transport that delivers to
  whoever is listening would hide every policy failure this mission cares about.
- Record every attempt — target, status, and whether it was delivered — so tests can assert
  on what was *attempted*, not only on what arrived. FR-050's whole point is that an attempt
  can happen when it should not.

### T003 — Injectable failure: 503, timeout, and a stalled retry

- **Files**: `tests/federation/harness.py`
- The outside review's finding (FR-050) needs a peer that can **hold a delivery pending**
  and accept it later. That is not an edge case to bolt on afterwards; it is the mechanism
  by which the mission's sharpest requirement is tested.
- Provide: return `503`, time out, and "fail now, succeed on the Nth retry".
- Also provide an oversized response and a malformed body, for the bounds in NFR-002.

### T004 — Controllable time, so backoff is testable without sleeping

- **Files**: `tests/federation/harness.py`
- Retry backoff is `1.25^n` capped at 24h. A suite that waited would be unrunnable.
- Inject a clock rather than patching `time` globally. The retry logic should take its
  notion of now as a parameter, which is also better production design.
- Do **not** use `Date.now`-style ambient time in the harness; make the test say when it is.

### T005 — Prove the harness, by making it fail

- **Files**: `tests/federation/test_harness.py`
- A message sent from `alpha` to an actor on `beta` arrives in that actor's inbox — asserted
  on **beta's inbox contents**, not on a 202 from the transport.
- Then break it deliberately: point the peer at a host the transport does not know, and
  assert nothing arrives. A harness that delivers regardless of addressing would make every
  later test meaningless, and this is the assertion that says it does not.
- Assert the attempt log records the failed attempt. Silence and refusal must be
  distinguishable.

## Definition of Done

- [ ] Two hubs, two stores, asserted distinct.
- [ ] A message crosses and is asserted on the recipient's inbox.
- [ ] An unroutable peer delivers nothing, asserted.
- [ ] 503, timeout and stalled-retry are all injectable.
- [ ] Backoff is testable without sleeping.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A harness that always delivers | Every policy test downstream becomes vacuous | T005 breaks it on purpose and asserts the break |
| Shared state between the two hubs | Isolation assertions pass for the wrong reason | T001 asserts the stores differ |
| Wall-clock sleeps | An unrunnable suite, so retry logic goes untested | T004 injects the clock |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
