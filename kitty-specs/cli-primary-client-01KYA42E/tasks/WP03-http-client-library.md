---
work_package_id: WP03
title: HTTP client library
dependencies:
- WP01
- WP02
requirement_refs:
- FR-004
- NFR-002
tracker_refs: []
planning_base_branch: feat/cli-primary-client
merge_target_branch: feat/cli-primary-client
branch_strategy: Planning artifacts for this mission were generated on feat/cli-primary-client. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/cli-primary-client unless the human explicitly redirects the landing branch.
subtasks:
- T012
- T013
- T014
- T015
agent: python-pedro
history:
- date: '2026-07-24'
  note: Authored during mission decomposition.
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/client.py
create_intent:
- src/agent_inbox/client.py
- tests/test_client.py
execution_mode: code_change
owned_files:
- src/agent_inbox/client.py
- tests/test_client.py
role: implementer
tags: []
---

# WP03 — HTTP client library

## ⚡ Do This First: Load Agent Profile

Before reading anything else, load your assigned profile with `/ad-hoc-profile-load
python-pedro`. It carries the TDD discipline, type-safety expectations and Python 3.12+
idioms this repo is held to.

## Branch Strategy

Planning branch and merge target are both `feat/cli-primary-client`. Execution worktrees
are allocated per computed lane from `lanes.json` — do not create branches by hand.

## Objective

One client, shared by the CLI and the stdio proxy, that can never hang an agent's turn.

## Context

This is the only place that knows how to talk to the hub. Both callers go through it, so
timeout and error behaviour is defined exactly once.

NFR-002 is the hard requirement: **a hub that is down, slow, or unreachable must never
hang the agent.** A mail check that stalls a turn is worse than a mail check that fails.

## Guidance per subtask

**T012** — `HubClient` wrapping `httpx`, taking hub URL and identity from config. Identity
goes in the header WP01 defined. Every request carries an explicit timeout; there is no
untimed call.

**T013** — translate failures into errors that say what to do: connection refused → the
hub is unreachable at this URL, check it is running; timeout → the hub did not respond in
N seconds; 4xx → the server's `detail`; 5xx → a hub-side failure with the status. Never
let a raw `httpx` exception escape.

**T014** — one method per API operation, returning the same models the CLI already prints,
so the command layer barely changes shape.

**T015** — stub-server tests for success, timeout, connection refused, 404 and 500.

## Anti-goal

No caching, no retries that could mask a broken hub, and **no fallback to local state**.
If the hub is unreachable, say so.

## Definition of Done

- Every request has a timeout; none can block indefinitely.
- No raw httpx exception reaches a caller.
- Failure messages name the fix, not just the fault.
- Four gates green.

## Quality gates (all four, every time)

```
uv run pytest
uv run ruff check
uv run ruff format --check
uvx pyright@1.1.411 src
```

## Reviewer guidance

Look for any code path that could block without a timeout, and for silent
retry logic that would hide an outage.
