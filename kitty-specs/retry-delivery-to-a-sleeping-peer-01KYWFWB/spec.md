# Spec — Retry delivery to a sleeping peer

- Mission: `retry-delivery-to-a-sleeping-peer-01KYWFWB`
- Federation **Step 7**. Sketch: `doc/federation-step-7.md`. Prerequisite: Step 6, shipped.
- Status: **specified.** Three prior open questions are answered here; one new one is raised.

## What this is

**A federated message to a peer that is briefly unreachable is retried until it arrives or
is given up on, and the sender can see which.**

Today federation delivers once. A peer that is asleep, restarting or momentarily offline
makes the send **fail** — reported honestly, but gone.

## Why now, and why this is not hypothetical

Step 6 was shipped knowing this. What changed is that we now run a peer that is asleep
most of the time.

- **The public demo suspends when idle.** A Fly machine scaled to zero takes seconds to
  wake. The ordinary case for a message to it is therefore *a peer that is coming up*,
  which today is indistinguishable from one that is gone.
- **Deploys restart hubs.** We deploy on every release.
- **Laptop hubs sleep.** The original motivating case.

So the queue is not a refinement of federation between our two hubs — it is a
**precondition for federation between them being usable at all**. Without it, the common
case fails.

## Domain language

| Term | Means | Not to be confused with |
|---|---|---|
| **Unreachable** | The peer could not be contacted: connection refused, timeout, DNS failure, or a 5xx. A condition of the world, and it may pass. | Refused |
| **Refused** | *We* declined to send: federation is off, or the peer is not trusted. A decision, made by us, and retrying cannot change it. | Unreachable |
| **Queued** | Accepted for retry; not yet delivered anywhere. | Delivered |
| **Given up** | The retry bound is spent. Terminal, and reported as `failed`. | Queued |

**The unreachable/refused distinction is the central one in this spec** and did not appear
in the sketch. It decides both correctness and safety: see FR-004 and FR-005.

## User scenarios

### Primary — the peer is merely asleep

1. An agent on our hub sends to `atlas@sleepy.example`.
2. The first delivery attempt fails: the peer is waking up.
3. The receipt says **`queued`**, not `failed`.
4. Attempts continue with backoff. The peer wakes; the message is delivered.
5. The sender's record shows **`delivered`** without anyone having done anything.

### Exception — the peer never wakes

Same up to step 4. The bound is spent, the message is marked **`failed`**, and the reason
says the peer was unreachable for the whole window — not merely that one attempt failed.

### Exception — trust is withdrawn while a message waits

A message is queued for a peer. Before the next attempt, the operator removes that peer or
switches federation off. **The next attempt refuses rather than delivers**, and the message
is failed. This is the outbound-authorization case, and the reason the queue may never carry a decision.

### Exception — the hub restarts

The queue is in memory (see C-001). Anything waiting is lost. The sender was told `queued`,
so **that promise must be visibly withdrawn**, not silently abandoned — see FR-008.

## Requirements

### Functional

| ID | Requirement | Status |
|---|---|---|
| **FR-001** | A delivery that fails because the peer was **unreachable** is retried with backoff, rather than failing the send. | Specified |
| **FR-002** | **Authorization is re-derived on every attempt**, from configuration read at that moment. Never carried from when the message was queued. This is the outbound-authorization finding from the parent federation spec's first outside review. | Specified |
| **FR-003** | `Receipt.state` reports **`queued`** while a message is waiting, joining `delivered` and `failed`. The property is already a word rather than a boolean for exactly this reason, so no client breaks. | Specified |
| **FR-004** | **A refusal is terminal and is never retried.** Federation being off, or a peer not being trusted, is a decision — retrying it cannot change the answer, wastes attempts, and would read as the hub arguing with its own configuration. | Specified |
| **FR-005** | A peer that loses trust, or a hub that stops federating, **drains rather than delivers**: queued messages for it are failed at their next attempt, by FR-004 above, because the authorization check happens inside the attempt. | Specified |
| **FR-006** | Retries stop. A message that cannot be delivered within the bound is given up on and reported `failed`, with a reason distinguishing "unreachable for the whole window" from "refused". | Specified |
| **FR-007** | **`@local` never enters the queue.** The non-egress guarantee holds by construction in `split_recipients` today; the queue must not become a second route around it. | Specified |
| **FR-008** | Because the queue does not survive a restart, that is **disclosed, not discovered**. Two halves, both required: **(a)** a `queued` receipt carries the disclosure in its detail, so a reader learns it from the receipt itself; **(b)** a hub shutting down fails what it is still holding rather than letting the last thing the sender heard remain a promise nobody is keeping. | Specified |
| **FR-009** | A local recipient's copy is unaffected by any of this. It is stored before delivery is attempted, so queueing changes when a message arrives elsewhere — never whether the sender keeps their own. | Specified |

