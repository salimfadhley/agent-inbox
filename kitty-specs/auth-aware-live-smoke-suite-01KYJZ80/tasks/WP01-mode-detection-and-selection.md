---
work_package_id: WP01
title: Mode detection, and making -k auth work
dependencies: []
requirement_refs:
- FR-001
- FR-004
- NFR-001
- NFR-002
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
agent: ''
history: []
authoritative_surface: tests/live/conftest.py
create_intent:
- tests/live/conftest.py
execution_mode: code_change
owned_files:
- tests/live/conftest.py
- tests/live/test_live_smoke.py
role: implementer
tags: []
---

# WP01 — Mode detection, and making `-k auth` work

## Objective

Give the suite a **premise**. Today it has no representation of what kind of hub it is
talking to, so the answer is hardcoded as an assumption and every assertion inherits it.
This WP introduces the probe and the fixture everything else keys off, and fixes the
selector while in the file.

Nothing else in the mission can be done first.

## Subtasks

- **T001 — the probe** (`tests/live/conftest.py`). A session-scoped fixture that fetches
  `GET /` once and exposes a `HubDescriptor` (`name`, `version`, `authenticated`, `note`)
  and a derived `AuthMode` of `open` or `enforcing`. See `data-model.md`.

  **A failed probe fails the run**, with a message naming the URL it tried. It must not
  fall back to a default: a default is exactly the current bug, and one that would then be
  invisible because the suite would look like it was working.

- **T002 — record the mode in failure output** (NFR-002). Any assertion that depends on
  the mode reports which mode it assumed. A wrong assumption must be diagnosable from the
  failure alone, without re-running against the hub.

- **T003 — test selection** (FR-004). Mark or rename the auth-relevant tests so
  `pytest tests/live -k auth` selects them. Today it deselects all 11, so the obvious way
  to reach the `LIVE_AUTH` variants finds nothing. If a pytest marker is used, register it
  in `pyproject.toml` so it does not warn.

## Acceptance

- Pointed at an open hub, the fixture reports `open`; pointed at an enforcing hub,
  `enforcing`. Both verified against a real hub, not a mock — the point of this suite is
  that it talks to the shipped image.
- With the hub unreachable, the run stops with a message naming the URL. It does not
  proceed to produce per-test failures that describe the wrong problem.
- `pytest tests/live -k auth` selects a non-zero number of tests.

## Notes

`LIVE_HUB_URL` / `LIVE_CONSOLE_URL` stay the only source of addresses — no hostname enters
the repository (NFR-001, and the generic-only rule in `AGENTS.md`).

Do not model `warn` mode. Its caller-facing semantics are an open question in
`auth-mode-truthful-error-text-01KYJZ81`, and modelling it now would encode a guess.
