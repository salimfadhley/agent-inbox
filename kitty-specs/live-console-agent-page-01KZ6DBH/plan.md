# Implementation Plan: A live console — the hub working, and each agent's own page

**Branch**: `main` | **Date**: 2026-08-04 | **Spec**: `kitty-specs/live-console-agent-page-01KZ6DBH/spec.md`

## Summary

Generalise the arrival stream the hub already serves per actor into a hub-wide one, add
the two read routes the console needs and does not have, and then build one feed
component and mount it in two pages. The console holds a single upstream connection and
re-emits it on its own origin, so the browser only ever talks to the console and
`connect-src 'self'` stands unchanged.

**This ships in two parts**, because the first is coherent when running without the
second: the hub API is useful to any client and provable by `verify-deployment`, while the
console depends on it. Charter — "the unit that ships is whatever is coherent when
running".

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: none new. Litestar (`ServerSentEvent`, `ServerSentEventMessage`)
and `asyncio` server-side, both already used at `api.py:989`; the console's existing
stdlib `HubClient` and `SseParser` for the upstream leg; vanilla ES for the browser, with
no build step and no CDN.
**Storage**: SQLite, unchanged. One new read path — a sent-side query beside
`Mailbox.observe_mailbox` — and one new read of the existing `auth_token_use` table. No
schema change.
**Testing**: pytest. Litestar's test client for the routes; a driven fake stream for the
relay, so no test depends on a socket or on wall-clock timing; rendered-HTML assertions
made against the *page* rather than a helper — a console test that exercised a helper
instead of the rendered page could not tell a working guard from a missing call, and that
has happened in this repository before.
**Target Platform**: the hub container, and the console sidecar beside it on a different
origin.
**Project Type**: single package, `src/agent_inbox/`.
**Performance Goals**: arrival to visible row under one second; ten viewers producing one
hub listener; the sent-side query adding no store scan beyond the one `observe_mailbox`
already performs.
**Constraints**: `/observe/*` takes no caller and consumes nothing; subjects never bodies;
no polling; no new dependency; CSP unweakened.
**Scale/Scope**: `notify.py`, `api.py`, `mailbox.py`, `house.py`, `client.py` and
`console.py`, plus one new static asset. Roughly six files, in two shippable halves.

## The design decisions

### 1. Hub-wide fan-out: a second subscriber kind, not a pseudo-actor

`Listeners` keys queues by actor and `announce(actor, arrival)` walks that key. A hub-wide
feed needs every arrival regardless of actor.

**Chosen: an explicit set of hub-wide queues alongside the per-actor map**, fed by the same
`announce` call.

Rejected: registering a reserved actor name (`"*"`, `"__all__"`) as the subscriber key. It
needs no new code, which is its only virtue — and it puts a value into the actor namespace
that is not an actor, where `count_for`, `by_actor` and `listening` would each report it as
one. A name that is not a name is the kind of thing this project finds two months later.

Capacity is accounted the same way, and the register-inside-the-generator fix is preserved
verbatim: registering above the generator leaked a slot whenever the response was never
iterated, and copying the older shape must not reintroduce it.

### 2. The event carries no more than the per-actor one

`Arrival.as_event()` already yields id, sender, recipients, subject and time. The hub-wide
feed reuses it unchanged rather than defining a second wire shape.

**Direction is not a property of the event.** It is a property of the viewer: the same
message is "sent" on one agent's page and "received" on another's. So direction is computed
where it is rendered, from `attributed_to` against the page's subject, and never baked into
the wire. That is what lets one event serve the hub-wide feed and both halves of an agent
page.

### 3. The observed outbox mirrors its inbound twin, deliberately

`GET /observe/outbox/{name}` — same guard, same `Collection` shape, same "consumes
nothing", implemented as `Mailbox.observe_outbox` beside `observe_mailbox`, filtering on
`attributed_to`.

`observe_mailbox` loads every object and filters in Python. The sent-side query does the
same and is written next to it so the shared cost is visible in one place. NFR-006 makes
this a recorded ceiling rather than a later discovery; making it cheaper is a separate
mission that would change both.

### 4. The relay: the console holds one connection, the browser talks only to the console

The console and the API are different origins. A browser `EventSource` pointed straight at
the API needs CORS plus cross-origin credentials, and would make every viewer a hub
listener.

**Chosen: the console holds one upstream SSE connection and re-emits to its own
subscribers.** N viewers cost the hub one listener (NFR-001), the CSP does not change, and
the console stays a plain client that decides nothing (ADR 0005).

