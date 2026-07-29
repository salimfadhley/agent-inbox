# Step 5 — one message, one peer, inbound

Spec and plan for the next federation step. Written in the shape that converged for hub
identity, not the 53-requirement shape that did not.

- **Prerequisite:** steps 0–4, all shipped.
- **Status:** specified, **no open questions**, not started.

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

## The decision this step turns on — answered

**How is a remote sender represented in a store that only knows local names?**

Answered by re-reading [ADR 0003](decisions/0003-identity-is-a-surrogate-key.md), which had
already decided it:

> The identifier is a **URI**, matching an ActivityStreams actor `id`.

**The globally unique identifier already exists.** `http://hub.example/actors/alice` is
unique by construction because it contains its origin — the same reason hub names need no
registry. What the *store* keeps is the local part, and `wire.py` derives the URI at render
time from the name. That has worked because every actor has been local.

A remote actor's identifier is the same shape at a different origin:
`https://beta.example/actors/alice`. Not a different kind of thing needing a different key.

So the question was wrongly framed. It asked how to squeeze a remote actor into a
local-name field, when the field was always conceptually a URI and the local part was a
shorthand that only holds while everyone is local. **Remote actors make the URI the thing
that must be stored**, and local actors keep deriving theirs exactly as they do now.

### Why not mint our own identifier for remote actors

Considered and rejected: give every actor, local or remote, an opaque ID of our own, and
display a name.

It is false precision, and the reason is a hard limit rather than a preference. **One hub
key signs for all of its actors** — that is how Step 4 is built and what the fediverse does.
`beta.example` vouches for its whole roster with a single signature, so we cannot tell its
actors apart cryptographically at all. If a peer retires `alice` and issues the name to
somebody else, nothing in any signature changes and **we can never know**.

An identifier we minted would imply a continuity we cannot observe. Our records would look
authoritative about something we are simply taking a peer's word for. Storing the URI the
peer claims — and nothing more — is the honest shape.

**The consequence must be visible, not buried.** A remote actor is a claim by its hub, for
as long as that hub keeps making it. FR-8 already requires the domain be shown; what this
adds is that no surface may present a remote actor as though its identity were something we
verified.

*This reasoning belongs in an ADR of its own once Step 5 lands — it is a limit on what
federated identity can mean here, not a detail of one step.*

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
| FR-12a | A remote actor is stored by its **actor URI**, which is its identifier (ADR 0003). No identifier is minted for it. No surface presents it as an identity this hub verified — it is a claim by its hub, for as long as that hub keeps making it. |
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
| A peer renames an actor and reuses the name | **we cannot detect it** — asserted as a documented limit, not a defect |

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

None.

## Estimate

Comparable to Step 4, plus the audit implied by (b). The signature work is done; what is new
is the digest, the delivery path, and the refusals. Roughly: one module for inbound, changes
to `records`/`store` for remote actors, one route, and around twenty tests of which most are
refusals.
