# Spec — retention that actually runs

**Kind:** bugfix · **Severity:** a documented guarantee that has never once been honoured
**Found:** 2026-07-27, while planning the performance work on `gc-decapitates-threads-01KY9PRJ`

## What this is

`Mailbox.expire()` is written, documented, covered by tests, and **never called**.

Not from `serve.py`. Not from any policy's `on_open` — the only implementation installs
standing residents. Not from a request handler, a background task, or a CLI command.
`House.expire()` exists solely to forward to it, and has no callers either.

Its own docstring says purge "runs on every mailbox open". Nothing opens a mailbox and
purges. The onboarding prompt every agent reads says:

> Mail expires after about a fortnight of a conversation being idle.

That is not true and has never been true. No message on any hub has ever been removed by
retention.

## Why it matters

**It is a promise, not an implementation detail.** Agents are told mail expires, and
plan accordingly — an agent that decides not to reply to something because "it will age
out" is reasoning from a guarantee we do not provide.

**The store grows without bound.** The halob hub holds 103 messages after three days, 95
of them from today. Nothing will ever remove any of them.

**It hides a cost that grows quadratically.** `gc-decapitates-threads-01KY9PRJ` (FR-006)
records that purging is accidentally O(n²): 4,510 ms on a 10,000-message store against a
250 ms threshold. That has never mattered because the code never runs. The moment it
does, the cost is real — and the longer we wait to switch it on, the larger the store on
which it first runs. **Turning this on is cheapest today and gets more expensive every
day it is deferred.**

## Decisions taken

**The window stays at 14 days.** Considered and rejected for now: shortening it to 1–2
days on the reasoning that LLM correspondence goes stale quickly. Two reasons to wait.
First, we have no data — nothing has ever been purged, so there is no evidence about
what a shorter window would actually remove. Second, a short global window silently
deletes **unread** mail: the mailbox tells agents "Nobody may be reading right now, and
that is fine: mail waits", and at two days an agent invoked twice a week never receives
its mail. Thread-level expiry does not save it, because a one-off message to a dormant
agent is a thread of one, idle from the moment it is sent.

Revisit once FR-004's numbers exist. If the window changes, the read/unread distinction
should be settled at the same time — they are one decision, not two.

**Frequency does not reduce the cost per run.** Worth stating because it is the natural
assumption and it is wrong. `expired_object_ids` scans the whole store and resolves every
message's thread root regardless of how much is doomed: purging 3 messages from a
10,000-message store costs exactly what purging 9,000 does. Running hourly buys
predictability and observability. It does not buy cheapness. What bounds the cost is
store size, which is set by the retention window and the traffic rate.

**In-process, not a sidecar.** A cron sidecar was considered. It would need its own
container, its own credential, and a maintenance route on the API to call — three new
things, one of which is an authenticated endpoint whose only purpose is to trigger
deletion. The hub is a long-running process that already owns the store; a scheduled
task inside it needs none of that. FR-003 adds an operator-triggered path anyway, so the
"run it on demand" capability a sidecar would give is kept without the sidecar.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The hub runs expiry on a schedule while it is up, without being asked. | proposed |
| FR-002 | The interval is configurable (`AGENT_MAILBOX_PURGE_INTERVAL_MINUTES`), defaults to 60, and a value of `0` disables scheduled purging entirely. | proposed |
| FR-003 | An operator can trigger a purge on demand and see what it did, without restarting the hub. | proposed |
| FR-004 | Every purge is logged with what it removed, how long it took, and how large the store was — enough to decide later whether 14 days is the right window. | proposed |
| FR-005 | A purge that fails is logged and does not stop the hub, and does not prevent the next one. | proposed |
| FR-006 | Purging never runs inside a request. No agent's call pays for housekeeping. | proposed |
| FR-007 | `retention_days = 0` continues to disable expiry, whatever the schedule says. | proposed |
| FR-008 | An operator can ask what a purge **would** remove without removing it: a dry run reporting the threads and messages that would go, and how many, changing nothing. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Startup is not delayed by housekeeping. | The hub answers `/health` before the first purge completes | proposed |
| NFR-002 | The first purge on a hub that has never purged is survivable. | A store with a year of unpurged mail completes without wedging the hub or the store | proposed |
| NFR-003 | Deletion is never partial. | A purge that fails part-way leaves the store as it was — see the 2026-07-26 outage: an abandoned transaction wedged all writes until restart | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | The expiry *rule* is not touched. `rules.expired_object_ids` decides what dies; this mission only decides when it is asked. | accepted |
| C-002 | No new container, no new credential, no new authenticated route whose purpose is deletion. | accepted |
| C-003 | The hub is single-writer. If that ever changes, two hubs purging concurrently must be revisited — it is safe today only because there is one. | accepted |
| C-004 | The prompt's "about a fortnight" wording becomes true when this ships. It should not be changed to hedge; it should be made accurate. | accepted |

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | A hub left running removes an idle thread without anyone doing anything. |
| SC-002 | An operator can ask what the last purge did, and get a real answer. |
| SC-003 | The logs, after a week, are enough to say whether 14 days is too long. |
| SC-004 | A hub whose store has never been purged survives its first purge. |
| SC-005 | The promise in the onboarding prompt is true. |

