# Tasks — A live console: the hub working, and each agent's own page

- Mission: `live-console-agent-page-01KZ6DBH`
- Spec: `kitty-specs/live-console-agent-page-01KZ6DBH/spec.md`
- Plan: `kitty-specs/live-console-agent-page-01KZ6DBH/plan.md`
- Planning base: `main` · Merge target: `main`

## How this is split

**Two ships.** WP01–WP04 are the hub API, which is coherent when running on its own: any
client gains a hub-wide feed and a way to read what an agent sent. It is released and
deployed before WP05 begins, so the console develops against a live hub that already
serves what it needs.

**Ownership is the constraint that shaped the decomposition.** `api.py` carries all three
new routes and `console.py` carries every page, so each is owned by exactly one work
package — splitting them by concern would give two packages the same file. The relay and
the feed are therefore *new* modules rather than additions to `console.py`, which is the
right shape anyway: the relay is not a page, and the feed is mounted twice.

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | Hub-wide queue set on `Listeners`, beside the per-actor map | WP01 | |
| T002 | `announce_all()` — hub-wide delivery once per message, not once per recipient | WP01 | |
| T003 | Open/close for hub-wide subscribers, with the same capacity accounting | WP01 | |
| T004 | `count_for` / `by_actor` / `listening` must not report a hub-wide subscriber as an actor | WP01 | |
| T005 | Tests, including the removal proof for the fan-out | WP01 | |
| T006 | `Mailbox.observe_outbox`, beside `observe_mailbox`, filtering on `attributed_to` | WP02 | [P] |
| T007 | `House.observe_outbox` delegate | WP01 | |
| T008 | Tests: only what the agent sent, consumes nothing, paired against `observe_mailbox` | WP02 | [P] |
| T009 | `GET /observe/events` — hub-wide SSE, registered inside the generator | WP03 | |
| T010 | `GET /observe/recent` — snapshot, bounded at the API | WP03 | |
| T011 | `GET /observe/outbox/{name}` | WP03 | |
| T012 | Route registration, keep-alives, capacity refusal | WP03 | |
| T013 | Tests: guards, consumes-nothing, the bound is the API's, unknown events | WP03 | |
| T014 | `HubClient.observe_recent()` | WP04 | [P] |
| T015 | `HubClient.observe_outbox(name)` | WP04 | [P] |
| T016 | Hub-wide events URL, reusing the existing stream headers | WP04 | [P] |
| T017 | Client tests | WP04 | [P] |
| T018 | One held upstream SSE connection | WP05 | |
| T019 | Fan-out to console subscribers | WP05 | |
| T020 | The three-state machine: open / reconnecting / lost | WP05 | |
| T021 | Reconnect with backoff | WP05 | |
| T022 | Tests on a driven fake stream — no socket, no wall clock | WP05 | |
| T023 | Two-line rows, direction rail, and direction in words | WP06 | [P] |
| T024 | The decaying wash, honouring `prefers-reduced-motion` | WP06 | [P] |
| T025 | Self-ageing relative times | WP06 | [P] |
| T026 | Head-row rendering, driven by state and never by silence | WP06 | [P] |
| T027 | Same-origin subscription; unknown event types ignored | WP06 | [P] |
| T028 | Filter pills | WP06 | [P] |
| T029 | `/events` on the console origin, fed by the relay | WP07 | |
| T030 | `/realtime` | WP07 | |
| T031 | `/agent/{name}` — identity and the two panels | WP07 | |
| T032 | Which token admitted this agent, from `auth_token_use` | WP07 | |
| T033 | Both directions on one feed, direction computed per viewer | WP07 | |
| T034 | Repoint `_mbox_link`; keep `/mailbox/{name}` and link to it | WP07 | |
| T035 | Tests against the rendered page, plus the nothing-declared case | WP07 | |

---

## Ship 1 — the hub can be watched

### WP01 — Everyone's arrivals, not just one agent's

**Goal**: `Listeners` gains a hub-wide subscriber kind so one connection can see every
arrival. **Priority**: first — WP03's stream route has nothing to serve without it.
**Independent test**: two actors receive mail; a hub-wide subscriber sees both, and each
per-actor subscriber still sees only its own.

- [x] T001 Hub-wide queue set on `Listeners`, beside the per-actor map (WP01)
- [x] T002 `announce_all()` — hub-wide delivery once per message, not once per recipient (WP01)
- [x] T003 Open/close for hub-wide subscribers, with the same capacity accounting (WP01)
- [x] T004 `count_for` / `by_actor` / `listening` must not report a hub-wide subscriber as an actor (WP01)
- [x] T005 Tests, including the removal proof for the fan-out (WP01)
- [x] T007 `House.observe_outbox` delegate (WP01)

**Risks**: the pseudo-actor shortcut is genuinely tempting and is rejected in plan §1 —
review should check no reserved name crept into the actor namespace.

