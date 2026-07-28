---
work_package_id: WP04
title: The second CI pass, against an enforcing hub
dependencies:
- WP02
- WP03
requirement_refs:
- FR-007
- FR-010
- NFR-003
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
agent: ''
history: []
authoritative_surface: .github/workflows/ci.yml
create_intent: []
execution_mode: code_change
owned_files:
- .github/workflows/ci.yml
role: implementer
tags: []
---

# WP04 — The second CI pass, against an enforcing hub

## Objective

Run the suite twice on every push: once against today's open compose stack, once against a
hub started with `AGENT_MAILBOX_AUTH_MODE=enforce`. The enforcing configuration is what
examplehub and every production hub run, and nothing tests it today.

## Subtasks

- **T011 — add the enforcing pass** to the `smoke` job in `.github/workflows/ci.yml`.
  Reuse the image already built in that job; no second build (NFR-003).

  Prefer an environment override on the existing `docker-compose.yml` over a second
  compose file. The compose file is itself part of what the smoke job validates, so
  keeping one topology definition keeps that validation honest — this is open question 2
  in `spec.md`, and the override is the recommendation, not a decision.

- **T012 — the anti-vacuity guard** (FR-010). The enforcing pass must fail if it completes
  without ever authenticating.

  This is the subtask that matters most in the WP. The plausible bad outcome is **not** a
  failing second pass — it is a *passing* one that never authenticated, which adds a green
  tick and no coverage, and which nobody would investigate because it is green. Assert
  positively that a credential was used and that an uncredentialed request to a protected
  route was refused.

- **T013 — prove the guard works by removing the credential.** Run the enforcing pass with
  the token deliberately withheld and confirm it fails. Do this before believing the pass,
  exactly as the v0.22.0 regression tests were verified — a test for this class of defect
  is itself prone to passing vacuously.

## Acceptance

- Both passes green on an ordinary push, and the job fails if either fails.
- With the credential withheld, the enforcing pass fails, and the failure says so.
- Job wall-clock does not grow by an image build.
- Teardown removes both stacks, including volumes, so a later run cannot inherit state
  from an earlier one — a hub with a leftover database is not a fresh first-run hub, and
  WP03 depends on first-run behaviour.

## Notes

Sequencing: depends on WP02 (the suite must be mode-aware before running it in two modes)
and WP03 (the enforcing pass needs a credential). WP01 is implied through both.

If the enforcing pass proves flaky, do not paper over it with retries before finding out
why. A flaky auth pass is itself a finding — it may be a real race in first-run enrolment,
which no other test would ever surface.
