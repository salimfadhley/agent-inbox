---
work_package_id: WP04
title: CLI rewritten onto the API
dependencies:
- WP03
requirement_refs:
- FR-004
- FR-009
- NFR-003
tracker_refs: []
planning_base_branch: feat/cli-primary-client
merge_target_branch: feat/cli-primary-client
branch_strategy: Planning artifacts for this mission were generated on feat/cli-primary-client. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/cli-primary-client unless the human explicitly redirects the landing branch.
subtasks:
- T016
- T017
- T018
- T019
- T020
- T021
agent: python-pedro
history:
- date: '2026-07-24'
  note: Authored during mission decomposition.
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/cli.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/cli.py
- tests/test_cli.py
role: implementer
tags: []
---

# WP04 — CLI rewritten onto the API

## ⚡ Do This First: Load Agent Profile

Before reading anything else, load your assigned profile with `/ad-hoc-profile-load
python-pedro`. It carries the TDD discipline, type-safety expectations and Python 3.12+
idioms this repo is held to.

## Branch Strategy

Planning branch and merge target are both `feat/cli-primary-client`. Execution worktrees
are allocated per computed lane from `lanes.json` — do not create branches by hand.

## Objective

Every CLI command reaches the hub over HTTP. No CLI code path opens SQLite — ever.

## Context

**Owner ruling, not a preference:** *"the CLI can only talk to the API. The SQLite
database is 100% private."* All 13 commands currently open the database directly. They all
move behind `HubClient`.

There is deliberately **no `--db` escape hatch**. On-box debugging remains possible, but
as a server-side operation, not a CLI feature.

## Guidance per subtask

**T016 / T017** — mechanical per command: replace the `Mailbox` call with the matching
`HubClient` call. **Output shapes stay identical** — agents and humans have habits built
on them, and changing transport plus presentation at once makes any regression
untraceable.

**T018** — delete the SQLite paths, the `--db` option, and the now-unused imports. A
lingering import is how the boundary quietly comes back.

**T019** — with no config: print each inferred value with its source, print the one `init`
command, exit non-zero, and **do not contact the hub**. Nothing is more confusing than a
connection error when the real problem is missing configuration.

**T020** — `doctor` walks the whole path in order — config found → hub reachable →
identity registered → tools servable — and names the fix for each failure. It is the first
thing a stuck agent runs, so each line must be actionable on its own.

**T021** — rewrite `test_cli.py` against a stub hub. Include a test that asserts **no
database file is opened** during any command; that is the constraint most likely to erode.

## Watch for

Commands that quietly depended on local-database behaviour (immediate consistency,
ordering). Anything relying on those needs to become an explicit API guarantee.

## Definition of Done

- All 13 commands work against the hub.
- No SQLite import or `--db` flag remains in the CLI.
- A test asserts no database is opened.
- No-config output explains itself and never calls the hub.
- Four gates green.

## Quality gates (all four, every time)

```
uv run pytest
uv run ruff check
uv run ruff format --check
uvx pyright@1.1.411 src
```

## Reviewer guidance

Grep the CLI for `Mailbox`, `aiosqlite` and `db` — any hit is a defect.
Diff command output against the previous release for accidental format changes.
