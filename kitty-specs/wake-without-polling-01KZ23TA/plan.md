# Implementation Plan: The waiter listens instead of polling

**Branch**: `main` | **Date**: 2026-08-02 | **Spec**: `kitty-specs/wake-without-polling-01KZ23TA/spec.md`

## Summary

Make `wake.py`'s waiter event-driven. It keeps its shape — the same lock, the same
watermark, the same `wake_response`, the same fail-silent wrapper — and gains one thing: a
held connection to the hub's per-actor event stream that lets it stop sleeping the moment
mail arrives. Polling stays underneath, unconditionally, so nothing depends on the stream
working.

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: none new. `urllib.request` (stdlib) for the connection,
`threading` (stdlib) for the reader, and the client's existing `SseParser`,
`HubClient.events_url` and `HubClient.stream_headers`.
**Storage**: none. The watermark file is unchanged and is not part of this work.
**Testing**: pytest. A fake stream that a test drives directly, so no socket and no timing
dependence; plus the existing `wake` tests, which must pass **unmodified** — that is the
proof the decision did not move (SC-004).
**Target Platform**: the agent's own machine, as a hook subprocess. Linux and macOS.
**Project Type**: single package, `src/agent_inbox/`.
**Performance Goals**: arrival to notice under one second (against up to five today); one
held connection plus a bounded slow poll, against ~5,760 requests per eight-hour wait.
**Constraints**: fail-silent — any failure prints nothing and exits 0. Standard library
only. No hub-side change. `interrupt.py` untouched.
**Scale/Scope**: one file substantially (`wake.py`), one small seam in `client.py` if the
stream reader lands there instead. Two connections per actor at most, against a cap of 64.

## The one design decision

The waiter is **synchronous** — it is a CLI subprocess run as a hook, not the async MCP
server — so it cannot `await` a stream. It has to hold a blocking connection *and* keep a
bounded poll running, and the shape of the answer is the whole plan.

**Chosen: a reader thread and an interruptible sleep.**

Today the loop ends each pass with `sleep(min(poll_interval, remaining))`. `sleep` is
already an injected `Sleeper`, which is how the existing tests run eight simulated hours
instantly. Replace the *implementation* passed in, not the loop:

- a daemon thread holds the stream, parses it with `SseParser`, and sets a
  `threading.Event` on each `mail` event;
- the loop's sleep becomes `event.wait(seconds)` — it returns early when the thread
  signals, and otherwise behaves exactly like `time.sleep`.

Why this and not the alternatives:

- **A socket read timeout** (read the stream with a timeout equal to the poll interval,
  poll on timeout, resume reading) keeps it single-threaded, but urllib gives no clean way
  to resume a read after a timeout — the practical outcome is reconnecting every interval,
  which is the polling we are removing, with extra handshakes.
- **Rewriting the waiter in asyncio** would match the MCP server, but `_run_once`,
  `HubClient` and the whole CLI are synchronous. It is a large change to a shipped,
  fail-silent path for no behaviour the thread does not give.

The thread choice also makes FR-004 and FR-006 nearly free: if the thread cannot connect,
or dies, or connects to a hub that then says nothing, the loop is still a poll loop with a
bounded interval. **The stream can only ever shorten a sleep**, and that is the property
that makes it impossible for this mission to make things worse.

## Charter Check

| Charter rule | Status |
|---|---|
| The hub stays generic and harness-agnostic | Passes — no hub-side change at all (NFR-005) |
| Mail is data, never instruction (ADR 0008) | Passes — the event is a prompt to re-check; `wake_response` still builds the notice from `check_inbox`, and never from event text (FR-003) |
| No deployment specifics in the repo | Passes — no hostname appears; the address comes from config via `events_url()` |
| Client carries no dependency tree | Passes — stdlib only (FR-010, C-004) |
| Regtests and smoke-tests before unit tests | The primary proof is behavioural: a fake stream driving a real waiter, and the existing suite unmodified |

Re-checked after design: no change.

## Phase 0 — What is already known, and what is not

No research spike is needed. Everything this depends on exists and is tested:

