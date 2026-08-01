---
work_package_id: WP02
title: The client holds the stream
dependencies:
- WP01
requirement_refs:
- FR-001
- FR-003
- FR-005
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T009
- T010
- T011
- T012
phase: Phase 2 - The client holds it
agent: python-pedro
history:
- at: '2026-08-01T20:55:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/mcp_client.py
create_intent:
- tests/test_events_client.py
execution_mode: code_change
owned_files:
- src/agent_inbox/mcp_client.py
- src/agent_inbox/client.py
- tests/test_events_client.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP02 – The client holds the stream

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer` · **Agent/tool**: `python-pedro`

---

## Objective

The MCP server opens the stream when the agent's session starts, holds it for as long as the
session lasts, and reconnects when it drops — without stampeding the hub when a release
disconnects every client at the same instant.

Nothing an agent experiences changes in this WP. Hearing is not interrupting; that is WP03.

## Context you need before you start

**The holder is forced, and the direction is forced.** The spec records both as constraints
rather than preferences, because a constraint that reads as a preference is one somebody
later simplifies away:

- The **MCP server** holds it, because the CLI is invoked per command and exits. The MCP
  server lives as long as the agent's session, which is the thing that wants waking.
- The connection is **client-initiated**, because the MCP client may be behind NAT. The hub
  cannot reach it, there may be no route, and there is certainly no address to rely on. This
  also rules out any future "the hub calls a webhook" shortcut.

**Consequence, and it is worth stating out loud in the code:** no session, no connection, no
wake. That is correct — there is nobody to interrupt — but it means the connection count
WP01 exposes measures *running sessions*, not agents that exist.

**Transport.** `HubClient` (`src/agent_inbox/client.py:658`) is synchronous urllib, which is
right for request/response and wrong for holding a stream inside an async MCP server.
`httpx` is **already in the `clients` extra** alongside `mcp[cli]`, so the MCP server can
hold the stream with `httpx.AsyncClient.stream` and no new dependency. The hub image carries
neither, which is correct and deliberate (ADR 0009) — this is client-side code.

**`wake.py` is the thing this eventually replaces.** Its `asyncRewake` waiter polls every
five seconds for up to eight hours. That poll loop is the floor FR-003 keeps supported; it
is not the thing to delete here. Leave it working.

## Subtasks

### T009 — `HubClient` can consume the stream

A way to read the stream that matches how the rest of the client is written, and that parses
SSE properly rather than assuming one event per line — `data:` continuation lines, comment
lines (the keep-alive from WP01 arrives as one), and blank-line event boundaries are all part
of the format, and a naive `for line in response` will mis-parse the first keep-alive it
sees.

Keep parsing separate from I/O. A pure function from a chunk of text to a list of events is
testable without a socket, and that is what T011 needs.

### T010 — The MCP server holds it

In `mcp_client.py`, open the stream when the server starts and hold it for the process's
life.

- **It must not delay startup and must not break it.** A hub that is down, a hub too old to
  have the route, a network that is not there: each of these is a client that runs exactly
  as it does today, with polling as its floor. Failure to connect is not an error the agent
  should ever see.
- **Reconnect with backoff, from the first version.** The plan names reconnect storms as a
  risk for a concrete reason: this hub is redeployed several times a day, and every release
  drops every client at the same instant. Exponential backoff with a cap, and jitter — the
  jitter is the part that actually prevents the stampede, and the part most likely to be
  left out.
- **A 404 is not a retryable failure.** A hub without the route will never grow one during
  this process's life. Stop, log once, poll as before.
- Events go nowhere yet. Hand them to a seam WP03 will fill — a callback that defaults to
  doing nothing. Resist building the decision layer here; it has its own requirements and
  its own removal proof.

### T011 — The tests

- **A drop loses nothing** (FR-005): mail that arrives while the client is disconnected is
  still there, unread, by the ordinary path. This is the requirement that makes the whole
  design safe, and it is the cheapest to test.
- **Two clients, same identity**: both are told, and neither consumes anything. Reading is
  still `read_message` and still per-recipient.
- **Reconnect**: kill the stream server-side, confirm the client comes back, and confirm it
  backs off rather than spinning. Assert the *delays*, not just that it eventually
  reconnected — a client that reconnects instantly in a tight loop also passes a test that
  only checks it reconnected.
- **A client that only polls is unaffected** (FR-003).

### T012 — Directive 4

Outside model review before this WP closes:

```
perl -e 'alarm 300; exec @ARGV' codex exec "<one narrow question>" < /dev/null
```

One narrow question. The best candidate: whether the reconnect loop can spin, leak a task,
or keep the process alive after the MCP server has been asked to stop.

## Definition of Done

- The four gates pass.
- An MCP server against a WP01 hub holds the stream and reconnects across a hub restart.
- An MCP server against a hub **without** the route runs exactly as it does today.
- Nothing an agent sees has changed.
- Released and deployed to **both** hubs, proved with `verify-deployment`, before WP03
  starts.

## Reviewer guidance

The failure modes worth hunting: a reconnect loop that spins; a background task that keeps
the process alive at shutdown; a parse that breaks on the first keep-alive comment; and any
path where a hub being unreachable becomes something the agent is bothered with.
