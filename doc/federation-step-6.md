# Step 6 — one message, one peer, outbound

- **Prerequisite:** steps 0–5, all shipped.
- **Status:** **done.** An agent calls `send` with a remote address and it arrives on the
  other hub, proved end to end against two real servers. **No open questions.**

## What this is

**An agent on this hub can address a message to an actor on a configured peer, and it
arrives.** One message, synchronously, to one peer.

No queue. No retry. No delivery state, no modes, no blocklist. The smallest honest path
from `send` to a row in somebody else's store.

## Why synchronous, and what that means for FR-050

The parent spec's **FR-050** — the finding from the very first outside review — says
outbound authorization must be re-derived at send time and never carried from queue time.
A peer that can stall a retry could otherwise make us send after federation was disabled,
or send as an actor that has since gone `local`.

**That bug cannot exist in this step**, because there is no queue: resolution and delivery
happen in one call, so there is no interval for policy to change in.

That is not a reason to ignore it. It is a reason to put the check **where the queue
cannot later get between it and the send**:

> Authorization is checked inside the function that performs the HTTP request, from
> configuration read at that moment — not by the caller, and not passed in as an argument.

Do it there now and Step 7 can add a queue in front without reopening the hole. Do it in
the caller and Step 7 has to remember, which is exactly how the finding arose.

## Requirements

| ID | Requirement |
|---|---|
| FR-1 | `local_name()` in `addressing.py` widens so a remote address resolves instead of raising. Federation widens *that one function* (parent FR-047); a second address-resolution path is the duplication ADR 0005 forbids, and the module's own docstring says the split exists for this. |
| FR-2 | A recipient is resolved by WebFinger to an actor URI, then to that actor's inbox URL — reusing Step 3's fetching, with its bounds and origin checks. |
| FR-3 | The activity is a `Create` wrapping a `Note`, carrying `to`, and `inReplyTo` when replying. The same shape Step 5 accepts, so the two hubs agree by construction. |
| FR-4 | The request is signed **with a `digest` covering the body**. Step 4's signing already does this when given a body; a POST that omits it authorises any body. |
| FR-5 | **Authorization is re-derived inside the sending function**, from configuration read at that moment: federation enabled, the peer trusted, the scheme permitted. See above. |
| FR-6 | **`@local` never egresses.** The oldest guarantee in the mailbox, and the first step where *we* are the one who could break it. Asserted directly, not inherited from the addressing layer. |
| FR-7 | The local copy is persisted first. A remote failure must not lose the sender's own message — losing local mail because somebody else's server is down is the worst available trade. |
| FR-8 | A failure to deliver is reported to the sender in words, and the local copy still exists. Silence would be indistinguishable from success. |
| FR-9 | Nothing is retried. A failed send stays failed, and says so — retry is Step 7 and pretending otherwise would be a queue nobody designed. |

## Test matrix

Against `tests/federation/test_two_real_hubs.py` — two servers, real sockets, distinct
hostnames — because this is the first step where *we* initiate the connection.

| Case | Expected |
|---|---|
| Send to `alice@beta.localhost`, beta trusts us | arrives in alice's inbox on beta |
| The same, read back on beta | attributed to our actor URI, marked remote |
| Send while our federation is disabled | refused; nothing leaves |
| Send to a hub we do not trust | refused |
| Send to `@local` | refused, and **no request is made** — asserted on the attempt, not the inbox |
| Send to an actor beta does not have | reported to the sender; local copy intact |
| Beta refuses the delivery | reported; local copy intact |
| Beta unreachable | reported; local copy intact |
| Two hubs, neither trusting the other | refused in both directions |

### Learned while building

**Peering is mutual, and the two directions mean different things.** Beta lists alpha so
alpha's signature counts on the way *in*; alpha lists beta because a hub should not send
mail to one its operator never configured. The trust list serves both, and a test that
added the peer on one side only failed — correctly.

**A handle carries no scheme.** `alice@beta.example` implies HTTPS, which is the
fediverse's answer and stays the default. But a deployment that opted into insecure
transport has hubs it can only reach over HTTP, and refusing to try would make the opt-in
useless for the case it exists for. HTTPS is attempted first, so a peer speaking both is
reached securely. Found by the real-socket test attempting TLS against an HTTP hub — the
in-process harness could not have.

**Assert on the attempt, not only the outcome.** Some of these are about *not trying*: a
`@local` send that reaches the network and is then refused has already leaked that the
address exists.

## Answered (owner, 2026-07-30)

Four questions stood between the built sending path and wiring it to `send`. All four are
settled; **Step 6 has no open questions.**

### 1. The wiring lives in `House`, injected

`House(mailbox, policies, deliver=...)` — the same shape `policies` already uses. `send`
stays the single entry point and handles both halves.

The alternative — the API layer splitting and calling `send` for the local half — keeps the
core purer, and was rejected for one reason: it makes `house.send` mean *send locally*, so
any caller not going through the API silently drops remote recipients. That is the
"looks like it worked" shape this project keeps finding.

