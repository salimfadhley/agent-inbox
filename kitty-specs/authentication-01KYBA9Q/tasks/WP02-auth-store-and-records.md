---
work_package_id: WP02
title: Auth store and records
dependencies:
- WP01
requirement_refs:
- FR-005
- FR-006
- FR-008
- NFR-002
tracker_refs: []
planning_base_branch: feat/authentication
merge_target_branch: feat/authentication
branch_strategy: Planning artifacts for this mission were generated on feat/authentication. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/authentication unless the human explicitly redirects the landing branch.
subtasks:
- T005
- T006
- T007
- T008
- T009
agent: python-pedro
history: []
agent_profile: python-pedro
authoritative_surface: src/agent_mailbox/auth/store.py
create_intent:
- src/agent_mailbox/auth/__init__.py
- src/agent_mailbox/auth/records.py
- src/agent_mailbox/auth/store.py
- src/agent_mailbox/auth/exceptions.py
- tests/test_auth_store.py
execution_mode: code_change
owned_files:
- src/agent_mailbox/auth/__init__.py
- src/agent_mailbox/auth/records.py
- src/agent_mailbox/auth/store.py
- src/agent_mailbox/auth/exceptions.py
- tests/test_auth_store.py
role: implementer
tags: []
---

# WP02 — Auth store and records

## ⚡ Do This First: Load Agent Profile

Load your profile with `/ad-hoc-profile-load python-pedro`.

## Objective

Persist all security state in its **own** tables behind an `AuthStore` Protocol, with an
in-memory adapter (for tests) and a SQLite adapter. The messaging store never references
these tables and vice-versa. See `../data-model.md` for the exact schema.

## Subtasks

- **T005 — records** (`auth/records.py`). Frozen `@dataclass(slots=True)`: `User(username,
  password_hash, totp_secret_enc: bytes|None, enrolment_state, created, last_login)`,
  `DeviceToken(id, actor, token_hash, label, created, last_used, revoked)`,
  `Session(id, username, created, expires)`. `enrolment_state` is a `Literal["must_change_and_enrol","active"]`
  or a small `StrEnum`.
- **T006 — Protocol + memory** (`auth/store.py`). `AuthStore` Protocol: `add_user`,
  `get_user`, `put_user`, `any_users`, `add_recovery_codes`, `spend_recovery_code(username,
  code_hash) -> bool` (atomic; true only if an unused matching row existed), `add_token`,
  `get_token_by_hash`, `tokens_for(actor)`, `touch_token`, `revoke_token(id) -> bool`,
  `add_session`, `get_session`, `delete_session`, `schema_version`/`set_schema_version`. Plus
  `InMemoryAuthStore`.
- **T007 — SQLite adapter** (`auth/store.py`). `SqliteAuthStore` over aiosqlite creating the
  `auth_users`, `auth_recovery_codes`, `auth_device_tokens`, `auth_sessions`, `auth_meta`
  tables. `spend_recovery_code` uses a single `UPDATE … WHERE used=0` and checks `rowcount`
  for atomicity. `revoke_token` likewise. Index `auth_device_tokens.token_hash`.
- **T008 — exceptions** (`auth/exceptions.py`). An `AuthError` base carrying a stable `code`,
  with `BadCredentials`, `NotAuthenticated`, `EnrolmentRequired`, `TokenRevoked`,
  `UnknownUser` (mapped to bad_credentials at the edge). Follow the repo standard: specific
  exceptions, one package base.
- **T009 — contract tests** (`tests/test_auth_store.py`). Parametrise over both adapters:
  add/get user; `any_users` transitions false→true; recovery code spent exactly once (second
  spend returns false); token added, found by hash, touched, revoked (then not found /
  flagged revoked); session add/get/delete and expiry-is-data.

## Definition of Done

- Both adapters satisfy the same contract tests; recovery-code and revoke atomicity proven.
- No import of `mailbox`/`rules`/`house` from any `auth/*` module.
- Four gates green.

## Risks

- Schema coexistence: the SQLite adapter must create its tables idempotently and version them
  via `auth_meta`, independent of the mailbox schema.
- Keep `spend_recovery_code`/`revoke_token` atomic — assert on the negative (double-spend) path.
