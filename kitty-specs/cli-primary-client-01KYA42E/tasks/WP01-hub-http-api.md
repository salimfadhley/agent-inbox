---
work_package_id: WP01
title: Hub HTTP API
dependencies: []
requirement_refs:
- FR-001
- C-002
- C-007
tracker_refs: []
planning_base_branch: feat/cli-primary-client
merge_target_branch: feat/cli-primary-client
branch_strategy: Planning artifacts for this mission were generated on feat/cli-primary-client. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/cli-primary-client unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
- T006
agent: python-pedro
history:
- date: '2026-07-24'
  note: Authored during mission decomposition.
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent:
- src/agent_inbox/api.py
- tests/test_api.py
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_api.py
- pyproject.toml
role: implementer
tags: []
---

# WP01 — Hub HTTP API

## ⚡ Do This First: Load Agent Profile

Before reading anything else, load your assigned profile with `/ad-hoc-profile-load
python-pedro`. It carries the TDD discipline, type-safety expectations and Python 3.12+
idioms this repo is held to.

## Branch Strategy

Planning branch and merge target are both `feat/cli-primary-client`. Execution worktrees
are allocated per computed lane from `lanes.json` — do not create branches by hand.

## Objective

Give the hub an HTTP API covering every mail operation, shaped so that the console
(mission 0021) and hand-written `curl` clients can adopt it later without redesign.

## Context

The hub currently speaks MCP over HTTP, with identity encoded in the URL path
(`/<project>/<agent>/mcp`). That is why nothing can authenticate: the caller picks its own
identity. This WP builds the replacement. Hosted MCP is **not** removed here — that is
WP05 — so nothing breaks while this lands.

`Mailbox` already implements all the behaviour. These routes are a front door, not new
logic.

## Guidance per subtask

**T001** — add `fastapi` and `httpx` to `[project.dependencies]`. `httpx` belongs in the
base install because the CLI (a client) needs it; both are small and Starlette is already
present transitively via `mcp`.

**T002** — an app factory `build_api(config) -> FastAPI` mounted under `/api/v1`. Identity
arrives in a **request header** (plan D3), resolved by a FastAPI dependency into
`(project, agent, role)`. Reject a malformed or missing identity with 400, naming the
header. Do not read identity from the path — that is the mistake being corrected.

**T003 / T004** — one route per operation, named for the resource, not the caller:
send, inbox (peek), read, reply, unread count; agents, whois, register, list-threads,
read-thread. Reuse the existing pydantic models for bodies and responses so the OpenAPI
schema is meaningful.

**T005** — map `MailboxError` to 404/409 as appropriate and `ConfigError` to 400, with a
`detail` a human or an agent can act on. Never leak a traceback.

**T006** — route coverage via `TestClient`. Include an explicit assertion that **no route
exposes `Mailbox.thread()`**: it is omniscient by design and backs only the console. A
route for it would re-open mission 0020 hub-wide (plan D4).

## Design tests to apply to every endpoint

- Could a non-CLI client use this, with only the OpenAPI schema? (C-007)
- Does it exist because a *client* wants it, or because it is a real resource operation?
  The former is forbidden.
- Could authentication be added later without moving it? (C-002)

## Definition of Done

- Send → inbox → read → reply completes end to end through `TestClient`.
- Every route carries identity in a header; none infers it from the path.
- Errors map to sensible statuses with actionable detail.
- A test asserts no route exposes the omniscient thread view.
- Four gates green.

## Quality gates (all four, every time)

```
uv run pytest
uv run ruff check
uv run ruff format --check
uvx pyright@1.1.411 src
```

## Reviewer guidance

Check the route list against the console's needs as well as the CLI's — a gap
found now is cheap, and found during mission 0021 is not. Confirm nothing in `api.py`
duplicates routing or visibility logic that belongs in `Mailbox`.
