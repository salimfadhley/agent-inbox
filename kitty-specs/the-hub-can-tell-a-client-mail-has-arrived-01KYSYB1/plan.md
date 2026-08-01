# Implementation Plan: the hub can tell a client mail has arrived

**Branch**: `kitty/mission-the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1` | **Date**: 2026-07-30
**Spec**: `kitty-specs/the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1/spec.md`

## Summary

An SSE endpoint on the hub, held open by the **MCP server** (the only client process that
lives long enough), feeding a **client-side decision layer** that gates interruption on
sender identity and rate limits. Three layers, three jobs: **hear, decide, deliver** —
delivery being `live-session-push-01KYCGZ1`, which this does not touch.

## Technical Context

**Language/Version**: Python 3.14, as the rest of the codebase since v0.35.0. (This line said
3.12 when the plan was written on 2026-07-30; the floor moved on 2026-08-01 and the charter
requires every statement of it to agree.)
**Primary Dependencies**: Litestar (already present) for SSE; no new runtime dependency expected
**Storage**: none for the stream itself. Connection state is in-memory and per-process — a
connection is not a fact worth surviving a restart, because a dropped client reconnects
**Testing**: pytest; the event tests must be proved by removal, since one that passes
because the client polled anyway proves nothing
**Target Platform**: same hub, same clients; must work behind NAT and through a
TLS-terminating proxy
**Project Type**: single package, `src/agent_inbox`
**Performance Goals**: an event within a second of the send that caused it
**Constraints**: polling stays first-class (FR-003); no body on the wire (FR-002); bounded
connections (FR-007)
**Scale/Scope**: single-digit connections per hub in the deployments in use

## Charter Check

- **ADR 0005 (one API, every client is a client)** — the stream is an API route like any
  other. Nothing about it may become a second way to read mail.
- **ADR 0008 (no actor has authority)** — **the gate that shapes the decision layer.** No
  sender-controlled field may raise its own priority (FR-011).
- **`live-session-push` rule 1 (hub stays harness-agnostic)** — extended here: the hub emits
  one sentence and owns neither the decision nor the delivery.
- **Mission 0020 disclosure protections** — the stream must not become a route around
  per-recipient visibility (FR-004).

## Architecture

```
hub ──SSE──▶ MCP server ──▶ decision layer ──▶ wake adapter ──▶ agent
   (this)     (this, holds)   (this)            (live-session-push)
```

**The direction is forced.** The MCP client may be behind NAT, so the hub cannot reach it;
the connection is client-initiated and held. This also rules out a webhook design later.

**The holder is forced.** The CLI is invoked per command and exits. The MCP server lives as
long as the agent's session, so it is the only candidate.

## Phase 0 — research

Two things to measure rather than assume. Both are cheap and both can change the design, so
they come first.

1. **Does a held SSE connection survive the deployments in use?** Specifically through Fly's
   TLS termination, and what a suspended machine does to an idle stream. The owner has
   accepted that a connection prevents suspension; what is unverified is whether the
   connection *survives* long enough to prevent it.
2. **What does Litestar give us?** It has SSE support; the question is whether its shape fits
   an event source fed by sends happening on other requests, or whether a small pub/sub of
   our own sits between.

No research needed on the decision layer: it is ours, in-process, and answers to nobody.

## Phase 1 — design

### The hub side

- One route, `GET /actors/{name}/events`, authenticated as exactly that actor (FR-004).
- An in-process registry of open connections, keyed by actor. Bounded, counted, and
  exposed (FR-007) — the count is what makes "always on because someone is listening"
  visible rather than a surprise.
- `Mailbox.send` gains a notification point. **It must not be able to fail a send**: a hub
  that refuses mail because nobody could be told about it has inverted its own priorities.
  Emitting is best-effort and after the store write, the same ordering as #33's mark-read.
- The event carries `from`, `subject`, `id` — never the body (FR-002).

### The client side

- The MCP server opens the stream at startup and reconnects on drop (FR-005).
- A **decision layer** between stream and adapter, whose inputs are: the recipient's own
  configuration, what the session is currently doing, and how recently it was interrupted.
  **Never a sender-supplied field** (FR-011).
- Default configuration interrupts for nobody (FR-012), so no existing agent's guarantee
  changes until somebody opts in.

### What must not happen

- **The stream becoming a way to read mail.** It says *that* there is mail; `read_message`
  remains the only thing that consumes.
- **A send failing because an event could not be emitted.**
- **Presence vocabulary.** This emits facts; issue #7 decides what "present" means.

## Phase 2 — work, in order

1. **Measure** (Phase 0). May change 2.
2. **Hub: the event registry and route.** Bounded, per-actor, authenticated.
3. **Hub: emit on send**, best-effort, after the write.
4. **Client: hold the stream** in the MCP server, with reconnect.
5. **Client: the decision layer**, default-deny, rate-limited, observable (FR-014).
6. **Documentation** (FR-015) — the tool descriptions currently promise mail cannot arrive
   mid-turn, and where a client can interrupt, that text is wrong.

Steps 2–3 are usable alone: a hub that emits events with no client holding a stream is
harmless and testable. Steps 4–5 are where the behaviour change lands, and 5 is the one
that needs the removal proof.

## Risks

- **The stream is a new disclosure surface.** Every event is addressed to somebody, and the
  test matrix treats "mail for somebody else produces no event" as a security case.
- **Reconnect storms.** A hub restart disconnects every client at once; backoff belongs in
  the client from the first version, not added after it bites.
- **The decision layer is where a denial-of-service lands.** FR-013's rate limit is not
  politeness — an agent that can be woken without bound has been handed to whoever sends
  most.
- **Scope creep into presence.** The temptation to publish "who is connected" is strong and
  belongs to #7.

## Out of scope

Waking the agent (that is `live-session-push`), federation events, and any second event
type. Every additional event is a new contract.
