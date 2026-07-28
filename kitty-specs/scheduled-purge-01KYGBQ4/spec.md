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

**The store grows without bound.** The deployed hub holds 103 messages after three days, 95
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

## How it runs

**An asyncio task inside the hub process, started by Litestar's lifespan.** Not a
sidecar, not a cron container, not a thread.

```python
@asynccontextmanager
async def purge_loop(app: Litestar) -> AsyncIterator[None]:
    task = asyncio.create_task(_purge_forever(house, interval, log))
    try:
        yield                       # the hub serves for its whole life here
    finally:
        task.cancel()               # and the loop stops with it
        with suppress(asyncio.CancelledError):
            await task


async def _purge_forever(house, minutes, log):
    while True:
        await asyncio.sleep(minutes * 60)   # sleep FIRST — see below
        try:
            removed = await house.expire()
            log.info("purge: removed %d, store now %d, took %d ms", ...)
        except Exception:                    # noqa: BLE001
            log.exception("purge failed; retrying at the next interval")
```

Four properties fall out of this shape, and each answers something that would otherwise
need designing:

**It sleeps before its first run**, so nothing is deleted at startup. That matters more
than it looks: on-startup deletion puts the blast radius in the hands of whoever last
restarted the container, at the moment nobody is watching, and makes a routine restart
into an unbounded irreversible action. A hub that has just come up should serve, not
delete.

**A failure is logged and the loop continues.** One bad purge must not stop the next
one, and — the lesson of the 2026-07-26 outage — must not take the hub down with it. The
`except` is deliberately broad: housekeeping is the one place where "keep serving mail"
beats "fail loudly".

**It is cancelled with the app.** No orphaned task, no purge running against a store
that is closing.

**It needs no credential, because it is not a caller.** It holds the `House` directly.
There is no network hop to authenticate, no token to issue, no route to guard.

### Why not a sidecar

Considered seriously; rejected on four counts, of which the last is decisive:

1. A second container and image to build, ship and version alongside the hub.
2. **Its own device token — a standing credential whose only power is deleting mail.**
   That is the most dangerous credential the hub could issue, and it would have to exist
   permanently, in a config file, on the same machine.
3. An authenticated deletion route on the API for it to call.
4. **Its failures are invisible.** An in-process loop that dies takes its stack trace to
   the hub's own log, where the operator is already looking. A sidecar that dies stops
   purging silently, and the symptom — mail not expiring — is exactly the symptom we
   have today and did not notice for the life of the project.

A sidecar buys one thing: purging that survives the hub being down. But a hub that is
down is not accumulating mail either, so there is nothing to purge.

### What still wants a route, and what does not

**v1 needs no deletion route.** The dry run (FR-008) is *read-only* — it reports what
would go and changes nothing — so it is an operator-gated `GET`, guarded exactly like
the existing `/auth/tokens` routes, and no more dangerous than the observation routes
already there.

The on-demand *trigger* (FR-003) is the only thing that would need a route capable of
deleting. With an hourly schedule, "on demand" saves at most an hour, so it is
**deferrable**: ship the loop and the dry run, and add the trigger only if waiting an
hour turns out to matter. If it is added, it is an operator-gated `POST` — the same
guard, no new credential, and still no sidecar.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The hub runs expiry on a schedule while it is up, without being asked. | implemented |
| FR-002 | The interval is configurable (`AGENT_MAILBOX_PURGE_INTERVAL_MINUTES`), defaults to 60, and a value of `0` disables scheduled purging entirely. | implemented |
| FR-003 | An operator can trigger a purge on demand and see what it did, without restarting the hub. | implemented |
| FR-004 | Every purge is logged with what it removed, how long it took, and how large the store was — enough to decide later whether 14 days is the right window. | implemented |
| FR-005 | A purge that fails is logged and does not stop the hub, and does not prevent the next one. | implemented |
| FR-006 | Purging never runs inside a request. No agent's call pays for housekeeping. | implemented |
| FR-007 | `retention_days = 0` continues to disable expiry, whatever the schedule says. | implemented |
| FR-008 | An operator can ask what a purge **would** remove without removing it: a dry run reporting the threads and messages that would go, and how many, changing nothing. | implemented |
| FR-009 | ~~Until scheduled purging exists, the prompt says retention is not currently enforced.~~ **Moot.** The user's instruction was "don't change the doc, just fix expiry", so the wording became true instead of being hedged. The prompt was false for a few hours on 2026-07-27 and is now accurate. | superseded |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Startup is not delayed by housekeeping. | The hub answers `/health` before the first purge completes | implemented |
| NFR-002 | The first purge on a hub that has never purged is survivable. | A store with a year of unpurged mail completes without wedging the hub or the store | implemented |
| NFR-003 | Deletion is never partial. | A purge that fails part-way leaves the store as it was — see the 2026-07-26 outage: an abandoned transaction wedged all writes until restart | implemented |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | The expiry *rule* is not touched. `rules.expired_object_ids` decides what dies; this mission only decides when it is asked. | accepted |
| C-002 | No new container and no new standing credential. **Revised**: the original wording also forbade "any authenticated route whose purpose is deletion", which contradicted FR-003. See "How it runs" — v1 needs no deletion route at all. | accepted |
| C-003 | The hub is single-writer. If that ever changes, two hubs purging concurrently must be revisited — it is safe today only because there is one. | accepted |
| C-004 | ~~The prompt's "about a fortnight" wording becomes true when this ships; do not hedge, make it accurate.~~ **Revised — see FR-009.** Correct only if this ships immediately. It is queued behind two other missions, so the prompt states a falsehood in the meantime. | superseded |

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

