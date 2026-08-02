# Tasks — The waiter listens instead of polling

Mission: `wake-without-polling-01KZ23TA` · Branch: `main` ·
Spec: `spec.md` · Plan: `plan.md`

## What the plan settled

The waiter is synchronous, so it cannot await a stream. A daemon thread holds the
connection and sets a `threading.Event`; the loop's sleep — already an injected `Sleeper`
— becomes `event.wait(seconds)`. **The stream can only ever shorten a sleep.** Everything
below follows from that, including why the removal proofs are the ones they are.

## What is already built, and is not rebuilt here

The route, its per-actor authentication, `SseParser`, `events_url()`, `stream_headers()`
and a jittered reconnect delay all shipped with
`the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`. This mission consumes them. It
makes **no hub-side change at all**.

## Subtask index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | A reader that holds the stream and signals on arrival | WP01 | |
| T002 | Failing to hold it is not an error — every path silent | WP01 | |
| T003 | Only `mail` signals; every other event type is ignored | WP01 | [P] |
| T004 | Reconnect while the wait has time left | WP01 | |
| T005 | Does the hub tell "no such route" apart from "unreachable"? | WP01 | [P] |
| T006 | The loop sleeps on the reader, and the reader is closed | WP02 | |
| T007 | The interval lengthens, and stays bounded | WP02 | |
| T008 | The existing wake tests pass unmodified | WP02 | |
| T009 | Removal proof for FR-004: delete the poll, an old hub stops waking | WP02 | |
| T010 | Removal proof for FR-006: unbound the interval, a silent stream stops waking | WP02 | |
| T011 | Directive 4 — outside model review before the mission closes | WP02 | |
| T012 | The prose stops saying the waiter polls | WP03 | |
| T013 | `--wait`'s CLI help says what it now does | WP03 | [P] |

---

## WP01 — The reader

**Goal**: an object that holds the stream, signals arrivals, and cannot break anything by
failing. It owns a connection and a thread, so it must be closable.

**Independent test**: driven by a fake connection, it signals on a `mail` frame, stays
silent on anything else, and swallows every failure.

- [x] T001 A reader that holds the stream and signals on arrival (WP01)
- [x] T002 Failing to hold it is not an error — every path silent (WP01)
- [x] T003 Only `mail` signals; every other event type is ignored (WP01)
- [x] T004 Reconnect while the wait has time left (WP01)
- [x] T005 Does the hub tell "no such route" apart from "unreachable"? (WP01)

**Sketch**: `start()` opens the connection in a daemon thread and parses with `SseParser`;
`wait(seconds)` is the `Sleeper` the loop will be handed; `close()` stops the thread and
closes the response. The connection comes from a factory so a test can supply a fake.

**Risks**: the reader must never read event *payload* text into anything printable. The
payload is sender-written, and a path from it into a notice would undo the one rule the
wake mechanism exists under (C-002). An arrival means "ask the hub", nothing more.

**Dependencies**: none.

---

## WP02 — The waiter listens

**Goal**: `_wait_for_wake` sleeps on the reader instead of the clock, with a bounded
interval and a closed connection at the end. Nothing else about it moves.

**Independent test**: an arrival on a fake stream wakes the loop without waiting out the
interval; with no stream, the loop is byte-for-byte today's behaviour.

- [ ] T006 The loop sleeps on the reader, and the reader is closed (WP02)
- [ ] T007 The interval lengthens, and stays bounded (WP02)
- [ ] T008 The existing wake tests pass unmodified (WP02)
- [ ] T009 Removal proof for FR-004: delete the poll, an old hub stops waking (WP02)
- [ ] T010 Removal proof for FR-006: unbound the interval, a silent stream stops waking (WP02)
- [ ] T011 Directive 4 — outside model review before the mission closes (WP02)

**Sketch**: start the reader after the lock is taken, hand its `wait` in as the sleeper,
close it in the `finally` that already releases the lock.

**Risks**: T008 is the one that matters. The existing wake tests inject `sleep` and never
mention a stream; if any of them needs editing to pass, the change went further than
intended and that is the signal to stop and look, not to edit the test.

**Dependencies**: WP01.

---

## WP03 — The words follow

**Goal**: the documentation and the CLI help stop describing a poll loop, because it is no
longer one.

**Independent test**: nothing user-facing says the waiter polls for mail, except where it
correctly says polling is the floor.

- [ ] T012 The prose stops saying the waiter polls (WP03)
- [ ] T013 `--wait`'s CLI help says what it now does (WP03)

**Sketch**: `wake.py`'s module docstring, `cli.py`'s `--wait` help text, and whichever of
`doc/` describes the hook. The honest sentence is "holds the hub's event stream, and polls
underneath it", not "no longer polls" — the floor is still there and saying otherwise
would be the same overclaiming this mission's spec calls out elsewhere.

**Dependencies**: WP02. The prose cannot be corrected before the thing it describes.

---

## MVP scope

**WP01 + WP02 are the feature**, and neither ships alone: a reader nothing consumes is
dead code, and a loop with no reader is today's code. WP03 is small and immediate — the
module docstring becomes false the moment WP02 lands, so it is not deferrable either.

## Parallelisation

None worth having. Three packages, one lane, each depending on the last; the whole change
is one file plus its tests.

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 | T001 |
| FR-002 | T006 |
| FR-003 | T001, T003 |
| FR-004 | T006, T008, T009 |
| FR-005 | T004 |
| FR-006 | T007, T010 |
| FR-007 | T006 |
| FR-008 | T002 |
| FR-009 | T006 |
| FR-010 | T001 |
| FR-011 | T003 |
| NFR-001 | T006 |
| NFR-002 | T007 |
| NFR-003 | T009 |
| NFR-004 | T002, T008 |
| NFR-005 | *nothing to do — no hub-side change exists to make* |
