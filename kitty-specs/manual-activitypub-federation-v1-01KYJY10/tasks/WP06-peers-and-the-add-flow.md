---
work_package_id: WP06
title: Peers, the add flow, and the compatibility check
dependencies:
- WP03
- WP04
- WP05
requirement_refs:
- C-004
- FR-002
- FR-003
- FR-009
- FR-013
- FR-014
- FR-015
- FR-051
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/federation
merge_target_branch: feat/federation
branch_strategy: Planning artifacts for this mission were generated on feat/federation. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/federation unless the human explicitly redirects the landing branch.
subtasks:
- T031
- T032
- T033
- T034
- T035
- T036
- T081
phase: Phase 3 - Surfaces
agent: python-pedro
history:
- at: 2026-07-28T18:00:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/federation/
create_intent:
- src/agent_inbox/federation/peers.py
- tests/test_federation_peers.py
execution_mode: code_change
owned_files:
- src/agent_inbox/federation/peers.py
- tests/test_federation_peers.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP06 – Peers, the add flow, and the compatibility check

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

Adding a peer, and finding out before you trust it whether it can actually talk to
you. The spec's nine-step add flow, implemented in order — the order is the requirement.

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

Implementation command (depends on: WP03, WP04, WP05):

```bash
spec-kitty agent action implement WP06 --agent <name>
```

## Subtasks & Detailed Guidance

### T031 — Normalise, then check the blocklist first

- **Files**: `src/agent_inbox/federation/peers.py`
- Steps 1 and 2 of the spec's flow. Normalisation must produce the same canonical form the
  blocklist matcher uses (WP02 T006) — two normalisers that nearly agree is the failure this
  project keeps finding.
- Blocklist **before** any network call. A blocked host must cost zero requests, or the
  blocklist is a delivery suppressor rather than a boundary.

### T032 — Fetch and read the descriptor

- **Files**: `src/agent_inbox/federation/peers.py`
- Steps 3–5: fetch `/.well-known/agent-inbox`, read display name, base URL, version,
  capabilities, schemes, key metadata; warn if the declared base URL disagrees with the URL
  the operator typed.
- Treat everything fetched as untrusted input: bound the size, bound the time, and do not let
  a peer's `title` become markup on our page.

### T033 — Confirm WebFinger, and readiness

- **Files**: `src/agent_inbox/federation/peers.py`
- Steps 6–7. Accept descriptor-only readiness for an empty server — a new hub with no actors
  is a legitimate peer, and refusing it would make bootstrapping two fresh hubs impossible.
- Record key fingerprint and first-seen (step 8).

### T034 — Ready / Warning / Failed, with exact reasons

- **Files**: `src/agent_inbox/federation/peers.py`
- Step 9. The three states are a requirement, and so is the reason text. "Failed" with no
  reason is what makes an operator guess, and guessing is what gets HTTP enabled.

### T035 — Adding a peer imports nothing

- **Files**: `tests/test_federation_peers.py`
- The spec is explicit: adding a peer does not import a directory by default. Assert it —
  count the fetches made during an add and assert the directory was not among them.
- FR-003: adding a peer authorises *addressed mail exchange* and nothing else. Assert it
  grants no inbox read, no history, no admin access.

### T036 — Identity changes: the two directions

- **Files**: `tests/test_federation_peers.py`
- FR-015: changing our **public URL** is high risk and must warn that federated ids go stale.
- FR-051: changing the hub **`name`** is *not* high risk and needs no forwarding. Assert
  that a rename leaves every federated surface byte-identical — that is the test that makes
  FR-048 load-bearing rather than decorative.

### T081 — The trust boundary, asserted as negatives

- **Files**: `tests/federation_peers` tests owned by this package
- FR-003 says adding a peer authorises **addressed mail exchange and nothing else** — not
  database access, not inbox reads, not admin API access, not history.
- A requirement of that shape is only met by **negative** tests. Assert that an enabled,
  fully-trusted peer cannot: read any actor's inbox, read thread history it was not
  addressed into, reach any operator-gated route, or enumerate actors beyond the
  discoverable directory.
- **Found missing by outside review, 2026-07-28.** FR-003 was mapped to this package on the
  strength of the peer add flow, which establishes trust but never bounds it. A security
  boundary with no test is a claim, not a boundary.

## Definition of Done

- [ ] The nine steps run in the spec's order.
- [ ] Blocklist precedes any network call, asserted by fetch count.
- [ ] Descriptor fields are bounded and never rendered as markup.
- [ ] Empty-server peers can be added.
- [ ] Ready/Warning/Failed each carry a reason.
- [ ] A hub rename changes no federated surface; a URL change warns.
- [ ] All four charter gates pass.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Two normalisers | A blocklist bypass | T031 shares WP02's canonical form |
| Network calls before the blocklist check | The blocklist stops being a boundary | T031 orders it first; T035 counts fetches |
| A peer's text rendered as markup | Stored XSS from a hostile peer | T032 treats fetched fields as untrusted |
| Adding a peer quietly importing a directory | Unbounded work from one operator click | T035 asserts the fetch was not made |

## Reviewer Guidance

- For every test this package adds that guards a rule, **delete the rule and run the test**.
  If it still passes, the test is looking at nothing. This project has shipped four such
  tests and caught all four this way.
- Check that no policy decision is made outside `federation/policy.py`.
- Check that assertions about refusal look at the thing that should not have happened — an
  inbox that stayed empty, an attempt that was never made — rather than at a status code.
