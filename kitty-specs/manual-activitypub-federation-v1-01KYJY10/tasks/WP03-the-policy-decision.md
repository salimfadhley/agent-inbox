---
work_package_id: WP03
title: The policy decision, in one place
dependencies:
- WP02
requirement_refs:
- C-007
- C-008
- FR-004
- FR-005
- FR-006
- FR-007
- FR-008
- FR-012
- FR-025
- FR-026
- FR-027
- FR-053
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T012
- T013
- T014
- T015
- T016
- T017
phase: Phase 2 - The decision
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/__init__.py
- src/agent_inbox/federation/policy.py
- tests/test_federation_policy.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/__init__.py
- src/agent_inbox/federation/policy.py
- tests/test_federation_policy.py
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


# Work Package Prompt: WP03 – The policy decision, in one place

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

One function that answers *may this exchange happen*, and every inbound and
outbound path asks it.

This is the highest-value target in the mission. If the decision is made in two places they
will disagree, and a disagreement here is a disclosure — the same class as the thread
disclosure that mission 0020 shipped and an outside reviewer found.

This package also converts `federation.py` into a package. The existing
`check_may_enable_federation()` moves in unchanged, and **its test must keep passing** —
that test was written to fail if the rule is removed, so a move that breaks it is a signal,
not an inconvenience.

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

Implementation command (depends on: WP02):

```bash
spec-kitty agent action implement WP03 --agent <name>
```

## Subtasks & Detailed Guidance

### T012 — Convert `federation.py` to a package, rule intact

- **Files**: `src/agent_inbox/federation/__init__.py`
- Move `check_may_enable_federation()` in with no behaviour change.
- Run the existing test that guards it **before and after**. It was shipped with a recorded
  removal check; if it fails now, the move changed something.
- Keep the docstring that records why the rule blocks *enabling* rather than *federating*.

### T013 — The decision function

- **Files**: `src/agent_inbox/federation/policy.py`
- One entry point. Inputs: direction (inbound/outbound), the peer or remote actor, the local
  actor, and the current configuration. Output: permitted, or a refusal that **names the rule
  it broke**.
- Return a structured refusal, not a bare `False`. Every caller needs to audit the reason
  (FR-042) and most need to show it. A boolean forces each call site to reconstruct why,
  which is how two call sites start disagreeing.

### T014 — Modes, and the blocklist that overrides them

- **Files**: `src/agent_inbox/federation/policy.py`
- `disabled` / `allowlist` / `open` per FR-004–FR-006. `allowlist` is the default enabled
  mode and an empty allowlist means effectively local-only.
- **The blocklist is not a mode; it overrides all of them** (FR-007). Put it inside this
  function, before the mode check. If it is a thing each call site remembers to check, one
  of them will not.

### T015 — Scheme policy

- **Files**: `src/agent_inbox/federation/policy.py`
- `https` always; `http` only when explicitly enabled (FR-010); everything else refused
  (FR-012) — `file`, `gopher`, `s3`, `ftp` and friends.
- Refuse by allowlist of schemes, never by blocklist of known-bad ones. A denylist of schemes
  is a guess about what exists.

### T016 — Actor visibility as a ceiling

- **Files**: `src/agent_inbox/federation/policy.py`
- `local` / `normal` / `discoverable` per the spec's table.
- **Visibility is a ceiling on exposure, never a grant** (FR-053). Server policy still wins:
  a `discoverable` actor on a `disabled` hub is not reachable. Encode that ordering here so
  no caller can invert it.
- `@local` never egresses (C-007), and that guarantee already exists in `addressing.py`. This
  function must not become a second place that decides it — defer, do not duplicate.

### T017 — The decision table, exhaustively

- **Files**: `tests/test_federation_policy.py`
- Enumerate the cross-product that matters: 3 modes x (peer allowed / not listed / blocked) x
  3 visibilities x (https / http-enabled / http-disabled / other scheme), both directions.
- Table-driven, with the expected outcome **and the expected refusal reason**. A test that
  only checks permitted/refused cannot catch two rules swapping.
- Then delete the blocklist override and re-run. Tests must fail. Record that they did.

## Definition of Done

- [ ] `federation` is a package; the `local` rule moved with its test still passing.
- [ ] One decision function; refusals name the rule broken.
- [ ] Blocklist overrides every mode, inside the function.
- [ ] Schemes are allowlisted.
- [ ] Visibility is a ceiling, with server policy ordered first.
- [ ] The decision table is exhaustive and was proved by removing the override.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Policy evaluated in more than one place | They diverge; the divergence is a disclosure | One entry point; T017's table is the contract |
| Blocklist checked per call site | One site forgets | T014 puts it inside, before the mode check |
| Visibility read as a grant | Inverts the policy — a `discoverable` actor becomes reachable on a disabled hub | T016 encodes the ordering; T017 tests it |
| Moving the `local` rule breaks its guard test | The gate silently stops being enforced | T012 runs it before and after |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
