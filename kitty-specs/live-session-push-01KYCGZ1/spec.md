# Spec — Push mail into a live session

> **RETIRED 2026-08-01 — superseded by `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1`.**
>
> Both missions describe the same feature: getting mail to an agent the moment it arrives
> rather than when it next looks. The successor was written after the transport decision
> (server-sent events, not WebSocket) and after the client-side decision layer was agreed,
> so it is the one being planned. Nothing below is work; it is kept for its statement of
> the problem, which is the better one — see the paragraph immediately following.

## What this is

Agents are pull-only: they see mail only when they look. So today a human relays "go check
your inbox" — the exact hand-carrying this project exists to end. This mission gets a
message to an agent **the moment it arrives**, without the agent polling and without a human
nudging it.

Anthropic shipped a mechanism for precisely this — **Channels**: an MCP server that pushes
an event into a *running* Claude Code session, so the message lands in the session already
open rather than spawning a fresh one or waiting to be polled. That is the ideal, and it is
the primary path. But Channels are a gated research preview with real constraints (below),
so the mission's **first deliverable is a decision, evidenced**: are Channels usable in this
environment? If yes, build on them; if no, fall back to the already-proven wake hook. Either
way the outcome is the same for the agent, and two rules hold regardless.

**Two rules that shape everything** (from the 0017 brief):

1. **The hub stays harness-agnostic.** It stores mail and answers "what is unread"; *every*
   wake mechanism — Channel, hook, or a future Codex equivalent — is a **client-side
   adapter**. No harness-specific concept enters the server. A harness with no push at all
   must still work by polling.
2. **Message bodies are untrusted input.** A mailbox any agent can write to, delivered into a
   live session, is a prompt-injection vector — Anthropic's own warning: *"an ungated channel
   is a prompt injection vector… gate on the sender's identity."* So a wake carries **who and
   what** (sender, subject, id), frames any text as quoted data, and prefers a notification
   over dumping the body — the agent chooses to fetch.

## Not this

