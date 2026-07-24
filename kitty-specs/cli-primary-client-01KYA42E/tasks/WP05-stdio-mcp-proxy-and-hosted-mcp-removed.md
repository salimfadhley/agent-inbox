---
work_package_id: WP05
title: stdio MCP proxy, and hosted MCP removed
dependencies:
- WP04
requirement_refs:
- FR-002
- FR-003
- NFR-001
tracker_refs: []
planning_base_branch: feat/cli-primary-client
merge_target_branch: feat/cli-primary-client
branch_strategy: Planning artifacts for this mission were generated on feat/cli-primary-client. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/cli-primary-client unless the human explicitly redirects the landing branch.
subtasks:
- T022
- T023
- T024
- T025
- T026
- T027
agent: python-pedro
history:
- date: '2026-07-24'
  note: Authored during mission decomposition.
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/stdio_proxy.py
create_intent:
- src/agent_inbox/stdio_proxy.py
- tests/test_stdio_proxy.py
execution_mode: code_change
owned_files:
- src/agent_inbox/stdio_proxy.py
- src/agent_inbox/mcp_server.py
- tests/test_stdio_proxy.py
role: implementer
tags: []
---

# WP05 — stdio MCP proxy, and hosted MCP removed

## ⚡ Do This First: Load Agent Profile

Before reading anything else, load your assigned profile with `/ad-hoc-profile-load
python-pedro`. It carries the TDD discipline, type-safety expectations and Python 3.12+
idioms this repo is held to.

## Branch Strategy

Planning branch and merge target are both `feat/cli-primary-client`. Execution worktrees
are allocated per computed lane from `lanes.json` — do not create branches by hand.

## Objective

Agents reach the hub through a local stdio MCP server, and the hosted MCP transport is
deleted.

## Context

This is the point of the mission. A local process can push into the session it serves,
which is what makes channels possible; a hosted endpoint never can.

**Plan D2 — the proxy translates, it does not decide.** Each tool maps to exactly one HTTP
call. No routing, no filtering, no caching, no fallback. Logic in the proxy is logic that
can disagree with the server, and the visibility rules won in mission 0020 must live in
exactly one place.

## Guidance per subtask

**T022 / T023** — expose today's tool names **unchanged**: `ping`, `check_inbox`,
`send_message`, `read_message`, `reply_message`, `notify_agent`, `register`,
`list_agents`, `whois`, `hub_info`, `list_threads`, `read_thread`. Every agent's habits
and every prompt reference them. Each is a thin call into `HubClient`.

**T024** — `mcp-serve` runs the stdio proxy. Remove the hosted-transport options.

**T025** — strip the MCP mount from `build_http_app`; the hub serves the API and the
console. `AgentIdentityMiddleware` existed to parse identity out of the MCP path — most of
it should disappear with that path.

**T026** — assert the old hosted path 404s, and that the tool-name list is unchanged from
the previous release. The second test is what protects agents from a silent rename.

**T027** — measure added overhead against NFR-001 (under 100 ms on a LAN hub). Measure;
do not assume.

## Do not

Ship a compatibility shim for the hosted endpoint. The owner asked to remove the second
interface; keeping a shim is keeping it.

## Definition of Done

- An MCP client speaking stdio completes send → read → reply.
- The hosted MCP path is gone and a test proves it.
- Tool names are byte-identical to the previous release.
- Measured overhead meets NFR-001.
- Four gates green.

## Quality gates (all four, every time)

```
uv run pytest
uv run ruff check
uv run ruff format --check
uvx pyright@1.1.411 src
```

## Reviewer guidance

Confirm the proxy contains no conditional routing or visibility logic.
Confirm no code still imports the streamable-HTTP app.