> **A `House` with no sender injected refuses remote recipients. It never drops them.**

The trap is closed by construction rather than by everyone remembering.

### 2. Delivery is reported per recipient

The send returns the `Note` as now, plus a per-recipient delivery status.

**Reaching nobody is never a success.** That is not a new rule — `api.py` already carries it
for a reply with no recipients, with a comment calling silent success "the worst failure
shape we have". Partial delivery is the genuinely new case, and it is reported as what it
is.

**Chosen for forward-compatibility with Step 7.** The fediverse-normal answer is to accept
the post, return immediately, and deliver asynchronously without telling the client — but
that answer *depends on a queue*, and FR-9 says there is none. The same response shape means
"we'll keep trying" with a queue and "we dropped it" without one. A per-recipient status that
reads `failed` today can read `queued` at Step 7 without breaking a client.

### 3. A remote recipient is stored by its URI — and the renderer is wrong today

`to` holds a local name for a local recipient and the **actor URI** for a remote one. Exactly
the shape `attributed_to` already has, for the ADR 0003 reason the Step 5 spec sets out: the
field was always conceptually a URI, and the local name is a shorthand that holds only while
everyone is local.

**`Renderer` never learned that, and there is a live defect on `main`.**
`Renderer.actor_uri()` prefixes unconditionally, so a message from a remote sender renders as:

```
attributedTo -> http://ourhub.example/actors/https://beta.example/actors/alice
```

The stored record is correct; the rendering is mangled. `test_two_real_hubs.py` asserts on
the record, which is why it passed. Fixing it is part of this step: `actor_uri()` passes
through a value that is already a URI. Answering the question the other way would have added
a second defect pointing the opposite direction instead of removing this one.

*Found by asking what `to` should hold — not by any test.*

### 4. `keyId` names the sending actor

`{base}/actors/alice#main-key`, as built. Unchanged, but now deliberate.

Between our own hubs it makes no difference: `verified_peer` resolves a signature by
**origin**, and every actor document publishes the same hub key. It matters against a real
peer, and not in the direction the honesty argument suggests — receiving implementations
commonly check that the signer and the activity's `actor` agree, to stop one user signing on
another's behalf. A hub-level `keyId` on a `Create` fails that check.

The instance actor is real and has a place — signing *server-level fetches*, which is what
Mastodon's `Application` actor is for. That is a later step, not this one.

**The limit, recorded:** naming the sender implies `alice` holds that key, when the hub does.
One hub key signs for the whole roster — the same limit Step 5 records for remote actors,
seen from our side. It stops being a fiction the day per-actor keys exist.

## What the wiring cost, and what found the one defect

**18 tests, one new module, and one bug that only a real socket could have found.**

`delivery.py` holds the collaborator and the answer shape; `House` gained an injected
`deliver`; `Mailbox.send` gained `remote_to`, which is the exact mirror of the
`remote_sender` widening Step 5 needed — recipients **already resolved** at the federation
boundary and identified by URI, not passed through `local_name` and not looked up on the
roster.

### `RemoteMailbox`, not a new error code

The refusal a house gives when it has no delivery collaborator is the error that already
existed. Its docstring, written before federation did:

> This deployment does not federate, so there is nowhere to send it *yet*. … when
> federation arrives, this case becomes a delivery while that one still fails.

That is this condition exactly. A second code would have been vocabulary churn for
downstream callers to no purpose.

### The defect: `to` now holds two kinds of thing

Decision 3 stores a remote recipient by its actor URI in `record.to`. `Sent.reached_nobody`
asked "did anyone get this?" by checking whether `to` was non-empty — which had been a
faithful question for as long as every entry was a local name that received a row.

It is no longer. A remote recipient that **resolved and then failed delivery** is in `to`
and received nothing. So a send to an untrusted peer — resolution fine, delivery refused —
reported success while reaching nobody. The precise failure shape the whole per-recipient
report exists to prevent, reintroduced by the storage decision made to support it.

`Sent` now carries `local_recipients`, told to it by `House` rather than derived from
`to`.

**Found by the two-hub test, not by the fakes.** The fake collaborator refuses at
*resolution*, so the remote recipient never reaches `to` and `reached_nobody` is right by
accident. Only a peer that resolves and then refuses — which needs two real servers —
produces the state that breaks it. The unit tests were not wrong; they could not reach it.

### Every guard proved by removal

Not by passing. Each was deleted and watched failing first:

| Guard removed | What failed |
|---|---|
| `if remote and self._deliver is None` | both refusal tests |
| the already-a-URI passthrough in `actor_uri` | all three renderer tests |
| `@local` staying local in `split_recipients` | both non-egress tests |

## Out of scope

| Deferred | To |
|---|---|
| Queue, retry, backoff, per-peer concurrency | Step 7 — and FR-050 becomes live there |
| Delivery state in the UI | with the queue that produces states worth showing |
| Modes and blocklists | when there is traffic to govern |
| Threads spanning hubs | `inReplyTo` crosses; nothing is fetched or reconstructed |
