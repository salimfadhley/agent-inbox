---
work_package_id: WP06
title: Prompts, migration broadcast, deploy
dependencies:
- WP05
requirement_refs:
- FR-010
- NFR-004
- C-004
- C-006
tracker_refs: []
planning_base_branch: feat/cli-primary-client
merge_target_branch: feat/cli-primary-client
branch_strategy: Planning artifacts for this mission were generated on feat/cli-primary-client. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/cli-primary-client unless the human explicitly redirects the landing branch.
subtasks:
- T028
- T029
- T030
- T031
- T032
agent: python-pedro
history:
- date: '2026-07-24'
  note: Authored during mission decomposition.
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/prompts/
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/prompts/agent.md
- src/agent_inbox/prompts/host.md
- src/agent_inbox/prompts/admin.md
- src/agent_inbox/templates/prompts.html
- docs/missions/README.md
role: implementer
tags: []
---

# WP06 — Prompts, migration broadcast, deploy

## ⚡ Do This First: Load Agent Profile

Before reading anything else, load your assigned profile with `/ad-hoc-profile-load
python-pedro`. It carries the TDD discipline, type-safety expectations and Python 3.12+
idioms this repo is held to.

## Branch Strategy

Planning branch and merge target are both `feat/cli-primary-client`. Execution worktrees
are allocated per computed lane from `lanes.json` — do not create branches by hand.

## Objective

Agents can migrate themselves, and the change reaches the hub without stranding anyone.

## Context

**Ordering is the whole risk.** Removing hosted MCP disconnects every agent until its human
reinstalls. Some have no human available — the hub has carried *"No human available to
restart anyone until further notice."*

So T030 (broadcast) must complete **while the old endpoint still works**, before T031
deploys the removal (C-004). Getting this backwards means agents lose access with no
instructions and no way to ask.

## Guidance per subtask

**T028** — rewrite the three role prompts. Replace every `claude mcp add --transport http
<url>` instruction with install → `init` → `mcp add ... -- agent-inbox mcp-serve`. Keep the
existing structure: choose a name, prove the connection with `ping`, persist to the local
project, invite a session restart. Keep the self-check — *if you have no tools, you are not
connected* — since it matters more, not less, during a migration.

**T029** — update the short-form copy blocks on `/ui/prompts` to match. They are what
humans actually paste.

**T030** — broadcast to `all/all`. This is one of the few things that genuinely warrants
it: a convention change nobody can opt out of. Say what changes, what breaks, the exact
commands, and where the full prompt lives. Make it self-contained — recipients do not share
our context.

**T031** — release, deploy to the hub, and `uv tool install --from . agent-inbox` locally
so agents on this machine have it.

**T032** — verify against a copy of live hub data (C-006, standing practice), then confirm
a real agent completes a round-trip. Tests on synthetic data have repeatedly missed what
live data caught.

## Reminder

No deployment-specific hostname in any prompt committed to the repo (C-003). The hub URL
is supplied by the operator.

## Definition of Done

- The three prompts describe CLI onboarding with no stale MCP-URL instructions.
- The broadcast went out **before** the removal deployed.
- Released, deployed to the hub, installed locally.
- Verified against live data and by a real agent round-trip.
- Four gates green.

## Quality gates (all four, every time)

```
uv run pytest
uv run ruff check
uv run ruff format --check
uvx pyright@1.1.411 src
```

## Reviewer guidance

Check the broadcast landed before the deploy — the git and hub timestamps
should show it. Re-read the prompts as if you had never seen the project.
