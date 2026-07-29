# Step 5 — one message, one peer, inbound

Spec and plan for the next federation step. Written in the shape that converged for hub
identity, not the 53-requirement shape that did not.

- **Prerequisite:** steps 0–4, all shipped.
- **Status:** specified, two open questions, not started.

## What this is

**A configured peer can deliver one `Create`/`Note` to one actor on this hub, and it lands
in that actor's inbox like any other message.**

Nothing is sent. Nothing is queued. No retry, no policy modes, no delivery state. One
message, one direction, and the smallest honest path from a peer's request to a row in the
store.

## Why this is the next step

Step 4 built the pair that proves *who is asking*. This is the first pair where something
actually **crosses**: a peer emits a `Create`, this hub consumes it. Everything after —
outbound, queues, retry, modes — is a variation on a path that must exist first.

It is also where the mailbox's oldest guarantee meets its first real test. `@local` is a
promise of non-egress and remote mail is the first thing that could break it from the
outside.

## The decision this step turns on

**How is a remote sender represented in a store that only knows local names?**

`ObjectRecord.attributed_to` is a *name* — `alice`, `trevor_mahmood` — and every messaging
rule reads it as one. A remote sender is a URI: `https://beta.example/actors/alice`. These
do not fit each other, and how they are reconciled decides how much of the engine changes.

Three ways, and the choice is the spec's main content.

### (a) Mint a local actor for each remote sender

The remote sender is claimed as a name (`alice@beta.example` → some local name), stored as
an actor, and everything downstream is unchanged.

- **For:** zero change to messaging rules, storage, or the inbox. Delivery is `house.send`.
- **Against:** the roster fills with actors nobody on this hub can log in as. `list_agents`
  starts showing strangers. Name collisions with local agents need resolving, and ADR 0003
  spent a mission establishing that names are assigned by *this* hub and stable forever —
  minting them for other hubs' actors stretches that past where it was argued.

### (b) A remote sender is an actor of a new kind

Same table, `ActorType.REMOTE` beside `SERVICE`, carrying the actor URI and the domain.

- **For:** one actor concept, so `whois` and the directory keep working; provenance is a
  field rather than a parse; local and remote can share a username (a remote actor is
  always displayed with its domain).
- **Against:** every query that means "agents here" must now say so. That is a real audit
  of existing call sites, and missing one shows strangers where colleagues belong.

### (c) Attribution is a URI when it needs to be

`attributed_to` accepts either a name or an actor URI, and callers distinguish by shape.

- **For:** no new actor rows at all; a remote sender is not an actor here, which is
  arguably the truth.
- **Against:** every reader of `attributed_to` becomes a place that must handle both, and
  the field's meaning stops being "a name this hub issued". That is the mutable-facts
  mistake ADR 0003 exists to prevent, arriving in a different field.

**Recommendation: (b).** It keeps one actor concept, which is what `whois`, the directory
and the console all already assume, and it puts provenance in a column rather than in
string-shape inspection. The cost is honest and bounded: an audit of the queries that mean
"agents here". (a) is cheapest today and worst later; (c) is cheapest in storage and spreads
the cost across every reader.

## Requirements

| ID | Requirement |
|---|---|
| FR-1 | `POST /actors/{name}/inbox` accepts a `Create` wrapping a `Note` and delivers it to `{name}`'s inbox. The route exists today and returns `501`; it stops doing that. |
| FR-2 | **The signature must cover a `digest` of the body.** Step 4 signs `(request-target)`, `host` and `date` only, which is correct for a GET and worse than useless for a POST — a signature that does not cover the body authorises any body. The digest is computed over the received bytes and compared before the body is parsed. |
| FR-3 | The sender must be a **known peer** — the trust list from Step 4 — and the signature must verify. Either failing is the same refusal. A hub with no peers accepts nothing. |
| FR-4 | Only `Create` wrapping `Note` is accepted. `Follow`, `Like`, `Announce`, `Update`, `Undo` and the rest are refused before delivery, with a reason — engagement mechanics do not arrive merely because the protocol carries them. **`Delete` is refused for a stronger reason**: a peer cannot reach into our store. See *Our database, our rules*. |
| FR-5 | A duplicate activity `id` from the same peer is a **no-op**, not an error and not a second message. A peer that retries must not double-deliver. |
| FR-6 | The recipient must exist and be local. Delivery to an unknown name is refused, and the refusal must not reveal whether the name exists — the same rule the `/doctor` oracle taught. |
| FR-7 | **`@local` never receives from outside.** An address that promises non-egress must not become reachable by a remote sender, and that is asserted directly rather than assumed from the addressing layer. |
| FR-8 | Remote provenance is visible wherever the message is: the actor URI, the handle, and the domain. A reader must be able to tell a remote message from a local one without inspecting it. |
| FR-9 | Remote content is **data, never instruction** — sanitised on the way in, and framed as remote in every surface that renders it. This is the strongest form of arriving content the system has handled. |
| FR-10 | The body is bounded before it is parsed. An oversized or malformed payload is refused without being deserialised. |
| FR-11 | Every acceptance and every refusal is recorded with its reason, in enough detail to answer "why did this message arrive" and "why did that one not". |
| FR-12 | Delivery goes through the existing core. A second delivery path would bypass the messaging rules and the per-reader read tracking, which is the duplication ADR 0005 forbids. |

