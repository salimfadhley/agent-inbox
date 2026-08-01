---
work_package_id: WP03
title: 'The image, CI, and every sentence that states a version'
dependencies:
- WP01
requirement_refs:
- FR-002
- FR-003
- FR-005
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/13
planning_base_branch: kitty/mission-current-python
merge_target_branch: kitty/mission-current-python
branch_strategy: Planning artifacts for this mission were generated on kitty/mission-current-python. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into kitty/mission-current-python unless the human explicitly redirects the landing branch.
subtasks:
- T010
- T011
- T012
- T013
phase: Phase 2 - Where it runs, and what we say about it
agent: python-pedro
history:
- at: 2026-08-01T14:45:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: .github/workflows/
execution_mode: code_change
owned_files:
- Dockerfile
- .github/workflows/**
- README.md
- CONTRIBUTING.md
- .kittify/metadata.yaml
- doc/**
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP03 – The image, CI, and the words

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer` · **Agent/tool**: `python-pedro`

---

## Objective

Make the places this project actually *runs* — the published container and CI — use 3.14,
and make every sentence that states a version say the same thing.

## Prerequisites

**WP01 must have landed.** This WP changes where the code runs; WP01 changes what the code
declares. Doing this first produces an image running 3.14 against a package that still says
it needs 3.12.

Runs in parallel with WP02. The two share no files.

## Subtasks

### T010 — Both `Dockerfile` stages move to `python:3.14-slim` [P]

There are **two** `FROM` lines:

- `Dockerfile:16` — `FROM python:3.12-slim AS build`
- `Dockerfile:37` — `FROM python:3.12-slim AS runtime`

Change both. **Changing one produces an image that builds on 3.14 and runs on 3.12**, or the
reverse — and it will look fine until something version-specific breaks in production.
T011 is what catches this.

### T011 — The gates pass **inside** the container

FR-003 says the image runs 3.14 **and the gates pass inside it**. That second half is the
requirement; the first half alone is satisfied by a `FROM` line.

Build the image, then run the four gates in it:

```bash
docker build -t agent-inbox:py314-check .
docker run --rm agent-inbox:py314-check python -V     # says 3.14
# then the four gates, inside the container
```

**A laptop run does not satisfy this.** The container has a different libc, a different
wheel set and a different filesystem, and this project's deployment history is a series of
things that were green locally and wrong in the place they ran.

Capture real exit codes — do not read `$?` after a pipe into `tail`.

### T012 — Collapse the CI matrix to 3.14 alone [P]

`.github/workflows/ci.yml`:

- Line 35: `uv sync --python 3.12` → `3.14`
- Line 53: `python-version: ["3.12", "3.13"]` → `["3.14"]`
- Line 15: a comment referring to behaviour differing "across 3.12/3.13" — update the words
  to match what the file now does

**This deletes the matrix rather than editing it**, and that is deliberate. FR-002 says the
gates run on 3.14, singular. This is an application, not a library — the spec's argument is
that it "owes nobody multi-version support". A `["3.12","3.14"]` matrix would keep testing a
configuration nobody ships, cost double the minutes, and tell the next reader the floor is
still 3.12.

If a single-entry matrix now reads as pointless scaffolding, collapsing it to a plain job is
fine — but keep the change visible in the commit message either way.

### T013 — README, CONTRIBUTING, `.kittify/metadata.yaml` [P]

Every remaining sentence that states a version:

| File | Line | What |
|---|---|---|
| `README.md` | 9 | the `python-3.12%2B-blue` badge |
| `README.md` | 54 | "**Python 3.12+** for the client tooling" |
| `README.md` | 55 | "Docker … (or Python 3.12+ and `agent-inbox serve`)" |
| `CONTRIBUTING.md` | 13 | "You need **Python 3.12+** and nothing else" |
| `.kittify/metadata.yaml` | 16 | `python_version: 3.12.1` |

Also check `doc/` for any self-hosting or install guide stating a version — FR-005 names
the self-hosting guide specifically.

**Do not edit `doc/session_logs/`.** Those are dated records of what happened at the time;
rewriting them would make them lie. If a session log mentions 3.12, it is correct.

## Definition of Done

- [ ] Both `Dockerfile` stages are `python:3.14-slim`
- [ ] The image reports 3.14 **and** the four gates pass inside it, with real exit codes
- [ ] CI installs and tests on 3.14 only; the stale 3.12/3.13 comment is gone
- [ ] `grep -rn '3\.12' README.md CONTRIBUTING.md doc/ .kittify/metadata.yaml` returns
      nothing outside `doc/session_logs/`
- [ ] The README badge renders 3.14

## Risks

| Risk | What to do |
|---|---|
| Only one `FROM` line is changed | T011 is the check. Run the gates in the container, not beside it |
| The matrix is edited instead of collapsed | Read FR-002 again: one version, because this is an application |
| Session logs get "corrected" | They are dated records. Leave them |

## Reviewer guidance

Grep the whole repo for `3.12` and `py312` at the end and account for every remaining hit.
The expected survivors are `doc/session_logs/` and nothing else.
