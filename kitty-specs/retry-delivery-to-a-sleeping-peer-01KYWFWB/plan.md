# Implementation Plan: Retry delivery to a sleeping peer

**Branch**: `kitty/mission-retry-delivery-to-a-sleeping-peer` | **Date**: 2026-07-31
**Spec**: `kitty-specs/retry-delivery-to-a-sleeping-peer-01KYWFWB/spec.md`
**Federation Step 7.** Sketch: `doc/federation-step-7.md`

## Summary

Wrap the existing `RemoteDelivery` collaborator in one that retries. A first attempt still
happens inline; if it fails because the peer was *unreachable*, the delivery is handed to
an in-memory queue that re-attempts with backoff for about five minutes. Everything else in
this plan is a constraint on **what the retry is allowed to reuse** — which is the resolved
inbox, and nothing else.

## Technical Context

**Language/Version**: Python 3.12+ (project floor)
**Primary Dependencies**: none new — `asyncio` only; C-004 forbids a new service
**Storage**: none. The queue is in memory (C-001); outcomes go to the existing audit log
**Testing**: pytest, with three requirements proved by removal (FR-002/005, FR-004, FR-007)
**Project Type**: single package, `src/agent_inbox`
**Performance Goals**: a send returns in one attempt, not the retry window (NFR-002)
**Constraints**: no new dependency; retries must go through `RemoteDelivery.deliver` (C-003)
**Scale/Scope**: one new module, three touched, one test module

## Charter Check

- **Directive 3 (settle a foundation first)** — passes. This completes a shipped
  foundation rather than opening a new surface.
- **ADR 0005 (one API, every client is a client)** — the queue sits below `House`, so the
  console, CLI and MCP all inherit it from one place. No client learns about queueing
  separately.
- **ADR 0008 (no actor has authority)** — unaffected. Nothing a message contains can
  change whether or how it is retried.
- **FR-050, the parent spec's outside-review finding** — **this is the mission that makes
  it live.** Step 6 could not violate it because there was no interval; Step 7 creates the
  interval. See "The one rule" below.

## The one rule

> Authorization is re-derived on every attempt and never carried from queue time.

The guard already exists in the right place, and this plan's job is to **not get between
it and the send**:

```python
# FederatedDelivery.deliver — already correct, unchanged by this mission
settings = await self.mailbox.hub_settings()   # read now
peers    = await self.mailbox.peers()          # read now
await asyncio.to_thread(outbound.deliver, ..., settings=settings, peers=peers)
```

`outbound.deliver` raises `DeliveryRefused` if federation is off or the peer is untrusted.

**So the queue must re-call `RemoteDelivery.deliver` and pass no decision into it** (C-003).
Doing that makes FR-002 and FR-005 structural rather than remembered: a peer that lost
trust while a message waited is refused by code we do not touch.

## The distinction the sketch missed

`DeliveryRefused` and a socket timeout are both exceptions, and treating them alike is the
easy mistake here.

| Failure | Is | Retry? |
|---|---|---|
| `DeliveryRefused` | **our** decision — federation off, peer not trusted | **Never.** Terminal (FR-004) |
| Connection refused, timeout, DNS failure, 5xx | the world | Yes, until the bound |
| 4xx from the peer | the peer rejecting the message | **Never.** Retrying will not change their mind |

Retrying a refusal would be the hub arguing with its own configuration, and would make
FR-005's drain take five minutes instead of happening at once.

## A regression this would otherwise cause

`Sent.reached_nobody` decides whether `api.py` returns an error — its docstring calls a
silent success "the worst failure shape we have".

```python
return bool(self.receipts) and not any(r.delivered for r in self.receipts)
```

A **queued** receipt has `delivered=False`. Left alone, a message that is merely *waiting*
would be reported to the sender as having reached nobody — an outright error for a send
that is very likely to succeed moments later. `reached_nobody` must become false while
anything is still queued.

This is the only place in the existing code where adding a third state changes an answer
that is currently correct, and it is not mentioned in the sketch.

## Phase 0 — research

One question, and it is in the spec: **an attempt that fails after the peer received it.**

Finding: `FederatedDelivery.deliver` builds the activity id as `{public_url}/act/{record.id}`
— derived from the record, therefore **identical across attempts**. A receiver that
de-duplicates on activity id already handles a retried duplicate. What is not yet known is
whether *our own* inbox does; that is a test to write, not a design to choose.

No other unknowns. The storage, the authorization path and the failure taxonomy are all
existing, understood code.

## Phase 1 — design

### New: `RetryingDelivery`

A `RemoteDelivery` that wraps another and adds a queue. It satisfies the same Protocol, so
`House` is unchanged apart from what it does with a failure.

- `resolve` / `actor_uri` — delegate untouched.
- `deliver` — attempt once. On `DeliveryRefused` or 4xx, re-raise (terminal). On an
  unreachable failure, enqueue and raise a distinct `Queued` signal so `House` can mint a
  `queued` receipt rather than a failed one.

Backoff: `2s, 8s, 30s, 2m, 5m` after the inline attempt — six attempts, ~7½ minutes worst
case, which NFR-001 rounds to "about five minutes". Strictly increasing (NFR-004).

**One asyncio task per queued delivery.** Per-peer independence (NFR-003) then costs
nothing to arrange, and at the volumes this hub sees a worker pool would be machinery
protecting against a problem we do not have.

### Lifecycle

`House` is already an async context manager. The queue starts with it and, on close,
**fails everything it still holds** rather than vanishing — FR-008, and the reason C-001 is
acceptable at all.

### Where the outcome is visible

**A gap the spec's SC-005 overstates, corrected here.** Receipts are returned at send time
and are not persisted, so once `House.send` returns, a later transition from `queued` to
`delivered` has nowhere to appear.

Rather than build a receipt store, queue outcomes are written to the **existing audit log**
(already a hub policy). An operator can then answer "did it arrive". **The sender is not
notified** — pushing a later outcome to a client is precisely the
`the-hub-can-tell-a-client-mail-has-arrived` mission, and duplicating it here would build
the second notification path that ADR 0005 exists to prevent.

SC-005 should read "from the hub's audit log" rather than "from the sender's own record".

### Entities

| Entity | Fields |
|---|---|
| `Queued` (signal) | the recipient, so `House` can mint the right receipt |
| queued delivery (internal) | resolved recipient, record, attempt count |
| `Receipt` | gains `queued: bool`; `state` returns the third word |

No schema change, no migration, no contract change to any endpoint. The only externally
visible difference is a third value in a field that already carries words.

## Work, in order

1. `Receipt.queued` + `state`, and **`Sent.reached_nobody` corrected** — the regression above.
2. `RetryingDelivery`: attempt-once, classify the failure, enqueue the retryable.
3. The retry loop: backoff, bound, re-call through the collaborator, terminal on refusal.
4. Lifecycle: start with `House`, fail outstanding on close (FR-008).
5. Audit-log outcomes.
6. Tests, including the three removal proofs and the duplicate-delivery question.

## Open question carried from the spec

**Ambiguous delivery failures.** Recommendation stands: rely on the stable activity id and
verify our own inbox de-duplicates. If it does not, that is a separate defect in the
receiving half, and worth its own issue rather than a compensating hack in the sender.
