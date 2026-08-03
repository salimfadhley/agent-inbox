# T008 — does a held stream survive, and how late is the event?

The plan's Phase 0 question 1 and the analysis report's A5, measured against a deployed
hub rather than assumed. Run on 2026-08-01 against **v0.39.0**, with both hubs proved by
`verify-deployment` first.

Neither could be measured before WP01 shipped: there was no streaming route on either
deployment to hold open. That is why this is the last subtask of the work package rather
than the first, and why the analysis recorded it as an accepted risk (A3) instead of a
blocker.

## The house hub — measured, and better than the spec asked for

| Question | Answer |
|---|---|
| Does the stream open? | Yes. `200`, `content-type: text/event-stream; charset=utf-8` |
| **Latency, send to event** | **0.020 s** |
| Does the event identify the message? | Yes — the id returned by the send is the id on the wire |
| Does it carry the body? | **No** |
| Does an idle connection survive? | **Yes — still open after 240 s**, with only keep-alive frames crossing |

**The spec's only number is safe.** "An event within a second" was written as an
aspiration with nothing measuring it; the real figure is fifty times under it. It can
stand as a test criterion — the margin is large enough that it will fail on a genuine
regression rather than on a slow afternoon.

Four minutes idle is past every proxy timeout in the ordinary range, so the fifteen-second
keep-alive is doing its job here.

## The stodge node — **measured 2026-08-03**, and it holds

The operator minted a device token, which is what had been missing. Run against
**v0.47.0**, through fly-proxy and its TLS termination — the path that mattered,
since a request from inside the machine would have answered the wrong question.

| Question | Answer |
|---|---|
| Does the stream open? | Yes. `200`, `content-type: text/event-stream; charset=utf-8`, `via: 1.1 fly.io` |
| **Latency, send to event** | **0.079 s** |
| Does the event identify the message? | Yes — the id returned by the send is the id on the wire |
| Does it carry the body? | **No** |
| Does an idle connection survive? | **Yes — still open after 300 s**, with only keep-alive frames crossing |

**Both open questions are closed, and both the way we hoped.**

1. *Does an idle SSE connection survive fly-proxy?* **Yes**, for five minutes of
   silence. Immediacy is not conditional on where a hub is hosted, and WP02's
   reconnect carries exactly the weight it was given rather than more.
2. *Does a held connection prevent the machine suspending?* It stayed up throughout,
   which is the already-accepted consequence — *"a hub with any client connected is a
   hub that is always on"* — now observed rather than assumed.

**The spec's number is safe on both hubs.** 0.079 s through a proxy and a CDN-facing
TLS terminator, against a stated ceiling of one second. Four times the house hub's
0.020 s, which is what a real network costs and is still an order of magnitude
under the criterion.

The probe is `scratchpad/t008_stodge.py` in the session that ran it — deliberately
not committed, since it reads a device token from the environment and belongs to
nobody's repository.

### What the blocker was, kept because it explains the delay


That hub ran `v0.39.0` at the time and enforces authentication. Holding a stream needs an
identity on *that* hub, and there is none available:

- no device token for it in `~/.config`, and none in the private deploy repo;
- no shared token — its only secrets are `AGENT_INBOX_AUTH_MODE` and
  `AGENT_INBOX_SECRET_KEY`;
- `POST /actors` is operator-gated, so a client cannot enrol itself;
- minting a device token needs a console login, which is a human credential.

Running a command inside the machine works (`fly ssh console` reports `agent-inbox
0.39.0`), but that reaches the app on localhost and so answers the *wrong* question:
what is unverified is specifically whether **fly-proxy and its TLS termination** hold a
long-lived streaming response, and a request that never crosses the proxy cannot tell us.

**What this leaves open.** Two things, and only for that deployment:

1. Whether an idle SSE connection survives fly-proxy, or is closed after some interval
   despite the keep-alive. If it is closed, immediacy becomes conditional on where a hub
   is hosted, and the client's reconnect (WP02) carries more weight than planned.
2. Whether a held connection prevents the machine suspending. The owner has already
   **accepted** that it does — *"a hub with any client connected is a hub that is always
   on"* — so this is confirmation of a decision rather than an input to one. The cost
   consequence is real either way and is recorded in the spec.

Neither changes WP01, which is deployed and working. Both are inputs to WP02, whose
backoff and reconnect behaviour is the thing that has to be right if the answer to (1) is
"no".

**To unblock:** a device token for the stodge node, minted by whoever can log into its
console. One value, passed in the environment; nothing about it belongs in this repo.

## How it was measured

`measure_stream.py`, kept out of the repository because it takes a hub URL and a token.
It opens the stream, sends one message to itself, records the interval to the event
landing, and then holds the connection idle reporting what closes it and when.
