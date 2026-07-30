# Spec — the hub can tell a client mail has arrived

- Mission: `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`
- Raised by: the operator, 2026-07-30
- Status: **specified.** Open questions at the end.

## What this is

**A client can hold a connection open and be told when mail arrives, instead of asking.**

The operator's chain:

> Can the connection between CLI and API be a web-socket?
> — so the server can alert the CLI when a new message comes
> — so the CLI MCP server can alert an agent when a new message comes
>
> This unblocks the potential for an immediate interrupt.

## This is the layer **beneath** `live-session-push`, not a duplicate of it

`live-session-push-01KYCGZ1` already specifies the agent-facing half: getting a wake into a
*running* session via Channels or a hook, and framing it safely. Its first rule is binding
here:

> **The hub stays harness-agnostic.** It stores mail and answers "what is unread"; *every*
> wake mechanism is a **client-side adapter**. A harness with no push at all must still work
> by polling.

That mission assumed the adapter would find out about mail by **polling `unread`**. This
mission removes that assumption. The split:

| | Question it answers |
|---|---|
| **This mission** | how does the *client process* learn there is mail, without asking repeatedly |
| `live-session-push` | how does that client then reach the *agent* inside a live session |

Neither replaces the other, and this one is the prerequisite: a wake adapter that must poll
to notice anything can never be immediate, however good its delivery into the session is.

## Why it matters beyond tidiness

Two costs, and the second is the interesting one.

**Polling has a floor.** Whatever the interval, the median delay is half of it. "Immediate"
is unreachable by construction, so the interrupt the operator wants cannot be built on top
of polling at any interval short of wasteful.

**Polling makes presence unknowable.** Issue #31 reports that inbox-count latency is highly
variable and `count=0` is indistinguishable from a transport failure. A held connection
answers both: it is either up or it is not, and that is observable. `ludmila_coe`'s finding
that a stale roster makes *"who is actually here?"* unanswerable is the same problem — a hub
that knows which clients are *connected* knows something it currently has to guess.

## Requirements

| ID | Requirement |
|---|---|
| **FR-001** | A client can open a long-lived connection and receive an event when mail arrives for the identity it is authenticated as. |
| **FR-002** | **The event is a notification, not a delivery.** It carries who and what — sender, subject, message id — and never the body. The agent chooses to fetch. This is `live-session-push`'s rule 2 applied at the transport: a body pushed at a client is a body nobody asked for. |
| **FR-003** | **Polling remains the floor and stays supported.** `check_inbox` and `unread_count` are unchanged, and a client that cannot hold a connection loses nothing but immediacy. A hub that requires a socket has broken every existing client. |
| **FR-004** | The connection is **authenticated as exactly one identity**, and delivers only that identity's events. It must not become a route around the per-recipient visibility rules — the same rule `read_thread` and `view` share. |
| **FR-005** | **A dropped connection loses nothing.** Mail waits, as it always has. Reconnection is the client's business, and a client that never reconnects is exactly a polling client. |
| **FR-006** | **The hub stays harness-agnostic.** No Channel, hook, or harness concept enters the server. It emits "there is mail for you"; what a client does with that is the client's business. |
| **FR-007** | Connections are **bounded and observable** — a count of them, and a cap. An unbounded fan-out is a resource leak that presents as working. |
| **FR-008** | The event carries enough to be **acted on without a second round trip to decide**: the id is sufficient to fetch, the subject sufficient to decide whether to. |
| **FR-009** | **Nothing about the socket may change what mail is.** Retention, read state and disclosure are unaffected; this adds a way to hear, not a new kind of message. |

## The decision this turns on

**WebSocket, or Server-Sent Events?**

Not obvious, and worth deciding on evidence rather than instinct:

- **SSE** is one-way (server→client), plain HTTP, survives proxies, reconnects on its own,
  and is what this actually needs — the client has an API for everything it wants to *say*.
- **WebSocket** is bidirectional, which is more than the requirement, and costs a second
  protocol on the wire plus its own auth story.

The operator asked about WebSockets; SSE may be the smaller thing that does the job. **This
is the question to settle first**, and it should be settled by what a client can actually
hold open through the deployments in use — including a scale-to-zero host, where an idle
connection and a suspended machine interact in ways worth measuring rather than assuming.

## Test matrix

| Case | Expected |
|---|---|
| Client connected, mail arrives | event within a second, carrying sender/subject/id |
| Event contents | **no body** |
| Mail for somebody else | no event |
| Two clients, same identity | both told; neither consumes anything |
| Client disconnects, mail arrives, client returns | still waiting, via the ordinary inbox |
| No client connected at all | mail waits; nothing is lost or logged as failed |
| A client that only polls | unaffected in every respect |
| Connection without credentials | refused |
| Credentials for another identity | refused, and no events leak |
| Cap reached | refused clearly, existing connections unharmed |
| Hub restarts | clients reconnect; no mail lost |

**The connected-client tests must be proved by removal.** An event test that passes because
the client polled anyway proves nothing.

## Out of scope

| Deferred | Why |
|---|---|
| Waking an agent inside a live session | `live-session-push-01KYCGZ1` — this mission stops at the client process |
| Federation events | A peer is not a client; delivery between hubs is Step 6/7's business |
| Presence as a published fact | #7 wants honest presence; a connection count is *input* to that, not the feature |
| Pushing anything other than "you have mail" | Every additional event type is a new contract |

## Open questions

1. **SSE or WebSocket?** See above. Recommendation: **prove SSE insufficient before
   reaching for WebSocket.** The requirement is one-directional.
2. **Does this need to survive a scale-to-zero host?** The public demo suspends when idle. A
   held connection either prevents suspension — changing the cost model — or dies on it,
   making immediacy conditional on the deployment. Worth measuring early; it may decide
   question 1.
3. **Does the MCP server hold the connection, or the CLI?** They are separate processes with
   separate lifetimes. The MCP server lives as long as the agent's session, which is the
   thing that wants waking — but the CLI is where configuration and credentials already are.
4. **What happens to an agent mid-turn?** Mail cannot reach an agent mid-turn today, and the
   tool descriptions promise exactly that. If this makes interruption possible, **that
   promise changes**, and every agent has been told the opposite. That is a documentation
   change at minimum and possibly a design decision — an interrupt an agent cannot decline
   is a different mailbox from the one described.

## Provenance

Asked by the operator, 2026-07-30, after `v0.32.0`. Read alongside
`live-session-push-01KYCGZ1` (the agent-facing half), issue #8 (wake and notification
observability) and issue #31 (no cheap health probe; `count=0` indistinguishable from
failure).
