# Step 7 — a delivery queue, so a sleeping peer is not a lost message

- **Prerequisite:** step 6, shipped.
- **Status:** specified, not started. Deferred deliberately — see below.

## Why this is its own step rather than part of step 6

Step 6 delivers synchronously and does not retry. A peer that is asleep, restarting or
briefly unreachable means the message **fails**, is reported as failed, and is not sent
again. The sender's own copy survives and the sender is told.

That is a real limitation and it was shipped anyway, on purpose. Federation that works
between two hubs that are both up is useful now; federation that survives a peer being
down is better, and waiting for it would have delayed everything else behind it.

**The queue is the difference between "both hubs are up" and "both hubs exist".** For two
laptops that sleep, that difference is most of the value — which is exactly why it wants
field data from step 6 rather than a design written before anyone had tried it.

## What this is

**A message to an unreachable peer is retried until it arrives or is given up on, and the
sender can see which.**

## FR-050 becomes live here

The parent spec's FR-050 — the finding from the very first outside review — says outbound
authorization must be re-derived at send time and never carried from queue time. Step 6
could not violate it, because there was no queue.

Step 7 creates the interval the finding is about. The guard already exists in the right
place: `outbound.deliver` reads settings and peers *itself*, immediately before the
request, and refuses if federation is off or the peer is not trusted. **A queue must call
that function and must not pass a decision into it.**

The failure this prevents: a peer that stalls a retry could otherwise make us send after
federation was switched off, or after that peer lost our trust.

## Requirements

| ID | Requirement |
|---|---|
| FR-1 | A delivery that fails is retried, with backoff, up to a bound. |
| FR-2 | **Authorization is re-derived on every attempt**, inside `outbound.deliver`, from configuration read at that moment. Never carried from when the message was queued. See above. |
| FR-3 | A queued delivery has a state the sender can see. `Receipt.state` already returns a word rather than a boolean *for this reason* — `queued` joins `delivered` and `failed` without breaking a client. |
| FR-4 | Retries stop. A message that cannot be delivered is given up on, and says so — an unbounded queue is a slow leak that presents as working. |
| FR-5 | A peer that has lost our trust, or a hub that has stopped federating, drains rather than delivers. Its queued messages are not sent. |
| FR-6 | The queue survives a restart, or it is honest that it does not. A queue that silently empties on deploy is worse than no queue, because the sender was told `queued`. |
| FR-7 | Per-peer ordering and concurrency are bounded, so one unreachable hub cannot starve the rest. |
| FR-8 | `@local` never enters the queue. The non-egress guarantee holds by construction in `split_recipients` today; a queue must not become a second route around it. |

## What step 6 already got right for this

- **The check is in the right place.** `outbound.deliver` re-derives authorization itself,
  so a queue in front of it cannot get between the decision and the send.
- **The report shape anticipates it.** `Receipt.state` is a word, so `queued` is additive.
- **The local copy is already independent of delivery.** It is persisted before any
  delivery is attempted, so a queue changes when a message arrives elsewhere, never
  whether the sender keeps their own.

## A case that may already work — measure before building for it

Raised while specifying `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`, and it
narrows what this step is for.

A peer that is **down** needs the queue; nothing else will do. But a peer merely
**suspended** on a wake-on-request host is different: the delivery *is* the request that
wakes it, so it is not unreachable, only slow to answer the first time.

The failure mode there is a **timeout**, not a refusal. `outbound.deliver` allows 15
seconds and resolution has a 20-second deadline. If a cold peer answers inside that,
federating with a sleeping hub already works and needs nothing from this step. If it does
not, first contact fails and a retry succeeds — which is precisely what the queue is for.

**Measure it against a real scale-to-zero host before assuming either way.** The answer
changes how much of this step is load-bearing.

## Open questions

1. **Where does the queue live?** A table in the existing store is the obvious answer and
   keeps deployment a single file. An external broker would be a new dependency for a
   tool whose whole shape is "one process, one file".
2. **What does "given up on" mean to the reader?** A failed receipt after a day is
   different from one after ten seconds, and the sender who was told `queued` has moved on.
3. **Does a retry re-resolve the recipient?** WebFinger answers change. Re-resolving is
   more correct and more expensive; caching is faster and can deliver to an actor that has
   moved.

## Out of scope

| Deferred | Why |
|---|---|
| Modes and blocklists | Nothing to govern beyond the trust list until there is traffic |
| Threads spanning hubs | `inReplyTo` crosses; nothing is fetched or reconstructed |
| Per-actor visibility | Still the hub-level switch; unchanged by queueing |
