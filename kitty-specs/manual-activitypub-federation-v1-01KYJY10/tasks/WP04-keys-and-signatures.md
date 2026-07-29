---
work_package_id: WP04
title: Keys and RFC 9421 signatures
dependencies:
- WP02
requirement_refs:
- FR-039
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T018
- T019
- T020
- T021
- T022
- T023
phase: Phase 2 - The decision
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/keys.py
- src/agent_inbox/federation/signatures.py
- tests/test_federation_signatures.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/keys.py
- src/agent_inbox/federation/signatures.py
- tests/test_federation_signatures.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP04 – Keys and RFC 9421 signatures

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

Sign what we send; verify what arrives. `cryptography` is already a dependency
(auth uses it), so this needs no new package.

This is the one place where a mistake is silent and total. A verifier that accepts an
unsigned request, or that verifies bytes other than the ones it acts on, passes every test
that does not attack it.

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
spec-kitty agent action implement WP04 --agent <name>
```

## Subtasks & Detailed Guidance

### T018 — A signing keypair, generated once and kept

- **Files**: `src/agent_inbox/federation/keys.py`
- Generate on first need, store beside the mail, never regenerate silently.
- The private key is a secret: it must never appear in the descriptor, the audit log, an
  error message, or a log line. FR-042 says "before/after values **where safe**".
- Rotation is out of scope for V1, but leave the key identified so rotation is possible
  later without a migration.

### T019 — Public key metadata in actor documents

- **Files**: `src/agent_inbox/federation/keys.py`
- Peers need it to verify us. Emit it in the shape ActivityPub implementations expect.
- Note per C-008 that the fediverse's de-facto shape and RFC 9421 are not the same thing;
  FR-039 says RFC 9421 "unless planning proves a compatibility shim is required". Record what
  you find rather than deciding silently.

### T020 — Sign outbound requests

- **Files**: `src/agent_inbox/federation/signatures.py`
- Cover the components that matter: method, target, host, date, and a digest of the body.
- **Sign the body that is actually sent.** Signing a serialisation and sending a different
  one is a bug that only shows up against a strict peer.

### T021 — Verify inbound requests

- **Files**: `src/agent_inbox/federation/signatures.py`
- Fetch the sender's key via its actor document, bounded by the fetch budget.
- Reject: missing signature, unknown key, wrong key, altered body, stale or future date.
- **Default to refusal.** Any path through this function that ends in "accepted" without a
  verified signature is the whole hole.

### T022 — Attack the verifier

- **Files**: `tests/test_federation_signatures.py`
- A valid request and a garbage request prove nothing interesting. Required cases:
  **tampered body** (valid signature, changed content), **replay** (a previously-valid
  request sent again), **wrong key** (validly signed by someone else), **no signature at
  all**, and **signature over different components than were sent**.
- Then remove the verification call and re-run. Tests must fail. Record it.

### T023 — Clock skew, deliberately

- **Files**: `src/agent_inbox/federation/signatures.py`
- Pick a tolerance and write down why. Too tight and honest peers fail; too loose and replay
  becomes practical.
- Use the injected clock from WP01 so this is testable at the boundary rather than
  approximately.

## Definition of Done

- [ ] Keypair generated once, stored, never in a log or descriptor.
- [ ] Public key metadata in actor documents.
- [ ] Outbound requests signed over the bytes sent.
- [ ] Inbound verification defaults to refusal.
- [ ] Tampered, replayed, wrong-key and unsigned all rejected, each asserted.
- [ ] Removing verification makes tests fail; recorded.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A path that accepts without verifying | Total, and silent | T021 defaults to refusal; T022 removes the call and watches tests fail |
| Signing different bytes than are sent | Passes locally, fails against strict peers | T020 signs the sent body |
| The private key reaching a log or the descriptor | Compromise | T018 forbids it; audit records no secrets |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
