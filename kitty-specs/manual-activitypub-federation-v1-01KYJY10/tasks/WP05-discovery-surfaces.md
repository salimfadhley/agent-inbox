---
work_package_id: WP05
title: 'Discovery: descriptor, WebFinger, actor documents'
dependencies:
- WP03
- WP04
requirement_refs:
- C-001
- C-006
- FR-016
- FR-017
- FR-018
- FR-019
- FR-020
- FR-021
- FR-022
- FR-025
- FR-029
- FR-030
- FR-048
- FR-052
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T024
- T025
- T026
- T027
- T028
- T029
- T030
phase: Phase 3 - Surfaces
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/routes.py
- src/agent_inbox/federation/webfinger.py
- tests/test_federation_discovery.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/routes.py
- src/agent_inbox/federation/webfinger.py
- tests/test_federation_discovery.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP05 – Discovery: descriptor, WebFinger, actor documents

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

What a peer can read about us: the server descriptor, WebFinger resolution, actor
documents, and the discoverable-actor directory.

**These are unauthenticated by decision** (`01KYMQC8Z4CKN86Y3R79T06BCB`). That makes FR-030's
exclusion list a security boundary rather than a tidiness rule, and it makes every field
added here a disclosure decision.

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

Implementation command (depends on: WP03, WP04):

```bash
spec-kitty agent action implement WP05 --agent <name>
```

## Subtasks & Detailed Guidance

### T024 — The server descriptor at `/.well-known/agent-inbox`

- **Files**: `src/agent_inbox/federation/routes.py`
- Software, version, base URL, `title`, `description`, mode, capabilities, schemes, public
  key metadata. Unauthenticated (FR-017, FR-052).
- **The hub `name` must not appear** (FR-048). That is what makes renaming free, and it is
  the kind of field someone adds helpfully. Assert its absence.

### T025 — WebFinger for local actors

- **Files**: `src/agent_inbox/federation/webfinger.py`, `routes.py`
- `acct:alice@example.com` resolves to a JRD with a `self` link to the actor document
  (FR-018, FR-019).
- **A `local` actor must not resolve at all** (FR-025). Not "resolves with a flag" — absent.
  A WebFinger hit is itself disclosure that the actor exists.

### T026 — Actor documents

- **Files**: `src/agent_inbox/federation/routes.py`
- Inbox URL, public key metadata, display fields. Nothing about read state, mailbox
  statistics, tokens, login state or history (FR-030).
- Remote identity is stored as the actor URI, never the typed handle (FR-021) — so what we
  *emit* must be a stable URI too.

### T027 — The federated directory

- **Files**: `src/agent_inbox/federation/routes.py`
- Only `discoverable` actors, minimal profile data, paged at 50 (FR-029).
- `normal` actors are addressable but **not listed**. That distinction is the entire point of
  three visibility levels; a directory that leaks `normal` actors collapses it to two.

### T028 — Outbound resolution of `@alice@example.com`

- **Files**: `src/agent_inbox/federation/webfinger.py`
- Resolve a typed handle to an actor URI and inbox URL, bounded by the fetch budget (100) and
  the page size (50).
- Ask policy before fetching, not after: a blocked domain should cost no requests.

### T029 — Disclosure tests

- **Files**: `tests/test_federation_discovery.py`
- For each surface, assert the **absence** of every FR-030 exclusion — not merely the
  presence of the intended fields. Absence is the security property.
- Assert the hub `name` appears on none of them (FR-048).
- Assert a `local` actor is invisible to WebFinger, the directory, and actor-document
  lookup.

### T030 — Local and remote may share a username

- **Files**: `tests/test_federation_discovery.py`
- FR-022: a local `alice` and a remote `alice@example.com` coexist, and remote actors are
  always displayed with their domain.
- Assert the two never collapse into one — this is ADR 0003's collision argument arriving
  from outside.

## Definition of Done

- [ ] Descriptor unauthenticated, complete, and carrying no hub `name`.
- [ ] WebFinger resolves normal and discoverable actors; `local` actors do not resolve at all.
- [ ] Actor documents carry no FR-030 excluded field.
- [ ] Directory lists only discoverable actors, paged.
- [ ] Handle resolution is policy-gated before any fetch.
- [ ] Absence assertions exist for every exclusion.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A field added to the descriptor without a disclosure decision | It is unauthenticated; anyone reads it | T029 asserts absences, not presences |
| `local` actors resolving through WebFinger | Existence disclosure — mission 0020's class, one hop out | T025 and T029 |
| The hub name leaking onto a federated surface | Breaks FR-051's free rename | T024 and T029 assert its absence |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
