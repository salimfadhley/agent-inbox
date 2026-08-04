---
work_package_id: WP10
title: Actor visibility, set by the actor
dependencies:
- WP03
requirement_refs:
- C-003
- FR-023
- FR-024
- FR-028
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T055
- T056
- T057
- T058
- T059
phase: Phase 5 - Control
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/
create_intent:
- src/agent_inbox/federation/visibility.py
- tests/test_federation_visibility.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/visibility.py
- src/agent_inbox/wire.py
- tests/test_federation_visibility.py
role: implementer
tags: []
task_type: implement
---

> **SUPERSEDED — do not implement from this file.** (2026-08-04)
>
> This package's work is planned and decomposed in
> [`federated-identity-and-trust-01KYN49V`](../../federated-identity-and-trust-01KYN49V/tasks.md),
> which was carved out of this mission and describes the same requirements with
> parent ids carried for traceability.
>
> Building it from both would put the policy decision in two places — which this
> package's own objective warns is *"a disagreement, and a disagreement here is a
> disclosure"*. Twelve of this mission's fourteen packages shipped; this is one of
> the two that did not, and the child mission is where it lands.


# Work Package Prompt: WP10 – Actor visibility, set by the actor

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

`local` / `normal` / `discoverable`, as a profile field the actor edits itself
(clarified 2026-07-28, decision `01KYMQ8T23YB16YY7Y88EZPVVD`).

Lemmy lets users control their own discoverability, so C-008 selects it, and it avoids a
second place actor facts live. ADR 0008 is not in tension: that ADR governs *mail* carrying
authority, and an agent choosing its own reachability is not administration of the hub.

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

Implementation command (depends on: WP03):

```bash
spec-kitty agent action implement WP10 --agent <name>
```

## Subtasks & Detailed Guidance

### T055 — Visibility as a profile field

- **Files**: `src/agent_inbox/wire.py`, `src/agent_inbox/federation/visibility.py`
- It joins the existing profile surface — the same one `profile set` already writes. Do not
  add a parallel administrative setting.
- Default `normal` (FR-024). An actor that has never heard of federation gets the middle
  option, which is addressable but unlisted.

### T056 — Validate the enum, refuse the rest

- **Files**: `src/agent_inbox/federation/visibility.py`
- Profiles are otherwise free-form; this field is not. An unknown value must be refused at
  the write, naming the three permitted values.
- A profile that already holds a nonsense value must not stop the hub starting — validation
  applies to writes, the same rule hub-name validation follows.

### T057 — A ceiling, never a grant

- **Files**: `tests/test_federation_visibility.py`
- FR-053 is in WP03's policy function; this package proves it from the actor's side.
- Assert: a `discoverable` actor on a `disabled` hub is unreachable; a `discoverable` actor
  behind the blocklist is unreachable; setting `discoverable` grants nothing by itself.
- An implementation reading `discoverable` as permission inverts the policy, and the
  inversion is invisible until someone federates.

### T058 — Narrowing takes effect on in-flight mail

- **Files**: `tests/test_federation_visibility.py`
- This is the second half of the outside review's finding. An actor that sets itself `local`
  must not have queued mail delivered afterwards.
- The mechanism lives in WP08 (FR-050); assert it from here too, because this is where a
  reader looks for what visibility means.

### T059 — Humans and agents both

- **Files**: `tests/test_federation_visibility.py`
- FR-028. Groups are out of V1 unless the actor model makes them free — if they are free, say
  so; if not, record that they were considered and excluded.

## Definition of Done

- [ ] Visibility is a profile field with default `normal`.
- [ ] Unknown values refused at write; a bad stored value does not stop startup.
- [ ] Discoverable grants nothing under disabled or blocked, asserted.
- [ ] Narrowing to `local` stops queued delivery, asserted.
- [ ] Humans and agents both covered; groups explicitly decided.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A parallel administrative setting | Two places actor facts live, diverging | T055 uses the existing profile surface |
| `discoverable` read as permission | Inverts policy; invisible until federation is live | T057 asserts unreachability under disabled and blocked |
| Free-form validation | A typo silently means `local` | T056 refuses unknown values at the write |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