### Reporting detail (FR-008)

Per **thread**, with the reason, by default — *"idle since 3 July — 14 messages"*. The
reason is what makes it checkable, and it is short because it is always the same shape.
Message ids behind a flag: nobody can look at forty ids and tell whether the decision
was right, so ids as the default would make the first run — the one that matters — less
readable, not more. Settled with ludmila_coe.

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

## Test matrix

Largely ludmila_coe's, with four additions. The first six are the cases anyone would
think of; the last four are the ones that bite.

| case | expected |
|---|---|
| thread entirely older than the cutoff | purged whole |
| thread entirely newer | kept |
| **old root, fresh reply** | kept **in full**, including the old root — the case the GC mission exists for |
| fresh root, old reply | kept in full |
| direct message read by one recipient, unread by another | purged on the thread's age regardless — see below |
| broadcast with read-state rows for several agents | purged with every one of those rows, none orphaned |
| **newest message exactly at the cutoff** | kept — the rule is `last < cutoff`, and boundary equality is where rules like this fail |
| **reply whose parent is already gone** | root resolution terminates on the orphan; nothing else in its thread is miscomputed |
| **a cycle in `inReplyTo`** | terminates. Cannot arise from correct use, but `thread_root` guards it explicitly, which means someone thought it could — pin it so the guard is not optimised away |
| **`retention_days = 0` with a schedule configured** | nothing is purged. The disable must win; a scheduler that ignores the off switch is the worst bug available in this mission |

**Expiry is by age, not by read state.** A message unread by one recipient and read by
another expires on its thread's age like any other. That is current behaviour and this
mission does not change it — but it is exactly the property that makes shortening the
window dangerous, so the matrix asserts it rather than assuming it.

## Notes for the implementer

**Do this before FR-006 of `gc-decapitates-threads`, not after.** The quadratic is real
but dormant; an unbounded store is real and growing. Switching purging on while examplehub
holds ~100 messages costs milliseconds. Switching it on in three months does not.

**Log the store size even when nothing is purged.** "Purged 0 in 4 ms, store 103" is the
line that tells us the window is too long — and it is the only line that will exist for
the first fortnight, since nothing is old enough to remove yet. A purge that logs only
when it deletes something teaches us nothing during the period we most need to learn.

**The entry point is a scheduled task plus an operator trigger — not mailbox open.**
On-open ties an unbounded amount of deletion to a process restart: the one moment nobody
is watching, and the moment the hub is least able to report what it did. It also puts
the blast radius in the hands of whoever last restarted the container, who does not know
they are deciding anything. The docstring's claim that purge "runs on every mailbox
open" describes an operational shape we are deliberately not adopting, and it should be
corrected when the caller is added rather than left to mislead the next reader.

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


## Shipped, 2026-07-27 — v0.18.1, live on examplehub

`event=mailbox.purge.scheduled interval_minutes=60 retention_days=14` in the hub log.

| commit | what |
|---|---|
| `6ff7bf7` | scheduler, operator routes, console page, and the O(n²) fix |
| `13f3d57` | the console routes were never registered — 404 on the live hub |
| `ba521fe` | loop-death detection, single-pass purge, structured logs |

### Two things this got wrong first, both worth keeping written down

**The console page was unreachable and every test passed.** The handlers were written,
the nav linked to them, and neither was in `route_handlers`. Nothing covered console
*routing* — the existing tests reference handlers directly, so an unreachable handler is
indistinguishable from a working one. Found by curling the deployed hub. Five tests now
exercise the page as a route.

**The loop's own death was silent**, which is precisely what this mission rejected the
sidecar for. Raised by ludmila_coe, who noticed the argument had been made and not
applied: moving a task indoors does not make it observable, it only moves where nobody
is looking. A done-callback now logs CRITICAL and says what it means — retention is no
longer running — rather than reporting that a task ended.

The same review found that the loop previewed and then expired, deciding the doomed set
twice, so on a busy hub it could report one thing and delete another. It now purges in
one pass and reports what it actually removed.

### The observability surface, and where it came from

| you want | use |
|---|---|
| a human glance | `agent-inbox hub` — one sentence, distinguishing "just restarted" from "a fault if it persists" |
| something that parses | `agent-inbox retention` — the schedule object |
| no shell at all | `GET /observe/purge/status` — any authenticated caller |
| what would actually go | `/maintenance`, or `GET /observe/purge` — **operator only**, because it lists subjects |

The split is the point. Asking *whether housekeeping runs* needs no delete rights;
asking *what it is about to remove* is asking to read mail. Conflating them means the
liveness check requires the credential that can destroy every message on the hub, which
is how a check stops being performed — and an unperformed check is exactly how retention
came to be broken here for the life of the project.

Four of the five pieces of this surface exist because **ludmila_coe** asked for them in
review: the loop that reports its own death, the loop that does not starve on a
frequently restarted hub, the heartbeat proving it arrived at all, and a read path that
does not require delete rights. None were in the original spec. The pattern across all
four is one blind spot: *built, reported as working, unobservable*.

### Still to do

**The first real purge has not happened and cannot yet.** examplehub is three days old and
the window is fourteen, so nothing is eligible until about 2026-08-07. Until then every
cycle logs `removed_threads=0`, which is the evidence the retention-window question
needs and which accumulates on its own.

Before that first purge, per ludmila_coe: copy the store, dry-run against the copy,
compare the report, dry-run against the live store, and only then take the explicit
operator action. The console already enforces the last step — the preview is shown every
time, and the button is separate from it.

The retention window itself remains an open question, deliberately deferred until those
logs exist. If it changes, the read/unread distinction should be settled at the same
time; they are one decision.
