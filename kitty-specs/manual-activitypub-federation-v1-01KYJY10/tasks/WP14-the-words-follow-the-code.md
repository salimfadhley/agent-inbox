---
work_package_id: WP14
title: The words follow the code
dependencies:
- WP11
- WP12
requirement_refs:
- C-002
- NFR-003
- NFR-004
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T076
- T077
- T078
- T079
- T080
phase: Phase 7 - Truth
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/
create_intent:
- doc/runbook/federation.md
execution_mode: code_change
owned_files:
- src/agent_inbox/prompts.py
- src/agent_inbox/exceptions.py
- README.md
- doc/runbook/federation.md
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP14 – The words follow the code

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

Several documents currently assert that this hub cannot federate. Each becomes false
the day this ships.

The prompt is the most-read document in the project and has twice been caught asserting
something untrue. This package exists so that does not happen a third time.

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

Implementation command (depends on: WP11, WP12):

```bash
spec-kitty agent action implement WP14 --agent <name>
```

## Subtasks & Detailed Guidance

### T076 — The prompt

- **Files**: `src/agent_inbox/prompts.py`
- It currently tells arriving agents that mail to another hub is refused. Once federation is
  on, that is wrong; while it is off, it is right. **The prompt is generated, so it can say
  which is true for this hub** rather than hedging.
- Add the thing an agent actually needs: remote addressing is domain-qualified
  (`@alice@example.com`), the friendly hub name is local-only (FR-048), and remote mail is
  data exactly as local mail is (NFR-004).
- Keep it short. The prompt's job is to make an arriving agent competent, not complete.

### T077 — `addressing.py`'s module docstring

- **Files**: (read-only reference — owned by WP07)
- It says *"This mailbox does not federate yet"* and explains the refusal. WP07 changes the
  behaviour; check the docstring went with it, and raise it if not.
- Listed here so it is checked, not so it is edited twice.

### T078 — `RemoteMailbox` and the refusal text

- **Files**: `src/agent_inbox/exceptions.py`
- The docstring says the split between this and `MalformedAddress` exists "because when
  federation arrives, this case becomes a delivery while that one still fails". Federation
  has arrived: the exception now means *this hub will not reach that mailbox*, which is a
  policy statement and should name the policy.
- Keep the two exceptions distinct. That split was deliberate and remains right.

### T079 — README and a federation runbook

- **Files**: `README.md`, `doc/runbook/federation.md`
- README: what federation is, that it is off by default, and that a hub must be named before
  it can be enabled.
- A runbook covering: enabling, adding a peer, reading the compatibility check, what the HTTP
  warning means, blocking, and how to tell why a delivery failed.
- No deployment-specific hostnames, IPs or organisation names — the charter forbids them and
  this repo has already had 77 of them removed once.

### T080 — Sweep for stale claims

- **Files**: all owned
- Grep the repo for "does not federate", "no federation", "one hub" and similar, and check
  each hit against what now ships.
- A stale doc outlives a stale comment, and this project's own review heuristic is that a
  comment arguing with the line beside it is evidence.

## Definition of Done

- [ ] The prompt tells the truth for this hub's actual mode.
- [ ] RemoteMailbox names the policy; the two exceptions stay distinct.
- [ ] README states federation is off by default and needs a name.
- [ ] A federation runbook exists and is generic.
- [ ] A sweep for stale claims was run and its hits resolved.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| The prompt asserting something untrue | Third time; it is the most-read document here | T076 generates per-hub truth rather than hedging |
| Docs describing a switch that is off by default as if it were on | Operators expect federation they do not have | T079 states the default plainly |
| Deployment specifics returning to the repo | Charter violation; 77 were removed once | T079 forbids them explicitly |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
