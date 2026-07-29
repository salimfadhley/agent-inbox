---
work_package_id: WP02
title: 'Federation storage: peers, blocklist, queue, seen ids, audit'
dependencies: []
requirement_refs:
- FR-037
- FR-042
- FR-043
- FR-044
- FR-045
- FR-049
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
- T010
- T011
phase: Phase 1 - Foundation
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/sqlite_store.py
- src/agent_inbox/store.py
- tests/test_store_contract.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP02 – Federation storage: peers, blocklist, queue, seen ids, audit

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

Somewhere to keep what federation knows: peers, blocklist entries, the outbound
delivery queue, the ids of inbound activities already seen, and the audit trail.

All of it lives in the SQLite file the mail already lives in (NFR-001, and the precedent set
by `a-hub-has-a-name-of-its-own`). No new mount. Additive only — this runs against a
database holding live mail.

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
spec-kitty agent action implement WP02 --agent <name>
```

## Subtasks & Detailed Guidance

### T006 — Peers and blocklist

- **Files**: `src/agent_inbox/sqlite_store.py`, `src/agent_inbox/store.py`
- Peers: base URL (normalised), display fields read from the descriptor, enabled state, key
  fingerprint, first-seen, health/last-error.
- Blocklist: normalised domain or base URL. Matching must be deterministic and resistant to
  case, trailing slash and default-port confusion — the spec says so explicitly, and a
  blocklist with a bypass is worse than none because it is believed.
- Store the normalised form **and** what the operator typed. The operator needs to recognise
  their own entry; the matcher needs the canonical one.

### T007 — The outbound delivery queue

- **Files**: both stores
- One row per (activity, target inbox): state (pending / delivered / failed / suppressed /
  unsupported per FR-038), attempt count, next-attempt time, last error.
- It must survive a restart. A queue held in memory loses mail on deploy, and this hub is
  restarted routinely.
- **Do not** store the authorization decision alongside the row. FR-050 requires it be
  re-derived at send time; a persisted `allowed=true` is precisely the stale-authorization
  bug the outside review found.

### T008 — Seen inbound activity ids, with expiry

- **Files**: both stores
- FR-037: duplicate inbound activity ids are no-ops. That needs a record of what has been
  seen.
- **It must expire, and it must outlive any sender's retry window.** Too short and
  duplicates return when a peer retries late; never, and the table grows without bound. The
  spec's retry cap is 24h, so a floor well above that is the safe direction — pick it
  deliberately and write the reasoning next to the constant.

### T009 — Audit entries

- **Files**: both stores
- Fields per FR-042: timestamp, acting human for admin actions, action type, target, before
  and after where safe, warning-acknowledgement id, and the reason for automated decisions.
- Append-only. An audit log that can be edited answers no question worth asking.
- "Before and after **where safe**" is doing real work in that sentence: never record a
  token, a private key, or message content.

### T010 — Contract tests across both stores

- **Files**: `tests/test_store_contract.py`
- Every new surface goes through the existing parametrised suite so the in-memory and SQLite
  implementations are proved to agree, rather than assumed to.
- Include: blocklist matching against the confusable forms (case, trailing slash, default
  port); queue state transitions; seen-id expiry at the boundary.

### T011 — An existing database survives

- **Files**: `tests/test_store_contract.py`
- Open a store, write mail, close, reopen with the federation tables, and assert the mail is
  still readable.
- Establish the premise first: assert the mail was there before the upgrade. A test that
  writes nothing and finds nothing missing has looked at nothing.

## Definition of Done

- [ ] Peers, blocklist, queue, seen-ids and audit exist on both stores.
- [ ] Blocklist matching is deterministic across case, slash and port forms.
- [ ] The queue survives a restart.
- [ ] Seen-ids expire, above the retry cap.
- [ ] Audit is append-only and carries no secrets.
- [ ] Existing mail survives, asserted with its premise established.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A blocklist that can be bypassed by a trailing slash | It is believed, so the bypass is silent | T006 and T010 test the confusable forms |
| Persisting the authorization decision | Recreates the FR-050 hole in the storage layer | T007 forbids it explicitly |
| Seen-ids growing without bound, or expiring too soon | Disk exhaustion, or duplicate delivery | T008 sets the floor above the retry cap, with reasoning |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