The cost is stated rather than hidden: the console becomes a point of failure for liveness.
It is already a point of failure for the pages themselves, so this adds no new class of
outage — but the relay owns reconnect, and its state must be *visible* to the browser
rather than inferred. That is FR-016 and FR-017, and it is why they are requirements
rather than polish.

### 5. Liveness is asserted by the head row, and it is the thing most likely to go wrong

A quiet hub and a dead connection render identically in any naive implementation. So the
head row is a state machine with three named states — **open**, **reconnecting**, **lost** —
driven by the relay, never inferred from "no events lately". The browser must not be
allowed to conclude health from silence, because silence is what both states look like.

This is the requirement the mission turns on, and its test must be a removal proof: kill
the connection, assert the page reports the fault, restore it, assert it recovers — and
check the paired positive, that a merely *idle* feed still reports open.

### 6. Absorbing `/mailbox/{name}` without breaking links

The agent page becomes the destination for every agent link. `/mailbox/{name}` keeps
answering — existing links and anyone's bookmark already point at it — and becomes a link
*from* the page rather than a second front door. `_mbox_link` is the single place every
table builds those links, so this is one function, and its callers stay as they are.

## Phase 0 — research

No open unknowns requiring investigation. The three that would have been research
questions were settled by reading the code during spec:

- whether a hub-wide feed discloses anything new — **no**, a signed-in operator can already
  read every mailbox individually;
- whether an observed outbox exists — **no**, `/actors/{name}/outbox` is a POST for sending;
- whether `auth_token_use` had landed — **yes**, `auth/store.py:257`.

`research.md` is therefore not generated. Recorded deliberately, because a missing artifact
should be a decision rather than an oversight.

## Phase 1 — design

### New API surface

| Route | Shape | Guard |
|---|---|---|
| `GET /observe/events` | SSE; `mail` events carrying `Arrival.as_event()`, plus keep-alive comments | `guard_enforce` |
| `GET /observe/recent` | `Collection` of the last N arrivals, newest last | `guard_enforce` |
| `GET /observe/outbox/{name}` | `Collection`, mirroring `/observe/mailbox/{name}` | `guard_enforce` |

`/observe/recent` is bounded at the API, not by the caller — an unbounded "recent" is a
whole-store dump wearing a small name. The snapshot exists so a page can fill before its
first event and after a reconnect, and both need the same small window.

### Console surface

| Path | What |
|---|---|
| `/realtime` | The hub-wide tab |
| `/agent/{name}` | The agent page; every `_mbox_link` points here |
| `/mailbox/{name}` | Unchanged, reachable from the agent page |
| `/events` (console origin) | The relay's re-emission — what the browser subscribes to |

### The feed component

One module, mounted twice: rows, the direction rail, the decaying wash, the self-ageing
clock, the head-row state machine, the reconnect. The agent page adds filter pills and
computes direction; the realtime tab does neither. Written once — building it twice is the
reason these two issues are one mission.

### The agent page's two panels

**Known to the hub** — address, joined, message counts, `lastSeen`, `listeningBy`, and the
token that admitted it (`auth_token_use`, agent-first). **Says of itself** — engine, model,
host, project, root, role, visibly marked unverified. An agent with no profile renders as
*nothing declared* (FR-021), not as empty rows implying facts were sought and found absent.

## Charter check

| Rule | How this complies |
|---|---|
| One core (ADR 0005) | The console reaches the hub only over HTTP and decides nothing about messaging. The relay forwards; it does not interpret. |
| Looking does not consume | Every new route is `/observe/*`, takes no caller, and NFR-003 asserts unread counts are unchanged after watching. |
| No actor has authority (ADR 0008) | Nothing rendered acts. Profile facts are labelled as claims. |
| Generic only | No deployment-specific host, address or organisation anywhere; the guard added under #42 runs in CI and has already caught one. |
| Establish the premise | FR-016's test is a removal proof with its paired positive, because a liveness indicator that cannot fail is the exact defect being guarded against. |
| Python floor, no new deps | Nothing added, server or client. |

Re-evaluated after design: no violations, and no exception required.

## Work split

**Ship 1 — the hub can be watched.** `notify.py` hub-wide subscribers, `/observe/events`,
`/observe/recent`, `/observe/outbox/{name}`, and the `Mailbox`/`House` sent-side query.
Coherent alone: any client gains a hub-wide feed and a way to read what an agent sent.

**Ship 2 — the console watches it.** The relay, the feed component, the Realtime tab, the
agent page, the absorption of `/mailbox/{name}`, and `_mbox_link` repointing.

Ship 1 is released and deployed before Ship 2 starts, so Ship 2 develops against a live hub
that already serves what it needs.
