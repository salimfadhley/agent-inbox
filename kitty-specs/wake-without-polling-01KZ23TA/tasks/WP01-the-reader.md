---
work_package_id: WP01
title: The reader
dependencies: []
requirement_refs:
- FR-001
- FR-003
- FR-005
- FR-008
- FR-010
- FR-011
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
agent: python-pedro
history:
- at: '2026-08-02T20:55:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/wake.py
create_intent:
- tests/test_wake_stream.py
execution_mode: code_change
owned_files:
- src/agent_inbox/wake.py
- tests/test_wake_stream.py
role: implementer
tags: []
---

# WP01 — The reader

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

An object that holds the hub's per-actor event stream, signals when mail arrives, and
cannot break anything by failing. It owns a connection and a thread, so it must be
closable.

## Context

`the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1` built everything this consumes:
`GET /actors/{name}/events` and its per-actor authentication (WP01 of that mission), and
`SseParser`, `HubClient.events_url()` and `HubClient.stream_headers()` (WP02). Read
`mcp_client.py`'s `_hold_the_stream` for the async equivalent — the same problem solved
for a process with an event loop. This one has none.

The waiter is a hook subprocess. It runs on the agent's machine, and if it raises, hangs
or prints, it damages a turn. That is why every path here is silent.

## Subtasks

### T001 — A reader that holds the stream and signals on arrival

A small class in `wake.py`. It needs three things:

- `start()` — open the stream in a **daemon** thread and parse it with `SseParser`.
- `wait(seconds) -> None` — the `Sleeper` the loop in WP02 will be handed. Returns early
  when an arrival has been signalled, otherwise behaves as `time.sleep`. A
  `threading.Event` is exactly this, and its `wait` already has the signature.
- `close()` — stop the thread and close the response.

The connection must come from a **factory**, so a test can hand in a fake without a
socket. Address and headers come from `HubClient.events_url()` and `stream_headers()` —
never assembled here, or the stream will authenticate differently from the rest of the
client the first time auth changes (that duplication is what `stream_headers` exists to
prevent, and its docstring says so).

Standard library only (FR-010). `urllib.request.urlopen` returns something you can read in
chunks; feed each chunk to the parser.

**The event's payload is never read for content.** An arrival means *ask the hub*; the
hub's answer is what becomes the notice. A path from a sender-written payload into printed
text would undo the rule the whole wake mechanism exists under (C-002, FR-003).

### T002 — Failing to hold it is not an error

Every failure — the hub is down, the route does not exist, the token was revoked, the
connection drops, the parser is handed nonsense, a bug — leaves the reader in the state
"not streaming" and raises nothing, prints nothing, and exits nothing.

Test it by handing the factory something that raises, and something that yields garbage.
The reader must be usable afterwards and `wait` must behave as `time.sleep`.

### T003 — Only `mail` signals

`event: mail` sets the flag. Any other event type is ignored — not an error, not a signal
(FR-011). A comment line, a keep-alive, and a blank frame all pass through `SseParser`
already and must reach nothing.

This is what lets the hub add an event type later without waking every deployed client for
it.

### T004 — Reconnect while the wait has time left

A proxy will close a long connection; a hub restarts on every deploy. When the stream ends,
reconnect — but a reconnect loop that spins is worse than no stream at all.

`mcp_client.py` has `reconnect_delay`, jittered, with a settle-based reset that an outside
review put there for a specific failure (a hub that accepts and immediately drops). **Reuse
the delay function; do not reuse the loop** — the two have different lifetimes. The MCP
server reconnects for the life of a session; this reader stops when its wait expires.
Decide in code which parts transfer, and say so in a comment.

### T005 — Does the hub tell "no such route" apart from "unreachable"?

A question, answered by looking, and recorded in this file when you have the answer.

A hub older than the events route answers a 404; a hub that is down answers a connection
error. If the reader can tell them apart, it can stop retrying the stream for the rest of a
wait against an old hub, rather than reconnecting for eight hours to a route that will
never exist.

If it cannot tell them apart, FR-004 still holds and the cost is a retry loop that never
succeeds — wasteful, not wrong. Either way, write down which it is.

## Definition of done

- The reader signals on `mail`, ignores everything else, and swallows every failure.
- A fake connection drives all of it. No socket, no sleep, no flake.
- Nothing in `wake.py` outside the reader has changed yet.
- Four gates green: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pyright`.

## Reviewer guidance

Look for a path — any path — from the event payload to something printed. There must not
be one.
