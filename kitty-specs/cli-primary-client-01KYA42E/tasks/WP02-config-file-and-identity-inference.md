---
work_package_id: WP02
title: Config file and identity inference
dependencies: []
requirement_refs:
- FR-005
- FR-006
- FR-007
- FR-008
tracker_refs: []
planning_base_branch: feat/cli-primary-client
merge_target_branch: feat/cli-primary-client
branch_strategy: Planning artifacts for this mission were generated on feat/cli-primary-client. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/cli-primary-client unless the human explicitly redirects the landing branch.
subtasks:
- T007
- T008
- T009
- T010
- T011
agent: python-pedro
history:
- date: '2026-07-24'
  note: Authored during mission decomposition.
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/conf_file.py
create_intent:
- src/agent_inbox/conf_file.py
- tests/test_conf_file.py
execution_mode: code_change
owned_files:
- src/agent_inbox/conf_file.py
- tests/test_conf_file.py
role: implementer
tags: []
---

# WP02 — Config file and identity inference

## ⚡ Do This First: Load Agent Profile

Before reading anything else, load your assigned profile with `/ad-hoc-profile-load
python-pedro`. It carries the TDD discipline, type-safety expectations and Python 3.12+
idioms this repo is held to.

## Branch Strategy

Planning branch and merge target are both `feat/cli-primary-client`. Execution worktrees
are allocated per computed lane from `lanes.json` — do not create branches by hand.

## Objective

Identity and hub URL come from `agent-inbox.toml`, and an agent that has no such file is
told precisely who it would be, where each part came from, and the one command to write it.

## Context

Owner's chosen bootstrap: **derive everything, show the inference, confirm once.** The
rejected alternative was an interactive wizard — agents drive non-interactive shells, and
an interactive prompt is exactly what stalled the codex CLI for 40 minutes.

Corrected derivation rule (a previous version of this guidance was wrong and has been
retracted in the agent prompt): **project = this git repository's name**, from
`git rev-parse --show-toplevel`. One repo, one project. Sibling repos under a shared
parent are *separate* projects; the parent directory is not a project.

## Guidance per subtask

**T007** — locate `agent-inbox.toml` by walking up from the working directory to the git
root. Stop at the git root; do not escape the repository. No file found is a normal
outcome, not an error.

**T008** — infer `project` from the git toplevel directory name (normalise: lowercase,
spaces/hyphens → `_`); `agent` from the engine; `role` defaults to the literal `agent`.
Fall back to the directory name outside a git repo, and to the org/owner when the name is
generic (`main`, `src`).

**T009** — each inferred value carries its **source**, because the output has to explain
itself: `project = agent_inbox (from git rev-parse --show-toplevel)`. This is what lets an
agent correct only the wrong part.

**T010** — `init` writes the file non-interactively. `--hub` is the only required
argument; every inferred value is overridable by flag. Never overwrite an existing file
without `--force`, and say what changed.

**T011** — tests build real temp git repos: discovery from a nested directory, inference,
provenance strings, init round-trip, and the no-config path.

## Constraint

No deployment-specific hostname may appear as a default anywhere — `--hub` is always the
user's to supply (C-003).

## Definition of Done

- Discovery works from any subdirectory of a repo and stops at the git root.
- Every inferred value reports its source.
- `init` is non-interactive and idempotent.
- Tests cover a real temp git repo, not a mocked one.
- Four gates green.

## Quality gates (all four, every time)

```
uv run pytest
uv run ruff check
uv run ruff format --check
uvx pyright@1.1.411 src
```

## Reviewer guidance

Confirm there is no interactive prompt on any path, and no hardcoded hub.
