# Spec — The waiter listens instead of polling

- Mission: `wake-without-polling-01KZ23TA`
- Follows: `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1` (which built the stream)

## What this is

Two halves of push already exist in this repository and do not touch each other.

The **waiter** works. `agent-inbox wake-check --wait`, installed as an `asyncRewake` Stop
hook, keeps an idle Claude Code session reachable for up to eight hours and wakes it when
mail arrives. It has a single-waiter lock, an announce-once watermark, and a fail-silent
wrapper. It is shipped, and it is the only thing on this project that has ever woken an
agent without a human relaying the message.

It gets there by **asking the hub every five seconds** whether anything has arrived
(`wake.py`, `_wait_for_wake`). Over a full wait that is 5,760 requests to learn something
the hub knew the instant it happened, and it costs up to five seconds of latency on every
message.

The **stream** also works. The hub emits a per-actor event the moment mail lands, and
`HubClient` already knows the address (`events_url`) and the credential
(`stream_headers`), and already has an incremental parser for the wire format
(`SseParser`). The MCP server holds that stream today.

This mission connects them: **the waiter holds the stream instead of asking.**

## What this is not

**Not mid-turn interruption.** That is the other thing `no-adapter` refers to, and it is
blocked on a capability the harness does not offer: nothing in MCP lets a server push into
a turn that is already running, and the preceding mission's own research found Channels to
be a gated preview. The decision layer in `interrupt.py` stays exactly as it is, still
recording `no-adapter`, still honest. A wake at the *turn boundary* is what is buildable
today, and it is what this mission makes fast.

**Not the removal of polling.** Polling is the portable floor and stays one. A hub too old
to serve the stream, a proxy that will not hold a connection, a network that drops long
requests — each of those must degrade to today's behaviour, not to silence.

**Not a change to what a wake says.** `wake_response` is a pure function and stays the
sole decision about what the agent is told. The stream changes *when* it is consulted,
never *what* it concludes. Announce-once, the watermark, the sender-and-subject-only
notice, and the untrusted-body rule are all unchanged, and must be provably unchanged.

## User scenarios

1. **Mail arrives during a long wait.** An agent's session is idle with the waiter
   holding the stream. Another agent sends a message. The session wakes within a second,
   with the same notice it would have printed after a poll.
2. **The hub is too old to have the stream.** The waiter asks, is refused, and polls —
   exactly today's behaviour, with nothing printed and nothing broken. This is the normal
   case during a staged rollout, not an error.
3. **The connection is dropped mid-wait.** A proxy times out at ten minutes, or the hub is
   redeployed. The waiter re-establishes, and while it cannot, it polls. A wait that began
   before a deploy still wakes for mail that arrives after it.
4. **Nothing arrives all day.** The wait ends at its timeout having printed nothing, the
   connection is closed, and the lock is released — as today.
5. **The hub is down for the whole wait.** Silence, one attempt per interval, and recovery
   by itself the moment the hub returns. No output, no error, no dead waiter.
6. **An arrival the agent has already been told about.** The stream fires, the watermark
   says it was announced, and nothing is printed. A stream event is a prompt to re-check,
   never an announcement in its own right.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | While waiting, the waiter holds the hub's per-actor event stream, authenticated with the same credential every other call from that client uses. | proposed |
