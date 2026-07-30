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

1. ~~**SSE or WebSocket?**~~ **Answered: SSE.** See below.
2. **Does this need to survive a scale-to-zero host?** The public demo suspends when idle. A
   held connection either prevents suspension — changing the cost model — or dies on it,
   making immediacy conditional on the deployment. Worth measuring early; it may decide
   question 1.
3. **Does the MCP server hold the connection, or the CLI?** They are separate processes with
   separate lifetimes. The MCP server lives as long as the agent's session, which is the
   thing that wants waking — but the CLI is where configuration and credentials already are.
4. ~~**What happens to an agent mid-turn?**~~ **Answered by the decision layer** — see
   below. Retained because the documentation consequence is real: Mail cannot reach an agent mid-turn today, and the
   tool descriptions promise exactly that. If this makes interruption possible, **that
   promise changes**, and every agent has been told the opposite. That is a documentation
   change at minimum and possibly a design decision — an interrupt an agent cannot decline
   is a different mailbox from the one described.

## Provenance

Asked by the operator, 2026-07-30, after `v0.32.0`. Read alongside
`live-session-push-01KYCGZ1` (the agent-facing half), issue #8 (wake and notification
observability) and issue #31 (no cheap health probe; `count=0` indistinguishable from
failure).

## Answered (owner, 2026-07-30)

**SSE.** Open question 1 is closed: server-sent events, not WebSocket. The requirement is
one-directional and the client already has an API for everything it wants to say.

**And a decision layer in the client**, between being told and interrupting:

> once alerted, decides how and when to interrupt the agent

### Why this changes the shape rather than adding a box

Without it, "the hub told the client" and "the agent was interrupted" are the same event,
and the interrupt is therefore decided by **whoever sent the message**. With it, arrival and
interruption are separate decisions, and the second one belongs to the client.

That is what makes open question 4 answerable. The promise every agent has been given —
*"mail cannot reach you mid-turn: you see it only when you look"* — becomes:

> **your client decides whether mail reaches you mid-turn**

which is honest, configurable, and still true by default for a client that decides "never".

### The rule this layer exists to enforce

**Priority claimed by a sender is not priority.**

If a message can make itself interrupting — by subject, by a flag, by saying URGENT — then
every message becomes urgent, and the mailbox has handed senders a lever over the recipient's
attention. That is ADR 0008 (*no actor has authority over the mailbox*) arriving at the
client, and it is the failure to design against.

So the decision layer reads:

- **who it is from**, against the recipient's own configuration — a wake is gated on the
  *reader's* trust, not the writer's claim;
- **what else is happening** — mid-turn, idle, or between sessions;
- **what has happened recently** — an agent interrupted five times in a minute has been
  denial-of-serviced by anyone who can send mail.

And it must not read anything the **sender** controls as a priority signal. Subject and
sender are shown so the *agent* can decide what to do; they are not inputs to whether it is
disturbed.

### Where it sits

```
hub ──SSE──▶ client transport ──▶ decision layer ──▶ wake adapter ──▶ agent
             (FR-001..009)        (this addition)    (live-session-push)
```

Three layers, three jobs: **hear**, **decide**, **deliver**. `live-session-push` owns the
third and is unchanged. The hub owns none of them — FR-006 still holds, and the decision
layer is emphatically **client-side**, because a hub that decided when to interrupt agents
would be a hub with authority over them.

### Additional requirements

| ID | Requirement |
|---|---|
| **FR-010** | A **decision layer** sits between the stream and the wake adapter. Being told mail exists and interrupting an agent are separate acts, and the second is a decision. |
| **FR-011** | **Nothing a sender controls may raise its own priority.** No subject keyword, no flag, no field. Wakes are gated on the recipient's configuration — sender identity, not sender assertion. |
| **FR-012** | **Doing nothing is a valid and default-safe outcome.** A client configured to interrupt for nobody behaves exactly as today, and every existing agent keeps the guarantee it was given. |
| **FR-013** | **Interruption is rate-limited.** An agent that can be woken without bound has been handed to whoever sends most, and the mailbox becomes a denial-of-service surface against its own users. |
| **FR-014** | The layer's decisions are **observable** — what arrived, what it chose, and why. An interrupt policy nobody can inspect is one nobody can trust or debug. |
| **FR-015** | The agent-facing description **says what it now does**. Today the tool docs promise mail cannot arrive mid-turn; where a client can interrupt, that text must change, because an agent that believes the old promise will be surprised by the new behaviour. |

### Test matrix additions

| Case | Expected |
|---|---|
| Default configuration | nothing interrupts; behaviour identical to today |
| Message with an alarming subject, sender not trusted to interrupt | **no wake** |
| The same subject from a sender who *is* | wake |
| Twenty messages in a minute | wakes are capped, and the cap is reported |
| Wake declined | the mail is still there, unread, and arrives by the ordinary path |
| Every decision | recorded with its reason |

**FR-011 must be proved by removal**: stand up a sender that claims urgency, confirm no
wake, then remove the guard and watch a subject line move the recipient's attention.
