# Tasks: the hub can tell a client mail has arrived

**Mission**: `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)
**Branch**: `kitty/mission-the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1` · **Merges into**: `main`
**Related**: [pre-tasks-review.md](pre-tasks-review.md) — its C1 and C2 are subtasks here, as it asked.

## What the plan settled, and what it left to measure

The spec closed every open question. The plan's Phase 0 left two things to measure, and one
of them is already answered:

- **What does Litestar give us?** — **Answered without writing anything.** Litestar 2.24
  ships `ServerSentEvent`, which takes an async iterable of `ServerSentEventMessage`. No new
  runtime dependency, and no need to hand-roll the wire format. What it does *not* give is
  the fan-out: the stream is fed by a send happening on **another request**, so a small
  in-process registry sits between. That registry is T001.
- **Does a held connection survive the deployments in use?** — **Cannot be measured before
  the route exists.** There is no streaming endpoint on either hub to hold open. So it is
  not a blocker before WP01; it is the thing WP01 proves *after* it ships (T008), with the
  route deployed and `curl` holding it. Measuring it first would mean building the route to
  measure the route.

The review's A1 ("event within a second" is the only number and nothing measures it) is
settled the same way, by the same task.

## The emit point is already there

`House.send` (`src/agent_inbox/house.py:190`) is the **single** place mail becomes stored
fact — local sends and federated arrivals both pass through it, and it already computes
`sent.local_recipients`, which is exactly the list of people to notify. Emitting anywhere
else means either missing federated mail or emitting it twice.

| WP | Goal | Depends on | Shippable alone |
|---|---|---|---|
| WP01 | The hub emits: registry, route, and the call in `House.send` | — | **shipped as v0.39.0**, proved on both hubs |
| WP02 | The MCP server holds the stream, and reconnects | WP01 | yes — hearing without acting on it |
| WP03 | The decision layer, rate limit, and the docs that must stop promising the old thing | WP02 | yes, and it is the one that changes behaviour |

Three ships, in that order. WP01 and WP02 are inert by design: nothing an agent experiences
changes until WP03, which is the point at which the tool descriptions become wrong (FR-015)
and are fixed in the same package.

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | The connection registry: per-actor, bounded, counted | WP01 | |
| T002 | `GET /actors/{name}/events`, authenticated as exactly that actor | WP01 | |
| T003 | Emit from `House.send` — best-effort, after the write, cannot fail a send | WP01 | |
| T004 | The disclosure tests: wrong identity, no identity, somebody else's mail | WP01 | |
| T005 | The content tests: no body (FR-002), actionable (FR-008), mail unchanged (FR-009) | WP01 | |
| T006 | The count and the cap (FR-007) | WP01 | [P] |
| T007 | Directive 4 — outside model review before WP01 closes | WP01 | |
| T008 | **After deploying**: does a held stream survive both hubs, and how late is the event | WP01 | |
| T009 | `HubClient` can consume the stream | WP02 | |
| T010 | The MCP server holds it, with backoff that survives a hub restart | WP02 | |
| T011 | Tests: a drop loses nothing, two clients same identity, reconnect | WP02 | |
| T012 | Directive 4 — outside model review before WP02 closes | WP02 | |
| T013 | The decision layer: default-deny, gated on sender identity | WP03 | |
| T014 | The rate limit (FR-013) | WP03 | |
| T015 | Every decision recorded with its reason (FR-014) | WP03 | [P] |
| T016 | FR-011 proved by removal: a sender claiming urgency moves nothing | WP03 | |
| T017 | The documentation stops promising what is no longer true (FR-015) | WP03 | |
| T018 | Directive 4 — outside model review before WP03 closes | WP03 | |

---

## WP01 — The hub emits

**Goal**: a client that holds `GET /actors/{name}/events` open is told, within a second, that
mail arrived for it — sender, subject, id, never the body — and nothing else about the hub
changes.
**Independent test**: hold the stream with `curl -N`, send mail from another terminal, watch
the event arrive. Kill the stream and everything else still works identically.

- [x] T001 The connection registry: per-actor, bounded, counted (WP01)
- [x] T002 `GET /actors/{name}/events`, authenticated as exactly that actor (WP01)
- [x] T003 Emit from `House.send` — best-effort, after the write, cannot fail a send (WP01)
- [x] T004 The disclosure tests: wrong identity, no identity, somebody else's mail (WP01)
- [x] T005 The content tests: no body, actionable, mail unchanged (WP01)
- [x] T006 The count and the cap (FR-007) (WP01)
- [x] T007 Directive 4 — outside model review before WP01 closes (WP01)
- [~] T008 After deploying: survival and latency — **house hub done, demo hub blocked** (WP01)

**Risks**: T003 is where a mistake is expensive. A notification that can raise is a
notification that can fail a send, and a hub that refuses mail because nobody could be told
about it has inverted its own priorities. The emit must be unable to propagate anything.

**Prompt**: [tasks/WP01-the-hub-emits.md](tasks/WP01-the-hub-emits.md)

---

## WP02 — The client holds the stream

**Goal**: the MCP server opens the stream when the agent's session starts, holds it, and
reconnects when it drops — without a reconnect storm when the hub restarts and drops every
client at once.
**Independent test**: start an MCP server, restart the hub, confirm the stream comes back
without either process spinning.

- [ ] T009 `HubClient` can consume the stream (WP02)
- [ ] T010 The MCP server holds it, with backoff that survives a hub restart (WP02)
- [ ] T011 Tests: a drop loses nothing, two clients same identity, reconnect (WP02)
- [ ] T012 Directive 4 — outside model review before WP02 closes (WP02)

**Risks**: the reconnect storm is real and is in the plan for a reason — every client
disconnects at the same instant on every release, which is several times a day here. Backoff
belongs in the first version, not after it bites.

**Prompt**: [tasks/WP02-the-client-holds-it.md](tasks/WP02-the-client-holds-it.md)

---

## WP03 — The decision layer, and the promise that changes

**Goal**: between hearing and interrupting there is a decision, it is the recipient's, it is
default-deny, it is rate-limited, and it is inspectable. And the tool descriptions stop
promising something that is no longer unconditionally true.

- [ ] T013 The decision layer: default-deny, gated on sender identity (WP03)
- [ ] T014 The rate limit (FR-013) (WP03)
- [ ] T015 Every decision recorded with its reason (FR-014) (WP03)
- [ ] T016 FR-011 proved by removal: a sender claiming urgency moves nothing (WP03)
- [ ] T017 The documentation stops promising what is no longer true (FR-015) (WP03)
- [ ] T018 Directive 4 — outside model review before WP03 closes (WP03)

**Risks**: this is where the mailbox could hand senders a lever over recipients' attention.
FR-011 is not a nicety — if a subject line can raise its own priority, every subject line
will, and ADR 0008 has been defeated at the last layer rather than the first.

**Prompt**: [tasks/WP03-the-decision-layer.md](tasks/WP03-the-decision-layer.md)

## Requirement coverage

| FR | Where |
|---|---|
| FR-001 stream exists | T002 |
| FR-002 no body | T005 |
| FR-003 polling stays the floor | T005 (mail unchanged), and nothing in WP01–03 touches `check_inbox` |
| FR-004 one identity | T002, T004 |
| FR-005 a drop loses nothing | T010, T011 |
| FR-006 harness-agnostic | T003 (the hub's whole contribution is one sentence), T013 (the decision is client-side) |
| FR-007 bounded, observable | T006 |
| FR-008 actionable without a second round trip | T005 — the review's C1 |
| FR-009 mail is unchanged | T005 — the review's C2 |
| FR-010 the decision layer exists | T013 |
| FR-011 no sender-controlled priority | T016, proved by removal |
| FR-012 doing nothing is the default | T013 |
| FR-013 rate-limited | T014 |
| FR-014 observable decisions | T015 |
| FR-015 the docs say what it does | T017 |
