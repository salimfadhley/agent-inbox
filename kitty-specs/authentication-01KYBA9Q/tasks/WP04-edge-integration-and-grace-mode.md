---
work_package_id: WP04
title: Edge integration and grace mode
dependencies:
- WP03
requirement_refs:
- FR-001
- FR-007
- FR-011
- FR-012
- FR-014
- FR-015
- NFR-001
- NFR-002
- NFR-003
- NFR-004
tracker_refs: []
planning_base_branch: feat/authentication
merge_target_branch: feat/authentication
branch_strategy: Planning artifacts for this mission were generated on feat/authentication. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/authentication unless the human explicitly redirects the landing branch.
subtasks:
- T015
- T016
- T017
- T018
- T019
- T020
agent: python-pedro
history: []
agent_profile: python-pedro
authoritative_surface: src/agent_mailbox/api.py
create_intent:
- tests/test_auth_api.py
execution_mode: code_change
owned_files:
- src/agent_mailbox/api.py
- src/agent_mailbox/serve.py
- tests/test_auth_api.py
- pyproject.toml
role: implementer
tags: []
---

# WP04 — Edge integration and grace mode

## ⚡ Do This First: Load Agent Profile

Load your profile with `/ad-hoc-profile-load python-pedro`.

## Objective

Wire `AuthService` into the API without touching the messaging engine. The caller is resolved
from a credential instead of a trusted header; a three-mode switch governs enforcement; the
`/auth/*` routes are exposed; `hub_info.authenticated` and the gated surfaces follow the mode.

## Subtasks

- **T015 — settings** (`serve.py`). Add `auth_mode: Literal["off","warn","enforce"] = "off"`
  and `secret_key: str | None` to `Settings.from_env` (`AGENT_MAILBOX_AUTH_MODE`,
  `AGENT_MAILBOX_SECRET_KEY`). Build the `AuthService` (SQLite adapter on the same DB path),
  call `bootstrap()` at startup, log the banner if it seeded.
- **T016 — middleware** (`api.py`). A resolver run before handlers: prefer
  `Authorization: Bearer` → `service.resolve_token` → actor; else the session cookie →
  `service.resolve_session` → username (humans act as themselves for `/auth/*` and observe).
  Stash the resolved caller in request state. `caller_name()` returns it. Behaviour by mode:
  `off` → fall back to `X-Agent-Name` (today); `warn` → resolve, and on missing/invalid
  **log** a structured warning then fall back to the header; `enforce` → missing/invalid →
  `NotAuthenticated` (401).
- **T017 — routes** (`api.py`). Add the `/auth/*` endpoints from `../contracts/auth-api.md`
  (login, logout, enrol GET/POST, change-password, rotate-2fa, and the token mint/list/revoke
  under an operator session). Reuse the existing `code`-carrying error handler.
- **T018 — gating & descriptor** (`api.py`). `hub_info.authenticated = (mode == "enforce")`.
  Under `enforce`, require a resolved caller on writes (`outbox`, `POST /actors`, `PUT
  /actors/{n}`, `read`) and on all `/observe/*`; reads that were already caller-gated are
  unchanged. This closes M2 FR-010.
- **T019 — tests** (`tests/test_auth_api.py`). A structural test: `api`/`serve` do not import
  `auth` *internals* beyond the service surface, and `rules`/`mailbox`/`house` never import
  `auth`. Functional: under `off`, existing header behaviour holds (the whole current suite
  still passes); under `enforce`, an anonymous write/observe is 401 and a bearer token / a
  session succeeds; under `warn`, an anonymous write succeeds **and** emits a warning log.
- **T020 — deps** (`pyproject.toml`). Add pinned `argon2-cffi`, `pyotp`, `cryptography`,
  `segno` to the **base** (hub) dependencies; update `uv.lock`. Keep the client extra as-is.

## Definition of Done

- The existing test suite still passes unchanged under the default `off` mode.
- The three modes behave exactly as specified; the structural test enforces the boundary.
- `GET /` reports `authenticated` per mode. Four gates green.

## Risks

- Middleware ordering and not breaking the ~281 existing tests (they assume `off`).
- Keep the engine import-clean — the structural test is the guard; make it fail first.
- The hub image must build with the four new deps (WP07/deploy will confirm multi-arch).
