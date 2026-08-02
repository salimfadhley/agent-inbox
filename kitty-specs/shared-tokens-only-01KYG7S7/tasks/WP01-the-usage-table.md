---
work_package_id: WP01
title: The usage table, and one credential shape
dependencies: []
requirement_refs:
- FR-005
- FR-006
- FR-009
- FR-011
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
- T006
phase: Phase 1 - foundation
agent: python-pedro
history:
- at: '2026-08-02T12:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/auth/
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/auth/**
- tests/test_auth_service.py
- tests/test_auth_store.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP01 — The usage table, and one credential shape

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the profile in the frontmatter before reading
the rest of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer`

---

## Objective

A secret cannot name an agent. It never could — a shared token admits a machine, and the
name arrives separately in a header — and the code has been pretending otherwise since
device tokens were bound to actors.

This package makes the credential answer only the question it can answer (*is this good?*),
and adds the record that makes revoking an informed act: which agents this token has
actually let in.

## What is already true

Read this before changing anything; it is the difference between a small change and a large
one.

- `auth_device_tokens` already has `id`, `actor`, `token_hash`, `label`, `created`,
  `last_used`, `revoked`.
- `resolve_token` (`auth/service.py:523`) already raises `TokenRevoked` before anything
  else, and already calls `touch_token` — **an `UPDATE` and a `commit` on every
  authenticated request**.
- It has exactly **one** production caller: `api.py:1483`, inside
  `resolve_verified_caller`.
- `provide_caller` already returns the header name when the resolved caller is
  `SHARED_ACTOR`. This mission widens that path; it does not add one.
- Schema is a `_SCHEMA` tuple of `CREATE TABLE IF NOT EXISTS` executed at open. There is no
  migration framework and none is needed.

## Subtasks

### T001 — `TokenUse`, and the table behind it

```
auth_token_use
  token_id    TEXT NOT NULL
  actor       TEXT NOT NULL
  first_seen  TEXT NOT NULL
  last_seen   TEXT NOT NULL
  uses        INTEGER NOT NULL DEFAULT 0
  PRIMARY KEY (token_id, actor)
```

A frozen dataclass in `auth/records.py`, store methods on both the in-memory and SQLite
stores (`record_use`, `uses_for_token`, and whatever the listing needs), and one more entry
in `_SCHEMA`.

**One row per agent-token pair, overwritten in place.** Bounded by the number of agents no
matter how much traffic flows — that is FR-011, and it is what stops this becoming a log
that grows for ever while presenting as working.

`uses` counts **buckets, not requests** once T002 lands. Say so in the column comment: a
number that looks like a request count and is not is worse than no number.

### T002 — Coarse recording, and the write that is already there

At most **one write per token per minute**, held in memory per process.

The framing that matters: authentication *already* writes on every call. This is not a new
cost to justify — it is a reduction, and the existing `last_used` update must be folded
into the same bucketed write rather than left beside it. Two writes where there was one
would be the opposite of what FR-009 asks for.

Check the bucket **before** writing, not after. A conditional wrapped around a write that
has already happened is not a saving.

A restart empties the cache and writes once more than it needed to. That is the whole
restart story; nothing is lost and nothing needs persisting.

### T003 — `resolve_token` answers the question a secret can answer

Today it returns `token.actor`. Under this model a token has no actor, so it returns the
**token record** and the caller combines it with the claimed name.

`resolve_verified_caller` is the right place for that combination: it already reads the
header, and it is where "who is this" is decided for every route. Record the use there,
where both facts are in hand.

Do **not** infer the actor from the token. That is the habit this package exists to break.

**Revocation stays first.** It raises before anything else today; the refactor must not
move that check behind the new usage write.

### T004 — Minting takes a label, never an actor

`mint_token(label)`. No path — service, API or CLI — produces a token bound to an actor.

**FR-006, and it is where a lockout hides.** A row that already has a real actor keeps
authenticating that actor: it is listed as bound, it can be revoked, and nobody is locked
out by an upgrade. Do not migrate old rows silently — an operator should see what they have
and retire it deliberately.

New rows use `SHARED_ACTOR` or drop the column's meaning entirely; either is fine provided
the old rows keep working.

**`MintedToken` loses its `actor` field** (analysis finding A3). It is returned by the mint
route, so this changes a published response shape — do it here, deliberately, rather than
leaving a field that always says `*` and means nothing.

### T005 — Tests, and the order to write them in

**Write the lockout test first**, before touching `mint_token`: a token row with a real
actor still admits that actor. It is the requirement whose failure costs the most and the
one most easily lost in a refactor.

Then: two agents on one token both recorded; `first_seen` set once and `last_seen` moving;
a second call inside the same minute writing nothing; revocation still refusing on the next
call.

`tests/test_auth_service.py` and `tests/test_auth_store.py` are **rewritten, not deleted** —
the properties they pin still hold.

### T006 — Directive 4

```
perl -e 'alarm 300; exec @ARGV' codex exec "<one narrow question>" < /dev/null
```

The strongest question here: whether any path can still reach a token's `actor` field and
treat it as the caller's identity.

## Definition of Done

- The four gates pass.
- A legacy bound token still admits its agent, proved by a test written before the change.
- Two agents on one token are both recorded, bounded by one row each.
- A second authentication inside the bucket writes nothing.
- Revocation still refuses on the next call.
- Released and deployed to **both** hubs, proved with `verify-deployment`.

## Reviewer guidance

Trace the hot path. Every authenticated request runs this code, so the question is not
"does it work" but "what does it cost per request, and is that less than before".
