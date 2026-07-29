# Step 6 — one message, one peer, outbound

- **Prerequisite:** steps 0–5, all shipped.
- **Status:** **the sending path is built and proved between two real hubs.** Not yet wired to `house.send`, so an agent cannot address a remote actor yet — that is the last piece.

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

## Out of scope

| Deferred | To |
|---|---|
| Queue, retry, backoff, per-peer concurrency | Step 7 — and FR-050 becomes live there |
| Delivery state in the UI | with the queue that produces states worth showing |
| Modes and blocklists | when there is traffic to govern |
| Threads spanning hubs | `inReplyTo` crosses; nothing is fetched or reconstructed |