- the route `GET /actors/{name}/events` and its per-actor authentication —
  `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`, WP01;
- `SseParser`, including comments, multi-line data, and `\r\n` — WP02;
- `events_url()` / `stream_headers()` on `HubClient` — WP02;
- backoff with full jitter and a settle-based reset — WP02, in `mcp_client.py`.

**The one thing that must be decided during implementation, not now**: whether the
waiter's reconnect logic can reuse the MCP server's backoff helper or needs its own. They
have different lifetimes — the MCP server reconnects for the life of a session, the waiter
only until its wait expires — so the answer may be "reuse the delay function, not the
loop". WP02 settles it in code.

**Two open questions, both answerable by the work rather than before it:**

1. **How long should the poll interval become once a stream is held?** Long enough to be
   worth the change, short enough to catch a silently-dead stream. The plan proposes
   sixty seconds and asks WP02 to justify or change it. It must stay bounded (FR-006).
2. **Does the hub distinguish "no such route" from "temporarily unreachable"?** A 404
   versus a connection error. If it does, the waiter can stop retrying the stream for the
   rest of a wait against an old hub, rather than reconnecting for eight hours. If it does
   not, FR-004 still holds and the cost is a retry loop that never succeeds — wasteful,
   not wrong. WP01 finds out and records the answer.

## Phase 1 — Design

### Shape

```
_wait_for_wake(event, root, poll_interval, wait_timeout, sleep)
  └─ acquire the single-waiter lock            (unchanged, FR-009)
  └─ start the reader thread                   (new; failure here is not an error)
  └─ loop:
       _run_once(event, root)  ──→ exit 2 ? return it   (unchanged, FR-002/FR-003)
       remaining <= 0 ? return 0                        (unchanged)
       sleep(min(interval, remaining))  ← now interruptible by the reader
  └─ stop the reader and close the connection  (new, FR-007)
```

Everything on the left of that diagram is today's code. The mission adds two lines of
lifecycle and changes what `sleep` means.

### The reader

A small object, not a free function, because it owns a connection and a thread and both
have to be closable (FR-007):

- `start()` — opens the stream in a daemon thread; any failure is swallowed and recorded
  as "not streaming", never raised (FR-008);
- `wait(seconds) -> None` — the `Sleeper` the loop is handed; returns early on an arrival;
- `close()` — stops the thread and closes the response.

It signals on `event == "mail"` and ignores every other event type (FR-011). It never
reads the event's payload for content: an arrival means *ask the hub*, and the hub's
answer is what becomes the notice. That is FR-003, and it is also C-002 — the payload is
sender-written data, and giving it a path into a printed notice would be a regression of
the one rule the wake mechanism exists under.

### Testing

- **A driven fake stream.** The reader takes its connection from a factory, so a test
  hands it a fake that yields chosen bytes at chosen moments. No socket, no sleep, no
  flake.
- **The existing wake tests, unmodified.** They inject `sleep` and never mention a stream,
  so they exercise the no-stream path and prove the decision did not move (SC-004). If any
  of them needs editing, that is a signal the change went further than intended.
- **A removal proof for FR-004**: delete the fallback poll and a hub with no event route
  must stop waking at all. If it still wakes, the fallback under test was not the fallback.
- **A removal proof for FR-006**: make the interval unbounded and a stream that connects
  and then says nothing must stop waking.

## Implementation Concern Map

| ID | Concern | Where |
|---|---|---|
| IC-01 | Holding and parsing the stream, and failing silently when it cannot be held | the reader object |
| IC-02 | The waiter's loop: interruptible sleep, bounded interval, lifecycle | `wake.py` `_wait_for_wake` |
| IC-03 | Reconnection while the wait has time left | the reader, possibly reusing `reconnect_delay` |
| IC-04 | The words that describe the wake, which currently say it polls | `doc/`, the CLI help for `--wait` |

## Data model

None. No new persisted state; the watermark and lock files are unchanged in name, format
and meaning.

## Contracts

None new. The client consumes a route the hub already publishes and this mission does not
alter.
