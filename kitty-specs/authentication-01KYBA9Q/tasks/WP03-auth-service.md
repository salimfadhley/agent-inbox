---
work_package_id: WP03
title: Auth service
dependencies:
- WP02
requirement_refs:
- FR-004
- FR-006
- FR-008
- FR-009
- FR-010
- FR-016
- FR-017
tracker_refs: []
subtasks:
- T010
- T011
- T012
- T013
- T014
agent: python-pedro
history: []
agent_profile: python-pedro
authoritative_surface: src/agent_mailbox/auth/service.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_mailbox/auth/service.py
- tests/test_auth_service.py
role: implementer
tags: []
---

# WP03 — Auth service

## ⚡ Do This First: Load Agent Profile

Load your profile with `/ad-hoc-profile-load python-pedro`.

## Objective

`AuthService` orchestrates auth the way `Mailbox` orchestrates messaging: it holds an
`AuthStore`, the settings (secret key, session TTL), and a clock, and exposes the verbs the
edge and console call. No HTTP here — pure application logic over the store.

## Subtasks

- **T010 — bootstrap** (`bootstrap()`). If `not store.any_users()`, create `admin` with
  `generate_token()` as the password, **log it once** at WARNING (`initial admin password:
  …`), store the argon2 hash, `enrolment_state = must_change_and_enrol`. Idempotent: a second
  call with users present does nothing. Return whether it seeded (for the caller to log the
  banner).
- **T011 — login** (`login(username, password, otp) -> LoginResult`). Verify password;
  wrong user or wrong password → `BadCredentials` (identical — FR-017). If
  `must_change_and_enrol` → return a result indicating enrolment is required (a limited
  session). Else require `otp`: a valid TOTP (±1) **or** an unused recovery code
  (`spend_recovery_code`); failure → `BadCredentials`. Success → create a `Session`, stamp
  `last_login`, return it.
- **T012 — device tokens** (`mint_token(actor, label)`, `list_tokens(actor)`,
  `revoke_token(id)`, `resolve_token(secret) -> actor`). Mint returns the plaintext once,
  stores only the hash. `resolve_token` hashes the presented secret, looks it up, refuses a
  revoked one (`TokenRevoked`), stamps `last_used`, returns the actor.
- **T013 — account & sessions** (`enrol(username, new_password, otp)`,
  `change_password(username, current, new)`, `rotate_2fa(username)`/`confirm_2fa`,
  `resolve_session(session_id) -> username`, `logout`). `enrol` sets the password, verifies
  the first TOTP against the pending secret, encrypts+stores it, persists hashed recovery
  codes, flips to `active`. Sessions past `expires` resolve to nothing.
- **T014 — tests** (`tests/test_auth_service.py`) over `InMemoryAuthStore` and a fixed clock:
  bootstrap seeds once and logs; wrong-user and wrong-password are indistinguishable;
  enrolment gate blocks normal login until done; a recovery code works once then is spent;
  mint→resolve→revoke→refused; TOTP ±1 window; session expiry.

## Definition of Done

- Every verb covered; the FR-017 generic-failure and the enrolment gate explicitly tested.
- Clock injected (like `Mailbox`) so time-based paths are deterministic.
- Four gates green.

## Risks

- The enrolment state machine is the subtle part — a `must_change_and_enrol` user must be able
  to *enrol* but nothing else.
- Recovery-code single-use must go through the store's atomic `spend_recovery_code`.