### Non-functional

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| **NFR-001** | The retry window is bounded and short enough to be honest about an in-memory queue. | Give up **within 5 minutes**, across ~6 attempts with increasing backoff. A ceiling the schedule must fit under, not a figure to round to. | Specified |
| **NFR-002** | A send whose recipients are all remote must not block the caller for the retry window. The first attempt happens inline; retries do not. | Caller returns in **one attempt — currently up to 15s**, the outbound timeout. Stated rather than left to be discovered: 15s inside a single agent tool call is a real cost. See issue #34. | Specified |
| **NFR-003** | One unreachable peer must not delay delivery to a reachable one. | Queued deliveries to distinct peers make progress independently. | Specified |
| **NFR-004** | A single message must not be attempted repeatedly in parallel. | Backoff is strictly increasing, and **each queued message** is in flight at most once at a time. **Deliberately per-message, not per-peer**: several messages to one sleeping peer do retry concurrently. Chosen 2026-07-31 for simplicity, accepting that a struggling peer may see one attempt per waiting message. | Specified |

### Constraints

| ID | Constraint | Status |
|---|---|---|
| **C-001** | **The queue is in memory** and does not survive a restart. Chosen deliberately as the smallest first slice; permitted by the sketch's durability clause ("survives a restart, *or is honest that it does not*"), which makes FR-008 load-bearing rather than cosmetic. | Accepted |
| **C-002** | **A retry reuses the inbox resolved at queue time** and does not re-run WebFinger. Within a ≈5-minute window an actor will not have moved, and re-resolving would multiply traffic against a peer that is already failing. **Not to be confused with FR-002** — resolution is cached; authorization is not. Revisit if the bound ever grows to hours. | Accepted |
| **C-003** | Retries must go through the existing `RemoteDelivery.deliver` collaborator, never to `outbound.deliver` directly. That is what makes FR-002 structural rather than remembered. | Accepted |
| **C-004** | No new runtime dependency and no new deployed service. The hub stays one process. | Accepted |

## Key entities

| Entity | Is | Notes |
|---|---|---|
| **Queued delivery** | One message awaiting one recipient | Holds the resolved recipient, the record, an attempt count, and when the next attempt is due |
| **Receipt** | What the sender is told per remote recipient | Existing; gains the `queued` state |

## Success criteria

| ID | Criterion |
|---|---|
| **SC-001** | A message sent to a peer that is asleep and wakes within the window arrives, with no human action. |
| **SC-002** | A sender is never told a message was delivered when it was not, and never told it failed while it is still being tried. |
| **SC-003** | Switching federation off, or removing a peer, stops queued mail to it from being sent — verifiable by making the change while a message is queued. |
| **SC-004** | Sending to one unreachable peer does not delay a message to a reachable one. |
| **SC-005** | An operator can tell, from the hub's audit log, which of *arrived*, *still trying*, and *gave up* happened. Not from the sender's own record: receipts are returned at send time and not persisted, so a later transition has nowhere else to appear. Notifying the sender is a separate mission. |

## What must be proved by removal, not by passing

Three requirements have tests that pass trivially if the behaviour is absent, and this
project has already shipped one vacuous oracle. Each guard must be removed and the test
watched failing:

- **FR-002 / FR-005** — "a message queued before trust was withdrawn is not delivered"
  passes if the retry never fires at all.
- **FR-004** — "a refusal is not retried" passes if nothing is ever retried.
- **FR-007** — "`@local` is not queued" passes if the queue is never reached.

## Assumptions

1. A peer waking from suspend answers within the retry window. Fly cold start is seconds;
   the window is minutes.
2. Delivery is idempotent enough at the receiving end that a retry after an ambiguous
   failure is safer than a lost message. **See the open question.**
3. Message volume is low enough that an unbounded in-memory queue is not a memory risk
   within a 5-minute window. Revisit if a hub is ever addressed at volume.

## Open question

**What happens when an attempt fails *after* the peer received it?** A timeout on a POST
that in fact succeeded is indistinguishable, from our side, from one that never arrived.
Retrying delivers the message twice; not retrying loses it.

The sketch did not raise this and it is the one genuinely unresolved risk here. Options:
retry anyway and accept rare duplicates; make the activity id stable so a well-behaved
receiver de-duplicates; or treat an ambiguous failure as terminal. **Recommendation: rely
on the stable activity id** — `outbound` already builds `{public_url}/act/{record.id}`,
which is derived from the record and therefore identical across attempts, so a receiver
that de-duplicates on activity id already handles this. Worth confirming our own inbox
does.

## Out of scope

| Deferred | Why |
|---|---|
| A durable queue | C-001. A later slice, once the shape is known from use |
| Per-peer health and circuit-breaking | Needs traffic before it can be tuned |
| Re-resolving a moved actor | C-002; only matters for a long window |
| Modes and blocklists | Nothing to govern beyond the trust list until there is traffic |
| Threads spanning hubs | `inReplyTo` crosses; nothing is fetched or reconstructed |
| Client-to-hub retry | Its own issue — **#34**, raised alongside this |