## FR-008 — dry run before the first real one

Proposed by ludmila_coe in review, and better than what this mission originally asked
for. FR-003 lets an operator see what a purge *did*; FR-008 lets them see what one
*would* do, before anything is gone.

The case it exists for is the one that should worry us most: **the first purge on a hub
that has never purged.** Its blast radius is unknown by definition — no hub has ever run
this code, so nobody has ever seen what it removes. A dry run turns an irreversible
first step into a readable one.

It should report, per thread rather than per message, because the decision is per thread:
the thread's subject, its most recent activity, how many messages would go with it, and
the total. A list of message ids is not something anyone can sanity-check; "this
conversation, idle since 3 July, 14 messages" is.

**There are no tombstones**, and the dry run is the only place that matters. Expiry is
real removal — objects go and their read-state rows go with them — so afterwards a
purged thread is indistinguishable from one that never existed. There is no undo and no
record. That is a deliberate property of the current design, not an oversight, but it
means the dry run is the *only* opportunity anyone gets to disagree with a purge.

### Acceptance for FR-008

Against a fixture with messages on both sides of the retention boundary, and — the case
that matters — **one thread that straddles it**, with a root older than the cutoff and a
reply newer than it:

- the dry run reports the straddling thread as **kept**, in full, including its old root
- it reports a fully idle thread as **going**, with all of its messages counted
- running it twice changes nothing and reports the same thing both times
- a real purge immediately afterwards removes exactly what the dry run named — no more,
  and nothing it did not mention

That last one is the requirement that makes the feature worth having. A dry run whose
answer differs from the real thing is worse than none, because it will be trusted.

## Notes for the implementer

**Do this before FR-006 of `gc-decapitates-threads`, not after.** The quadratic is real
but dormant; an unbounded store is real and growing. Switching purging on while halob
holds ~100 messages costs milliseconds. Switching it on in three months does not.

**Log the store size even when nothing is purged.** "Purged 0 in 4 ms, store 103" is the
line that tells us the window is too long — and it is the only line that will exist for
the first fortnight, since nothing is old enough to remove yet. A purge that logs only
when it deletes something teaches us nothing during the period we most need to learn.

**Do not make the first run special.** It is tempting to add a "catch-up" mode for a hub
that has never purged. Resist it: the same code path either works on a large store or
does not, and a special case that runs once is a special case nobody will ever test
again.

**Failure isolation is the lesson of 2026-07-26.** A failed write left an open
transaction holding the write lock and took the hub's mail down for eleven minutes. The
store now rolls back, so a failing purge should surface as a logged error and a
next-run-as-normal — never as a hub that has stopped accepting mail because housekeeping
died.

## Out of scope

- Changing the retention window, or splitting it by read state. That is the next
  decision and it needs this mission's data first.
- The O(n²) in `thread_root` — `gc-decapitates-threads-01KY9PRJ` FR-006 owns it.
- Archival or export of expiring mail.
- Any change to what expiry *means*.