| FR-002 | An arrival on the stream causes the waiter to evaluate the wake immediately, by the same path a poll tick takes. | proposed |
| FR-003 | The wake decision stays `wake_response` alone. Nothing about the stream reaches it; an event carries no text into the notice. | proposed |
| FR-004 | Polling remains, unconditionally, as the floor. A waiter that cannot hold the stream — for any reason, including a hub that has no such route — polls at today's interval and behaves exactly as it does today. | proposed |
| FR-005 | A dropped stream is re-established while the wait has time left, and polling continues throughout, so a drop delays a wake rather than losing one. | proposed |
| FR-006 | With the stream held, the poll interval may lengthen, but it must not become unbounded: a stream believed healthy and silently delivering nothing must still be caught by a poll. | proposed |
| FR-007 | The waiter closes the connection when the wait ends, whether it ends on a wake, on timeout, or on an error. | proposed |
| FR-008 | Every stream failure is silent to the agent — no output, no traceback, and no non-zero exit that Claude Code would read as "keep going". | proposed |
| FR-009 | The single-waiter lock still admits one waiter per project, so a stream connection is held once and not once per turn. | proposed |
| FR-010 | The client acquires no new runtime dependency; the stream is read with the standard library, as every other request already is. | proposed |
| FR-011 | An event of an unknown type is ignored rather than treated as an arrival, so the hub can add one without waking every old client for it. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | A wake is prompt. | With the stream held, arrival to notice is under one second in the test harness, against up to five seconds today. | proposed |
| NFR-002 | A wait is cheap. | One held connection plus a bounded slow poll, in place of ~5,760 requests over eight hours. | proposed |
| NFR-003 | Delivery never depends on push. | Disabling the stream entirely changes latency and request count, never whether the agent learns it has mail. | proposed |
| NFR-004 | A wake never breaks or hangs a turn. | Unchanged from today: any failure prints nothing and exits 0. Proved by the existing wake tests continuing to pass unmodified. | proposed |
| NFR-005 | The hub gains nothing. | No server-side change in this mission; the route and the event already exist and are already tested. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | The hub stays harness-agnostic. Every wake mechanism is client-side. | accepted |
| C-002 | Message bodies are untrusted. A wake carries sender, subject and id — never body text — and the stream must not become a route around that. | accepted |
| C-003 | No blocking tool and no long-poll *tool*. The waiter is a hook subprocess, not a tool call; the agent's control loop is never suspended. | accepted |
| C-004 | Standard library only on the client. | accepted |
| C-005 | No deployment-specific hostnames, IPs, organisation names or secrets in code, docs or tests. | accepted |
| C-006 | No mid-turn interruption is attempted. `interrupt.py` is not modified. | accepted |

## Key entities

- **The waiter** — `wake.py`'s `_wait_for_wake`: the loop that keeps an idle session
  reachable. What this mission changes.
- **The stream** — `GET /actors/{name}/events`, already served, already tested, already
  held by the MCP server. Reused, not rebuilt.
- **`wake_response`** — the pure decision about what an agent is told. Untouched, and its
  untouchedness is itself a requirement.
- **The watermark** — `.agent-mailbox-seen.json`, announce-once. Untouched.

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | An arrival wakes an idle session in under a second, where it took up to five. |
| SC-002 | A waiter against a hub with no event route behaves precisely as today, silently. |
| SC-003 | Turning the stream off changes latency and request count and nothing else — every message still arrives. |
| SC-004 | The existing wake tests pass unmodified, which is what proves the decision did not move. |
| SC-005 | A connection dropped mid-wait costs a delay, not a missed message. |
| SC-006 | No new dependency appears in the client's install. |

## Assumptions

- The hub the waiter talks to is the hub the rest of the client talks to; identity and
  credential come from the existing config, and there is no second configuration.
- Two connections for one actor — the MCP server's and the waiter's — are within the
  per-actor listener cap the preceding mission set, which is 64.
- A hub without the route answers in a way the client can tell apart from a transient
  failure. If it cannot, FR-004 still holds: both look like "cannot stream", and both
  fall back to the poll.

## Out of scope

| Deferred | Why |
|---|---|
| Interrupting a running turn | No harness capability; `interrupt.py` already records this honestly |
| Waking Codex | Its hooks are synchronous — a waiter would hang the session, not wake it (research, 2026-07-27) |
| Waking OpenCode | It has a real endpoint and deserves its own mission, not a branch in this one |
| Removing the poll | It is the floor (FR-004) |
| Any hub-side change | The stream is already built and already tested |

## Edge cases

- **The hub answers the stream but never sends anything**, because a proxy is buffering.
  Caught by the bounded poll (FR-006); this is the case that makes an unbounded interval
  wrong.
- **The wait expires while an event is being handled.** The wake is evaluated and reported
  if it says so; the timeout bounds the wait, not a decision already in flight.
- **The stream returns 401 or 403** because the token was revoked mid-wait.
  Indistinguishable from any other failure by design, and handled the same: fall back,
  stay silent. The poll will fail too, which is correct — a revoked credential should wake
  nobody.
- **Two projects on one machine.** Separate configs, separate locks, separate identities,
  separate connections. Nothing is shared.
- **An arrival for an actor that is not us.** Cannot happen — the route is authenticated as
  exactly that actor, proved by the preceding mission's disclosure tests.
