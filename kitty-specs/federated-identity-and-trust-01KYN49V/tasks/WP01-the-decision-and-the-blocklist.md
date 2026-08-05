---
work_package_id: WP01
title: The decision, and the blocklist
dependencies: []
requirement_refs:
- FR-004
- FR-006
- FR-007
tracker_refs:
- '44'
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. Completed changes merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
agent: python-pedro
history:
- at: '2026-08-05T08:40:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/peers.py
create_intent:
- tests/test_blocklist.py
execution_mode: code_change
owned_files:
- src/agent_inbox/peers.py
- tests/test_blocklist.py
role: implementer
tags: []
---

# WP01 — The decision, and the blocklist

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

One function that answers *may this exchange happen*, and a blocklist that **overrides
the mode in every case**.

This is the MVP of the mission and the concrete safety gap. Today the only way to refuse
a peer is never to add it — and FR-004 says explicitly that is not the same thing.

## What is already there

Read before writing. Verified in the source on 2026-08-04:

- `peers.py` holds the add flow: normalise, fetch the descriptor, check it, report.
- `ALLOWED_SCHEMES = ("https",)` at `peers.py:42`, with a comment on why a scheme
  *allowlist* beats a denylist. FR-005 is done; do not rebuild it.
- `check_may_enable_federation()` exists and is called from `api.py:469`. FR-002 is done.
- **"blocklist" appears nowhere in `src/`.** That is the whole of what is missing.

## The parent mission said this better than the spec does

`manual-activitypub-federation-v1` WP03 — now superseded by this package — called the
decision function *"the highest-value target in the mission"*, and gave the reason:

> If the decision is made in two places they will disagree, and a disagreement here is a
> disclosure.

That is C-006, and it is the thing to protect.

## Subtasks

### T001 — One function that decides

A single place answering *may this exchange happen*, consulted by every path that needs
the answer. Not a helper each caller wraps differently.

**The test that matters is not that it returns the right answer.** It is that no second
implementation exists — so include a test that fails if the decision is made anywhere
else, by searching for the shape of a re-derivation rather than trusting review.

### T002 — The blocklist, stored, and normalised

Stored-only, with no environment equivalent — decision `01KYMQ6PTT9J16PCA5H8FF66QX`:
precedence applies to scalars, lists do not have it.

Matching is deterministic and survives the three ways a blocklist is evaded by accident:
**case**, a **trailing slash**, and an **explicit default port**. `https://Peer.example/`
and `https://peer.example:443` are the same peer as `https://peer.example`.

### T003 — It overrides the mode, in every case

FR-004: *"A blocklist exists and overrides the mode in every case. It is not a mode."*

So a blocked peer is refused in `allowlist` mode even when it is also on the allowlist.
That combination is not a contradiction to resolve — it is a peer somebody added and
later blocked, and block wins.

### T004 — Consulted before any network call

FR-007 orders the add flow: normalise, **check the blocklist**, *then* fetch the
descriptor.

The order is the requirement, not an optimisation. Blocking somebody while still sending
them a request tells them we tried, which is worse than not blocking them — and the test
matrix says so: *"A blocked domain in `allowlist` mode → refused, and no network call
made."*

### T005 — Tests

In `tests/test_blocklist.py`:

- A blocked peer is refused in `allowlist` mode.
- **No network call is made** — assert by counting, with a fetch that fails the test if
  it is called at all.
- Blocked survives trailing slash, case, and `:443`.
- **The paired positive**: an unblocked peer in `allowlist` mode is still accepted, and
  the descriptor *is* fetched. Without it, a blocklist that refused everything would
  satisfy every test above.
- Removing a block restores the peer.
- The decision is made in one place.

**Run the removal proof.** Delete the blocklist check from the add flow, watch the
refusal tests fail, restore it, and confirm the paired positive passed throughout.

## Definition of Done

- An operator can refuse a specific peer, and that refusal beats the mode.
- No request reaches a blocked peer.
- One decision function; no second implementation.
- Four gates green.

## Reviewer guidance

Grep for anywhere other than the decision function that decides whether an exchange may
happen. One is correct; two is the defect this package exists to prevent, and it will not
announce itself.
