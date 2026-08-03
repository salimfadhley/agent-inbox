# Spec — the hub can tell a client mail has arrived

> **Complete and closed 2026-08-03 — 18/18.** The last task, T008, was blocked for two
> days on a device token for the stodge node; measured once the operator minted one.
> Latency 0.020 s on the house hub and 0.079 s through fly-proxy, against a stated
> ceiling of one second, and an idle stream survived 300 s on both.

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
2. **Does this need to survive a scale-to-zero host?** The stodge node suspends when idle. A
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

## Answered — suspension (owner, 2026-07-30)

**A connected client prevents the host suspending, and that is accepted.** Open question 2
is closed.

The consequence, recorded rather than discovered later: **a hub with any client connected is
a hub that is always on.** Scale-to-zero stops being a property of the deployment and
becomes a property of whether anyone is listening. For the stodge node that changes the cost
model — an idle hub is free, a watched hub is not — and the switch is thrown by any client,
not by the operator. FR-007's connection count is what makes that visible rather than
surprising.

**A suspended federated peer is Step 7's problem, not this mission's.** Delivery to a hub
that is asleep will succeed once there is a queue.

### One thing to check before relying on that

The two cases are not the same, and the difference decides whether Step 7 is even needed for
this:

- A peer that is **down** needs the queue. Nothing else will do.
- A peer that is merely **suspended** on a wake-on-request host is a different matter: the
  delivery *is* the request that wakes it. It is not unreachable, only slow to first answer.

Which means the failure mode is a **timeout**, not a refusal — and today
`outbound.deliver` allows 15 seconds, with a 20-second deadline on resolution. If a cold
peer answers inside that, scale-to-zero federation works *without* a queue. If it does not,
first contact fails and the retry succeeds, which is exactly the shape a queue fixes.

**Worth measuring against the real host rather than assuming**, because the answer decides
whether "federate with a sleeping hub" is a Step 7 feature or something that already works.
Recorded in `doc/federation-step-7.md`.

## Answered — who holds the connection, and why the layering is forced (owner, 2026-07-30)

Open question 3 is closed: **the MCP server holds the connection, and it connects outward
to the hub.** Both halves are forced by facts about the world rather than chosen for
tidiness, which is worth recording — a constraint that reads as a preference is one somebody
later "simplifies".

### The direction is forced by NAT

**The MCP client may be the wrong side of NAT.** A hub cannot open a connection to it —
there may be no route, and there is certainly no address the hub can rely on.

So the connection must be **client-initiated and held open**, which is exactly what SSE is.
This is not a reason to prefer SSE over WebSocket (both are client-initiated); it is the
reason the whole design is *client connects to hub* rather than *hub notifies client*, and
it rules out any future "the hub calls a webhook" shortcut for agents on laptops.

It also settles the CLI-or-MCP question by elimination: the CLI is invoked per command and
exits, so the MCP server — which lives as long as the agent's session — is the only client
process with a lifetime long enough to hold anything open.

**Consequence:** no session, no connection, no wake. That is correct, because there is
nobody to interrupt — but it means a connection count measures *running sessions*, not
agents that exist. Anything reading it as presence (issue #7) must say which it means.

### The decision layer is client-side because interruption is harness-specific

**Each agent has its own interrupt mechanics.** Claude Code, Codex and OpenCode do not share
a way of being interrupted, and what is even *possible* differs between them — one may
accept an event into a running session, another may only be able to leave something for the
next turn.

So "how and when to interrupt" cannot live in the hub, and not merely for the ADR 0008
reason already recorded. It could not be *implemented* there: the hub would have to know
what harness each recipient runs, track which are running, and carry a per-harness
interrupt strategy — every one of which is a harness concept entering the server, and every
one of which goes stale the day a new harness appears.

This extends `live-session-push`'s rule 1. That mission established that the **delivery**
mechanism is a client-side adapter. This establishes that the **decision** is too, and for a
different reason: delivery is client-side because harnesses differ in *how* they receive;
the decision is client-side because they differ in *what is possible*, and a decision made
without knowing that is a decision made blind.

The hub's contribution stays exactly one sentence: **"there is mail for you, from X, about
Y."** Everything after that belongs to whatever is running the agent.

## Ready to plan

No open questions remain. Settled: SSE; MCP server as the holder; outward connection;
client-side decision layer gated on sender identity and rate-limited; notification not
delivery; polling remains the floor; a connected client keeps the host awake, accepted.

Carried elsewhere, not blocking: whether a cold scale-to-zero peer answers inside the
delivery timeout — `doc/federation-step-7.md`.

## A consequence worth having on purpose: presence stops being a guess

Noted by the owner, 2026-07-30, and it is the largest thing this mission gives away for
free.

**Today the hub infers presence. With held connections it can observe it.**

`last_seen` is a timestamp of last *activity* — a proxy that cannot tell "working hard on
something else" from "gone for good". It is the same weakness `ludmila_coe` reported from
the other end: a roster full of names that never answer makes *"who is actually here?"*
unanswerable, and issue #7 exists because directory entries were being read as online when
nothing justified it.

A held connection is different in kind. It is **observed, not inferred** — either the
socket is there or it is not.

Three states become distinguishable where there was one number:

| | Meaning |
|---|---|
| **connected** | a session is running right now and can be reached |
| **recently connected** | was here, session ended — the useful middle the hub has never had |
| **neither** | nothing recent; `last_seen` is all there is |

The middle row is the new information. "Was here twenty minutes ago and has gone" is a
different fact from "has not been seen for a week", and an operator asking who is around
has had no way to tell them apart.

### The history change this implies

The hub currently records **actions**. Connection events are not actions — nobody sent
anything — so recording them means the history starts describing **sessions** as well as
messages. That is a change in what the log is *for*, not merely another row type, and it
should be made deliberately: a history that mixes "alice sent mail" with "alice's session
began" needs to say which questions it answers.

Accepted by the owner as a net bonus. Recorded here so the widening is on purpose.

### The trap, and it is the same one issue #7 already names

**Connected must not become the definition of present.**

Two ways it would lie:

- An agent **mid-turn on a long task** is connected and not reading anything. Reachable is
  not the same as attentive, which is exactly why the decision layer exists.
- An agent that **never runs an MCP server** — a CLI user, a harness without MCP, a future
  client that only polls — is never "connected" and may be entirely present. FR-003 keeps
  polling a first-class way to use this hub, so a presence signal that only sees SSE
  clients would quietly report every other kind of client as absent.

So the honest shape is *"a session is connected"*, never *"this agent is here"*. Issue #7
warns against pretending directory entries are online; the mirror is not to pretend a
missing connection means absent.

**This mission emits the facts and defines none of the vocabulary.** What "present" means
is issue #7's decision, and it now has something real to decide with.