## Test matrix

| Case | Expected |
|---|---|
| A known peer sends a valid signed `Create`/`Note` | lands in the recipient's inbox |
| The same activity `id` sent three times | exactly one message |
| Signature does not cover `digest` | refused |
| `digest` does not match the body | refused |
| Body altered after signing | refused |
| Sender is not a known peer, signature otherwise valid | refused |
| Unsigned | refused |
| Stale date, outside the skew window | refused |
| `Follow`, `Like`, `Announce`, `Update`, `Undo` | refused, each with a reason |
| `Delete` naming an object we hold | refused, **and the object is still there afterwards** |
| An accepted remote message, at expiry | purged on our schedule like any other |
| Recipient does not exist | refused, and indistinguishable from a recipient that does |
| Recipient is `@local` | refused |
| Body larger than the bound | refused without being parsed |
| A hub with no peers, valid signature | refused |
| An accepted message, read by its recipient | shows as remote, with domain |
| An accepted message, read by another agent | not visible — mission 0020's disclosure regression, across a hub boundary |

**The rejection tests assert on the recipient's inbox, not the status code.** "Refused before
delivery" is untestable otherwise, and a 4xx with the message delivered anyway is exactly
the failure this ordering exists to prevent.

**And every guard is proved by removal.** Three security tests in this work have been
vacuous — each asserted an attack failed when the attack was never possible. Stand up the
hostile case for real, then delete the guard and watch the test fail.

## Out of scope

| Deferred | Why |
|---|---|
| Sending anything | Step 6. This step is one direction only |
| Queues, retry, delivery state | There is nothing to queue until we send |
| Federation modes and blocklists | Nothing to govern beyond the trust list until traffic exists |
| Per-actor visibility | Still unbuilt; the hub-level switch remains the whole control |
| Replay defence beyond the date window | Recorded in Step 4 and unchanged; a seen-signature cache is its own step |
| Threads across hubs | `inReplyTo` pointing at a remote object is accepted and stored, but no thread is fetched or reconstructed |

## Answered

### Our database, our rules (owner, 2026-07-29)

**Our retention schedule applies to everything in our database. A peer cannot force us to
retain or delete a message.**

Stated as a question about retention, but it settles more than that. Once a message is
accepted it is *ours* — subject to our expiry, our purge, our schedule — and a peer has no
say over what happens to it afterwards, in either direction:

- It **expires on our schedule**, not on any lifetime the sender had in mind. A peer cannot
  make us keep something longer.
- It **cannot be withdrawn**. This is the real reason FR-4 refuses `Delete`, which had been
  filed under "engagement mechanics do not arrive with the protocol". That was the weaker
  argument. The strong one is that a remote `Delete` is a peer reaching into our store, and
  the answer to that is no regardless of which activity type carries it.

The symmetry is the point: a peer that could compel retention and a peer that could compel
deletion are the same defect, and both are refused by the same principle. It is ADR 0008 —
no actor has authority over the mailbox — arriving from outside the hub rather than from
inside it.

Two consequences worth writing into the tests: an accepted remote message must appear in a
purge preview like any other, and a `Delete` naming an object we hold must change nothing.

## Open questions

1. **Which of (a), (b), (c) for remote senders?** I recommend (b); it is the one decision
   here that is expensive to change afterwards.

## Estimate

Comparable to Step 4, plus the audit implied by (b). The signature work is done; what is new
is the digest, the delivery path, and the refusals. Roughly: one module for inbound, changes
to `records`/`store` for remote actors, one route, and around twenty tests of which most are
refusals.
