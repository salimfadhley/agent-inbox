---
work_package_id: WP02
title: Assertions keyed to the mode, and the honesty check
dependencies:
- WP01
requirement_refs:
- FR-002
- FR-003
- FR-005
- FR-006
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T004
- T005
- T006
- T007
agent: ''
history: []
authoritative_surface: tests/live/test_live_smoke.py
create_intent: []
execution_mode: code_change
owned_files:
- tests/live/test_live_smoke.py
role: implementer
tags: []
---

# WP02 — Assertions keyed to the mode, and the honesty check

## Objective

Turn the five false failures into true assertions, and add the one piece of genuinely new
coverage this mission buys.

## Subtasks

- **T004 — key the existing assertions to the mode** (FR-002). The five that fail against
  an enforcing hub:

  | Test | Open | Enforcing |
  |---|---|---|
  | `/observe/mailbox/admin` | 200 | 401 without a credential, 200 with |
  | `/observe/purge/status` | 200 | as above |
  | `join` | 201/409 | as above |
  | thread read | dict body | as above |
  | `test_the_console_serves_and_warns` | warning **present** | warning **absent** |

  The console one is the trap: it asserts `does not authenticate` appears in the HTML.
  That string is correctly absent on an authenticating hub, so the assertion must invert
  with the mode rather than be deleted.

- **T005 — the honesty check** (FR-003). A hub advertising `authenticated: true` while a
  protected route answers unauthenticated is a failure. This assertion only becomes
  possible once WP01 reads the advertisement, and it covers a defect class nothing else
  does.

  Cross-read `auth-mode-truthful-error-text-01KYJZ81` before writing it: that mission
  records the same hub contradicting itself *in prose*. This check covers behaviour, not
  prose, so it would not have caught that — do not assume it does.

- **T006 — credential handling** (FR-005). The credential comes from the environment,
  never a repo file. Against an enforcing hub with no credential, **skip with a stated
  reason**. "Cannot test this" and "this failed" are different facts and must not share a
  symbol.

- **T007 — report what did not run** (FR-006). A run where everything skipped must not
  look like a clean pass. Surface the skip count and reasons in the suite's own output,
  not only under `-rs`.

## Acceptance

- Against an enforcing hub with a credential: the whole suite passes.
- Against an open hub: the whole suite passes, unchanged in meaning from today.
- Against an enforcing hub with no credential: explicit skips with reasons; no failures;
  and the summary makes the reduced coverage visible.
- A hub that advertises `authenticated: true` but leaves a protected route open fails
  T005. Prove it by pointing the suite at a deliberately misconfigured hub rather than by
  reading the code.

## Notes

The temptation is to skip the awkward cases under enforcement. Resist it — a suite that
skips its way to green is the failure this mission exists to remove, and it would be
harder to notice afterwards than the current five red tests.
