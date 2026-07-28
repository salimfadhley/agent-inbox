---
work_package_id: WP03
title: Unattended operator bootstrap
dependencies:
- WP01
requirement_refs:
- FR-008
- FR-009
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T008
- T009
- T010
agent: ''
history: []
authoritative_surface: tests/live/conftest.py
create_intent: []
execution_mode: code_change
owned_files:
- tests/live/conftest.py
role: implementer
tags: []
---

# WP03 — Unattended operator bootstrap

## Objective

Obtain a device token inside CI with no stored secret, so the enforcing pass needs neither
a repository credential nor a configured CI secret. The hub is created fresh for the run
and destroyed with it.

**This is the highest-risk WP in the mission.** Read the risks before starting.

## The chain

All public surface; no product change is required.

| Step | Mechanism | Source |
|---|---|---|
| 1 | initial admin password from the container log | `auth/service.py:146` emits `initial admin password: …` |
| 2 | `GET /auth/enrol` → TOTP secret + recovery codes | `api.py:1145` |
| 3 | compute a code | `agent_mailbox.auth.totp` |
| 4 | `POST /auth/enrol` → completes first-run, yields a session | `api.py:1156` |
| 5 | `POST /auth/agents/{name}/tokens` → device token | `api.py:1197`, operator-guarded |

## Subtasks

- **T008 — implement the chain** as a fixture used only when the mode is `enforcing` and
  no credential was supplied by the environment. Records `origin=bootstrapped` on the
  credential (see `data-model.md`) so a later failure can say where the token came from.

- **T009 — name your own failures** (FR-009). Each of the five steps fails with a message
  identifying *that step*. Without this, a break anywhere in the chain presents as a
  baffling 401 in an unrelated live test, and the person debugging starts in the wrong
  place.

- **T010 — assert the bootstrap, do not merely use it.** The chain is the only live
  exercise of operator first-run that exists anywhere in this project, and that path runs
  exactly once per deployment, at the moment when getting it wrong is most expensive. Make
  it a test in its own right, not a silent precondition of other tests.

## Risks

**Step 1 is a log line, not a contract.** Reword the message in `auth/service.py` and CI
breaks somewhere that looks unrelated. This is open question 1 in `spec.md` and is **not
resolved** — the recommendation is to treat the line as a contract and assert it directly,
so that changing it fails a test that says so. The alternative, a first-run admin secret
read from the environment, is real product surface with security consequences on an
exposed hub and must not be added as a side effect of wanting a test. **Do not choose this
unilaterally; it is a human decision.**

**Do not weaken auth to make the test easier.** If the chain proves awkward, that is a
finding about operator onboarding worth reporting — not a reason to add a test-only
bypass. A bypass would also be a route into the hub that exists solely because of us.

## Acceptance

- Against a fresh enforcing hub, the fixture yields a working device token.
- Breaking any single step produces a failure naming that step.
- No credential appears in the repository, in CI configuration, or in logs the job
  publishes.
