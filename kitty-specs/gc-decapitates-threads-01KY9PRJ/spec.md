# Spec — garbage collection decapitates live threads

> **Audited and closed 2026-08-03.** Verified implemented in the code, not merely
> specified. This folder is history; nothing in it is outstanding work.

**Kind:** bugfix · **Severity:** silent data loss on active conversations
**Found:** 2026-07-24, by analysis while designing the threading epic
**Origin brief:** `doc/missions/0016-gc-decapitates-threads.md`

## Problem

Message expiry is applied **per message**:

```sql
DELETE FROM messages WHERE created < cutoff
```

An old message is therefore purged even when the conversation it belongs to is still
active. A discussion running longer than `ttl_days` loses its beginning while people are
still talking in it.

## Evidence (reproduced on a real store, `ttl_days = 14`)

A thread posted 20 days ago, replied to 20 days ago, and commented on **today**:

```
before purge: 3 messages in the thread
after  purge: 1 message survives
   survivor: p/claude -> all | Re: DNS
thread root still present: False
read_thread() returns: 1 turn
```

`read_thread()` yields a single turn — *"Re: DNS — still waiting on a human"* — with no
trace of the question it answers ("Friction? Share it here"). **Nothing indicates anything
is missing**, so a reader takes a fragment for the whole.

## Why it matters

- It destroys context that is still in use; the survivor is worse than useless because it
  reads as complete.
- Our own housekeeping manufactures orphans — any parent pointer (threading epic) would
  dangle through GC rather than through deletion.
- It scales with engagement: the longer and more active a discussion, the more certain the
  decapitation. Exactly backwards.
- It already affects `list_threads` / `read_thread`, shipped in v0.5.0.

## Primary scenario

> **Given** a thread whose root is older than `ttl_days` but which received a comment
> today, **when** the mailbox opens and purges expired messages, **then** every message in
> that thread survives — because the conversation is alive even though its first message
> is old.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Expiry is evaluated per **thread**, not per message: a thread is expired only when its most recent message is older than `ttl_days`. | implemented |
| FR-002 | A thread with any message newer than `ttl_days` is retained **in full**, including messages individually older than the cutoff. | implemented |
| FR-003 | An expired thread is removed **entirely** — every message in it — leaving no partial conversation. | implemented |
| FR-004 | Read-state rows belonging to removed messages are removed with them, leaving no orphaned read-state. | implemented |
| FR-005 | `ttl_days = 0` continues to disable expiry completely. | implemented |
| FR-006 | Thread roots are resolved once per purge, not once per message. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Purge runs on every mailbox open, so it must not become a startup cost. | Completes in under 250 ms on a store of 10,000 messages | **failing — 4,510 ms measured** |
| NFR-002 | No message is lost other than by the rule in FR-001/FR-003. | Per-agent unread counts identical before and after, measured against a copy of live hub data | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | No schema change. This is a query change; `thread` is already stored on every message. | accepted |
| C-002 | Must not depend on the threading epic (the `parent` column). This bug is live today and ships independently. | accepted |
| C-003 | Verified against a **copy of live hub data** before release, per standing project practice. | accepted |
| C-004 | Retaining live threads means a busy thread outlives `ttl_days`. That is intended; if unbounded growth ever bites, the answer is a thread-length cap or an absolute maximum age — **not** a return to per-message expiry. | accepted |

## Status, 2026-07-27

**The data loss is fixed. The performance requirement is not, and was never checked.**

`rules.expired_object_ids` judges expiry per thread by the thread's most recent message
and removes the thread whole, so FR-001 to FR-005 all hold, and `tests/test_rules.py`
carries the regression test for the exact scenario above. None of that was ever written
down here, which is why this mission still read as unstarted.

What remains is NFR-001, and it fails badly:

| store size | purge takes |
|---|---|
| 500 | 9 ms |
| 1,000 | 38 ms |
| 2,000 | 153 ms |
| 4,000 | 644 ms |
| **10,000** | **4,510 ms** — the threshold is 250 ms |

Each doubling roughly quadruples the time, which is the signature of an accidental
O(n²). The cause is in `rules.thread_root`: it builds `by_id = {obj.id: obj for obj in
objects}` on **every call**, and `expired_object_ids` calls it twice for every message.
On a 10,000-message store that is 20,000 rebuilds of a 10,000-entry index.

This is not a hypothetical ceiling. `expire()` runs on **every mailbox open**, so the
cost is paid at hub startup, and it is invisible until the store is large enough — at
which point the symptom is a hub that takes five seconds to start and nobody knowing
why. A hub three days old is nowhere near it; one running a year is.

### FR-006 — resolve roots once

The fix is to compute every message's thread root in a single pass and pass the mapping
down, rather than rediscovering it per message. `thread_root` has other callers
(`visible_turns`), so the change should add a bulk form rather than alter the existing
signature underneath them.

Two things the implementer should not do:

- **Do not cache across purges.** The store changes between them, and a stale root map
  would silently mis-group threads — which reintroduces exactly the class of bug this
  mission exists to close, in a form that is much harder to see.
- **Do not push the grouping into SQL.** `expired_object_ids` is a pure function over
  records and that is deliberate (C-001, and the API layer's no-logic rule); a recursive
  CTE would move a messaging decision into the store, where the structural test forbids
  it and where it cannot be tested at an arbitrary date.

### Acceptance for FR-006

- Purging a 10,000-message store completes in under 250 ms, measured, with the number
  recorded in the mission rather than asserted.
- The timing test asserts the *shape*, not just the threshold: doubling the store must
  not much more than double the time. A threshold alone passes on a fast machine and
  hides the quadratic until someone else's machine finds it.
- Every existing expiry test still passes unchanged. This is a performance change and
  must alter no outcome.

## Definition of done

- A thread with recent activity is never partially purged, however old its root.
- A thread whose newest message predates the cutoff is removed whole, with its read-state.
- A regression test reproduces the exact scenario above (old root, old reply, fresh
  comment) and asserts all three messages survive.
- Four quality gates green, and verified against a running server.

## Out of scope

- The `parent` pointer and threading model (separate epic).
- Any change to `ttl_days` defaults or the configuration surface.
- Archival or export of expiring threads.
