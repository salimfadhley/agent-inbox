---
work_package_id: WP12
title: The Federation section of the console
dependencies:
- WP06
- WP08
- WP11
requirement_refs:
- FR-001
- FR-010
- FR-011
- FR-038
- FR-041
- NFR-005
- NFR-006
- NFR-007
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T065
- T066
- T067
- T068
- T069
- T070
- T083
- T084
phase: Phase 6 - Operator surface
agent: frontend-freddy
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: frontend-freddy
authoritative_surface: src/agent_inbox/console.py
create_intent:
- tests/test_console_federation.py
execution_mode: code_change
owned_files:
- src/agent_inbox/console.py
- tests/test_console_federation.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP12 – The Federation section of the console

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `frontend-freddy`
- **Role**: `implementer`
- **Agent/tool**: `frontend-freddy`

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

Where an operator manages federation: peers, mode, blocklist, delivery state, peer
health, and the warnings that must be acknowledged before anything risky is switched on.

**Build a section, not a tab.** [#21](https://github.com/salimfadhley/agent-inbox/issues/21)
re-organises the console into a Settings tab with Federation as one section, and the operator
has chosen to do that before this lands. Read that issue before starting.

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

Implementation command (depends on: WP06, WP08, WP11):

```bash
spec-kitty agent action implement WP12 --agent <name>
```

## Subtasks & Detailed Guidance

### T065 — The section, reading through the API

- **Files**: `src/agent_inbox/console.py`
- Peers with state and health, current mode, blocklist, recent delivery outcomes.
- The console is a client (ADR 0005). It renders what the API returns; it does not recompute
  policy, and it does not read the environment.

### T066 — Peer add, showing the check

- **Files**: `src/agent_inbox/console.py`
- Run WP06's flow and show `Ready` / `Warning` / `Failed` **with the exact reason**.
- An operator who cannot see why a peer failed will try things until something works, and one
  of the things they will try is enabling HTTP.

### T067 — The HTTP warning, unavoidable

- **Files**: `src/agent_inbox/console.py`
- FR-010 and the spec's warning text, substantially as written. Acknowledgement is required
  before activation (NFR-005) and is audited.
- HTTP peers stay **visibly marked insecure wherever they appear** — not only at the moment
  of adding.

### T068 — Open mode, and open-plus-HTTP

- **Files**: `src/agent_inbox/console.py`
- FR-011: open mode plus HTTP needs a *stronger* warning than HTTP alone, and the spec gives
  both texts.
- Two warnings that look identical teach an operator to click through both. Make the stronger
  one visibly different.

### T069 — Delivery state and peer health

- **Files**: `src/agent_inbox/console.py`
- FR-038 and NFR-006: pending / delivered / failed / suppressed / unsupported, each with its
  reason, plus recent rejections per peer.
- Governed fields render disabled and name the variable (FR-045), reusing the pattern from
  the hub-identity mission rather than inventing a second one.

### T070 — Console tests

- **Files**: `tests/test_console_federation.py`
- Warnings appear and cannot be bypassed; acknowledgement is recorded.
- The stronger warning is rendered for open-plus-HTTP, asserted on its distinguishing text.
- An HTTP peer is marked insecure in the peer list, not just on the add form.
- On an enforcing hub, a caller without an operator session cannot reach any of the writes.

### T083 — Blocklist management

- **Files**: `src/agent_inbox/console.py`, `tests/test_console_federation.py`
- FR-001 names the blocklist as one of the things the Federation surface manages. List
  entries, add one, remove one, and show that it overrides the current mode.
- Adding a blocklist entry must show what it will affect: which peers it matches now, and
  whether pending deliveries will be cancelled (FR-008).
- **Found missing by outside review, 2026-07-28.** Every other clause of FR-001 had a
  subtask; the blocklist had none, so the requirement was mapped but a third of it was
  undeliverable.

### T084 — Delivery state where an operator looks for it

- **Files**: `src/agent_inbox/console.py`, `tests/test_console_federation.py`
- FR-038 requires delivery state to be **visible in the UI** — the Federation surface *and*
  message details. WP08 owns the state; this package owns showing it.
- On a message with remote recipients, show per-recipient state with its reason. "Sent" for a
  message that reached two of three recipients is the kind of lie this project keeps finding.
- **Found missing by outside review, 2026-07-28.** FR-038 was mapped to WP08, which is the
  delivery worker and owns no UI at all.

## Definition of Done

- [ ] A Federation section, not a tab.
- [ ] Peers, mode, blocklist, delivery state and health all render from the API.
- [ ] Add flow shows Ready/Warning/Failed with reasons.
- [ ] HTTP and open-plus-HTTP warnings present, distinct, unavoidable and audited.
- [ ] HTTP peers marked insecure everywhere they appear.
- [ ] Operator gating asserted on an enforcing hub.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Building a tab that #21 immediately renames | Wasted work and a rename across tests and docs | Build a section; read #21 first |
| Warnings that can be clicked past | NFR-005 requires acknowledgement, and the risk is real | T067 and T070 assert unavoidability |
| Identical warning text for different risks | Teaches click-through | T068 makes the stronger one distinguishable |
| Console recomputing policy | Two implementations diverging | T065 renders API output only |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