### WP02 — What an agent sent

**Goal**: a sent-side query in storage, mirroring the received-side one.
**Dependencies**: none — parallel with WP01. **Independent test**: an agent that sent two
and received three yields exactly the two.

- [x] T006 `Mailbox.observe_outbox`, beside `observe_mailbox`, filtering on `attributed_to` (WP02)
- [x] T008 Tests: only what the agent sent, consumes nothing, paired against `observe_mailbox` (WP02)

**Risks**: NFR-006 — it inherits the whole-store scan and must not add a second one.

### WP03 — Three routes that take no caller

**Goal**: the hub serves the hub-wide stream, the snapshot, and the observed outbox.
**Dependencies**: WP01, WP02. **Independent test**: each route refuses without a
credential under enforce, and none of them changes an unread count.

- [x] T009 `GET /observe/events` — hub-wide SSE, registered inside the generator (WP03)
- [x] T010 `GET /observe/recent` — snapshot, bounded at the API (WP03)
- [x] T011 `GET /observe/outbox/{name}` (WP03)
- [x] T012 Route registration, keep-alives, capacity refusal (WP03)
- [x] T013 Tests: guards, consumes-nothing, the bound is the API's, unknown events (WP03)

**Risks**: the register-inside-the-generator fix at `api.py:989` leaked a listener slot
when it was written the other way round. Copy the current shape, not the older one.

### WP04 — The client can read them

**Goal**: `HubClient` gains readers for the new routes, so every surface goes through one
core. **Dependencies**: WP03. **Independent test**: each reader round-trips against a
test hub.

- [x] T014 `HubClient.observe_recent()` (WP04)
- [x] T015 `HubClient.observe_outbox(name)` (WP04)
- [x] T016 Hub-wide events URL, reusing the existing stream headers (WP04)
- [x] T017 Client tests (WP04)

**► Ship 1 releases and deploys here, before WP05 starts.**

---

## Ship 2 — the console watches it

### WP05 — One connection, however many people are looking

**Goal**: a relay module holding a single upstream stream and re-emitting to console
subscribers, with its connection state exposed rather than inferred.
**Dependencies**: WP04. **Independent test**: ten subscribers, one upstream connection;
kill it and every subscriber learns.

- [x] T018 One held upstream SSE connection (WP05)
- [x] T019 Fan-out to console subscribers (WP05)
- [x] T020 The three-state machine: open / reconnecting / lost (WP05)
- [x] T021 Reconnect with backoff (WP05)
- [x] T022 Tests on a driven fake stream — no socket, no wall clock (WP05)

**Risks**: this is where FR-016 is either honoured or quietly lost. State must be
published, never deduced from quiet.

### WP06 — The feed, written once

**Goal**: the component both pages mount. **Dependencies**: none in code — it is a static
asset and can be built in parallel with WP05. **Independent test**: fed a scripted event
sequence, it renders rows, ages them, and reports each connection state.

- [x] T023 Two-line rows, direction rail, and direction in words (WP06)
- [x] T024 The decaying wash, honouring `prefers-reduced-motion` (WP06)
- [x] T025 Self-ageing relative times (WP06)
- [x] T026 Head-row rendering, driven by state and never by silence (WP06)
- [x] T027 Same-origin subscription; unknown event types ignored (WP06)
- [x] T028 Filter pills (WP06)

**Risks**: colour must never be the only cue (FR-013); the wash must not become motion a
reduced-motion user cannot escape.

### WP07 — The two pages

**Goal**: `/realtime`, `/agent/{name}`, the absorption of `/mailbox/{name}`, and every
agent link repointed. **Dependencies**: WP05, WP06. **Independent test**: every link that
worked before still works, and an agent with no profile renders as *nothing declared*.

- [x] T029 `/events` on the console origin, fed by the relay (WP07)
- [x] T030 `/realtime` (WP07)
- [x] T031 `/agent/{name}` — identity and the two panels (WP07)
- [x] T032 Which token admitted this agent, from `auth_token_use` (WP07)
- [x] T033 Both directions on one feed, direction computed per viewer (WP07)
- [x] T034 Repoint `_mbox_link`; keep `/mailbox/{name}` and link to it (WP07)
- [x] T035 Tests against the rendered page, plus the nothing-declared case (WP07)

**Risks**: assert against the **rendered page**, not a helper. A console test that
exercised a helper could not tell a working guard from a missing call, and that has
happened in this repository.

---

## MVP

**WP01–WP04 is the MVP and is shippable.** It gives any client a hub-wide feed and the
first way to read what an agent sent, and it can be proved on a deployed hub without a
line of console code.

## Parallel opportunities

- WP01 and WP02 have no dependency on each other.
- WP06 depends on nothing in code and can run alongside WP05.
- WP04's four subtasks are independent of one another.