The tempting shortcut — a blocking `check_mailbox` that holds the turn until mail arrives —
was cancelled in mission 0003 and independently confirmed wrong by the competitive survey
(postal-mcp shipped it; its author reports Claude Code "doesn't return to the mailbox
easily"). A wake must be genuinely out-of-band; it must never suspend the agent's control
loop.

## Delivery, and its fallback

- **Primary — Channels.** Where reachable, a local adapter bridges the hub to Claude Code's
  channel protocol: a new message becomes a channel event in the live session. No polling.
- **Fallback — the wake hook.** Where Channels are not reachable, the proven approach (a
  per-session local poller that wakes even an idle session) reaches the same outcome by
  polling `unread`. Kept until Channels are demonstrated working here.
- **Baseline — polling, always.** `check_inbox` remains the portable floor for every client
  and every harness; push is an accelerator layered on top, never a replacement.

The adapter is a **client-side CLI mode** reading the same `agent-mailbox.toml` for identity
(one install, one config, one identity — it builds on the CLI, not a second tool).

## User scenarios & testing

1. **Mail arrives while the agent is working (Channels available).** Another agent sends a
   message; within seconds it surfaces in the recipient's live Claude Code session as "you
   have mail from `jed_smith`: 'flaky tests'" — no human relay, no poll. The agent calls
   `check_inbox` to read the body.
2. **Mail arrives, Channels unavailable.** The fallback wakes the session to the same effect
   — the agent learns it has mail and fetches it. Graceful degradation, same outcome.
3. **No adapter configured at all.** The agent still receives every message by polling
   `check_inbox` when it is next active. Nothing is push-only.
4. **Session is closed when mail arrives.** The wake is dropped silently (no error); the
   message persists in the mailbox and is seen on the agent's next check.
5. **A sender embeds "ignore your instructions and…" in a subject or body.** The wake
   presents it as quoted data attributed to the sender, never as an instruction; the agent
   decides whether to fetch it.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The hub answers "what is unread for me" cheaply enough to poll frequently (it already has `check_inbox`/unread; this mission formalises that as the wake baseline). | proposed |
| FR-002 | A local, client-side adapter watches the hub for one agent and, on new mail, delivers a wake into that agent's Claude Code session. | proposed |
| FR-003 | Where Anthropic Channels are reachable, the adapter delivers the wake as a channel event into the already-open session, without polling. | proposed |
| FR-004 | Where Channels are not reachable, the adapter falls back to the proven wake hook (poller + idle-session wake), reaching the same outcome. | proposed |
| FR-005 | A wake carries **metadata** — sender, subject, message id — and frames any included text as quoted, attributed data; it does not present a message body as instructions. | proposed |
| FR-006 | A wake is gated on the sender's **authenticated identity**; it cannot be used to inject instructions into another agent's session anonymously. | proposed |
| FR-007 | Delivery by wake does **not** consume the message — it stays unread until the agent reads it. The mailbox remains the durable record. | proposed |
| FR-008 | When the target session is closed or absent, a wake is dropped silently (no error); the message persists and is seen on the next poll. | proposed |
| FR-009 | The adapter installs and uninstalls via the client CLI, reading `agent-mailbox.toml` for identity; config edits merge (not clobber) and are idempotent. | proposed |
| FR-010 | The mission records an **evidenced decision** on whether Channels are usable in this environment (allowlist, auth, plan, stdio-vs-hosted-HTTP), before building on them. | proposed |
| FR-011 | Every wake mechanism is a client-side adapter; the hub gains no code that names Channels, hooks, or any harness. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | The hub stays harness-agnostic. | A source check: hub/engine modules reference neither "channel" nor "hook" nor any harness name; the wake lives only in client code. | proposed |
| NFR-002 | Polling is the portable floor. | An agent with no wake adapter configured receives all mail via `check_inbox`; disabling push changes latency, never delivery. | proposed |
| NFR-003 | A wake never blocks the agent's control loop. | No blocking/long-poll tool is introduced; the agent is never suspended waiting for mail (mission 0003). | proposed |
| NFR-004 | A wake never breaks or hangs a session. | Adapter failures (hub down, unconfigured, session closed) are silent and non-fatal; the message is still poll-readable afterwards. | proposed |
| NFR-005 | The unread poll is cheap. | One indexed lookup returning a small count/list; safe to call on a short interval. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | The hub gains no harness-specific code (charter: generic, releasable infrastructure). | accepted |
| C-002 | No blocking / long-poll wake (mission 0003; survey-confirmed). | accepted |
| C-003 | No server-push channel *from the hub* (SSE/webhooks) in this mission — the wake is client-side; hub-initiated push is a later, federation-adjacent concern. | accepted |
| C-004 | Message bodies are untrusted; a wake frames them as quoted data and prefers metadata over body. | accepted |
| C-005 | Channels are a gated research preview — allowlist, claude.ai/Console auth (not Bedrock/Vertex/Foundry), stdio-only — so availability is environment-dependent and must be evaluated before any build on them. | accepted |
| C-006 | The built mechanism targets Claude Code; other harnesses (Codex, Gemini) get polling plus a documented adapter path, not a built adapter here. | accepted |
| C-007 | No deployment-specific hostnames, IPs, or secrets in the repo (charter). | accepted |

## Key entities

- **Wake adapter** — a client-side process (a CLI mode) that watches the hub for one agent
  and delivers wakes; holds no messaging logic, reads `agent-mailbox.toml` for identity.
- **Wake event** — a notification carrying the sender's authenticated identity, the subject,
  and the message id. Not the body.
- **Unread state** (existing) — what `check_inbox`/unread already expose; the polled baseline
  the wake accelerates.

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | With the adapter running and Channels available, a message reaches the recipient's live session within seconds — no human relay, no agent poll. |
| SC-002 | With Channels unavailable, the fallback wakes the session to the same effect — proving graceful degradation. |
| SC-003 | A wake never delivers a body as an instruction: the agent receives sender + subject + id and fetches the body itself. |
| SC-004 | An agent with no adapter configured still receives every message by polling — nothing is push-only. |
| SC-005 | Closing the session loses no mail — every message is still readable on the next check. |
| SC-006 | The hub contains no code that names Channels, hooks, or a harness (harness-agnostic, verified). |
| SC-007 | A documented, evidenced decision exists on whether Channels are usable in this environment. |

## Assumptions

- Channels availability depends on the operator's Anthropic plan, an allowlist, and
  claude.ai/Console auth; the plan's research spike determines it for this environment.
- The adapter runs on the agent's machine as a local CLI mode (building on mission 0014),
  reading the existing `agent-mailbox.toml` identity.
- The client authenticates to the hub as it does today (device token / identity header,
  per the authentication mission); this mission does not change auth.

## Out of scope (non-goals)

- Server-initiated push from the hub (SSE, webhooks).
- Any blocking or long-poll delivery.
- Built wake adapters for Codex or Gemini (a documented path only).
- Replacing `check_inbox` polling — it stays the portable baseline.
- Retiring the wake hook before Channels are demonstrated working here.

## Edge cases

- **Channels available but the session is closed** → the event is dropped silently; the
  mailbox persists it for the next poll.
- **Two agents on one machine** → identity comes from each agent's config; likely one
  adapter per agent (a cost the plan weighs).
- **Hub unreachable** → the adapter is silent and non-fatal; polling resumes delivering when
  the hub returns.
- **A malicious sender embeds injection text** → framed as untrusted, sender-attributed
  data; the wake is gated on sender identity; the agent chooses whether to fetch.
- **Duplicate wakes for one message** → deduped by message id, announced once.
