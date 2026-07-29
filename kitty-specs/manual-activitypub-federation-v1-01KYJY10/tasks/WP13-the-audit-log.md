---
work_package_id: WP13
title: 'The audit log: who opened the door'
dependencies:
- WP02
- WP08
- WP09
requirement_refs:
- FR-015
- FR-042
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T071
- T072
- T073
- T074
- T075
phase: Phase 6 - Operator surface
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/audit.py
- tests/test_federation_audit.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/audit.py
- tests/test_federation_audit.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP13 – The audit log: who opened the door

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

Enough record to answer two questions: *who opened the door*, and *why was this
message accepted or rejected*.

The spec lists what every entry carries. The interesting design problem is not the schema —
it is making sure the events are emitted from the paths that actually decide, rather than
from the paths that look like they decide.

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

Implementation command (depends on: WP02, WP08, WP09):

```bash
spec-kitty agent action implement WP13 --agent <name>
```

## Subtasks & Detailed Guidance

### T071 — Emit from the decision, not beside it

- **Files**: `src/agent_inbox/federation/audit.py`
- Automated accept/reject events belong where WP03's policy function returns its refusal, so
  a new call site cannot forget to log.
- If a decision can be made without producing an audit entry, the log answers "why was this
  rejected" with silence — which reads as "it was not rejected".

### T072 — Administrative events

- **Files**: `src/agent_inbox/federation/audit.py`
- Mode changes, warning acknowledgements, peer add/enable/remove, blocklist changes, server
  profile changes, visibility changes, key changes — with the acting human's username.
- The acknowledgement id and version matter: "they accepted a warning" is weaker than "they
  accepted *this* warning text".

### T073 — Before and after, where safe

- **Files**: `src/agent_inbox/federation/audit.py`
- Never a private key, never a token, never message content. The spec's "where safe" is the
  requirement, not a caveat.
- A redaction that silently drops the field is better than one that logs a placeholder
  someone later treats as data.

### T074 — Append-only

- **Files**: `src/agent_inbox/federation/audit.py`
- No update path, no delete path. An audit log with an edit route answers nothing.
- Retention interacts with the existing purge: decide explicitly whether audit entries expire
  with mail, and record the answer. Silently purging the record of a rejection would be
  worse than keeping it.

### T075 — Tests

- **Files**: `tests/test_federation_audit.py`
- For each rejection path in WP09, assert an audit entry exists with the reason.
- For each administrative action in WP12, assert the acting human and the before/after.
- Assert no entry contains a key, a token, or message body — by scanning the whole entry,
  not by checking the fields you remembered.

## Definition of Done

- [ ] Automated events emitted from the policy decision itself.
- [ ] Administrative events carry the acting human and the acknowledgement id.
- [ ] Before/after present, with secrets never recorded.
- [ ] Append-only; retention decided explicitly and written down.
- [ ] Every WP09 rejection path has an asserted entry.
- [ ] Whole-entry scans prove no secrets leak.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Decisions that produce no entry | Silence reads as 'not rejected' | T071 emits from the decision itself |
| Secrets in before/after | Compromise via the audit trail | T073 redacts; T075 scans whole entries |
| Audit purged with mail | Loses the record of exactly the events worth keeping | T074 forces an explicit decision |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
