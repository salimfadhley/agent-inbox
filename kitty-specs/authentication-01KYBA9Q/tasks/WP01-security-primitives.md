---
work_package_id: WP01
title: Security primitives
dependencies: []
requirement_refs:
- FR-002
- FR-003
- FR-005
- FR-006
- NFR-005
- NFR-006
tracker_refs: []
planning_base_branch: feat/authentication
merge_target_branch: feat/authentication
branch_strategy: Planning artifacts for this mission were generated on feat/authentication. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/authentication unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
agent: python-pedro
history: []
agent_profile: python-pedro
authoritative_surface: src/agent_mailbox/auth/secrets.py
create_intent:
- src/agent_mailbox/auth/secrets.py
- src/agent_mailbox/auth/totp.py
- tests/test_auth_primitives.py
execution_mode: code_change
owned_files:
- src/agent_mailbox/auth/secrets.py
- src/agent_mailbox/auth/totp.py
- tests/test_auth_primitives.py
role: implementer
tags: []
---

# WP01 — Security primitives

## ⚡ Do This First: Load Agent Profile

Before anything else, load your profile with `/ad-hoc-profile-load python-pedro` — the
TDD discipline, type-safety, and Python 3.12+ idioms this repo is held to.

## Objective

The cryptographic leaf everything else composes: password hashing, device-token generation
and hashing, at-rest encryption for TOTP secrets, and TOTP enrolment/verification with a
server-rendered QR. Pure functions, no store, no network, exhaustively tested.

## Subtasks

- **T001 — hashing & tokens** (`auth/secrets.py`). `hash_password`/`verify_password` via
  argon2id (argon2-cffi, `PasswordHasher`). `generate_token()` → `secrets.token_urlsafe(32)`.
  `hash_token(secret)` → hex SHA-256. `token_matches(secret, stored_hash)` using
  `hmac.compare_digest`. Device tokens and recovery codes are high-entropy, so a fast hash
  with constant-time compare is correct; Argon2 is only for the low-entropy password.
- **T002 — at-rest encryption** (`auth/secrets.py`). `encrypt_secret(plaintext, key)` /
  `decrypt_secret(token, key)` via `cryptography.fernet.Fernet`. A helper `fernet_key_from(env
  value)` that validates the key and a `generate_key()` for the CLI helper. The key comes from
  the caller (env), never hard-coded.
- **T003 — TOTP** (`auth/totp.py`). `new_secret()`; `provisioning_uri(secret, username, issuer)`
  → `otpauth://`; `qr_svg(uri)` → inline SVG string via `segno` (no external requests);
  `verify(secret, code, valid_window=1)`. Also `new_recovery_codes(n=10)` returning plaintext
  codes (hashing is the store's job).
- **T004 — tests** (`tests/test_auth_primitives.py`). Password round-trip + wrong-password
  reject; token hash is stable and `token_matches` is true only for the right secret;
  Fernet round-trip and that a wrong key / tampered token fails to decrypt; TOTP verify accepts
  a code from the same secret and rejects a foreign one; `verify` honours the ±1-step window
  (generate a code for the previous step and confirm acceptance); `qr_svg` returns `<svg…`
  and contains no `http`-scheme external reference.

## Definition of Done

- All four subtasks implemented; `tests/test_auth_primitives.py` covers each with at least
  the cases above, including a **tamper/negative** case per primitive.
- Full type annotations; specific exceptions (no bare `Exception`); no `print`.
- The four gates pass: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
  `uvx pyright@1.1.411 src`.
- `pyproject.toml` dependency additions are **not** made here (WP04 owns pyproject); if you
  need the libs locally, `uv add` them there is out of scope — note the requirement for WP04.

## Risks

- Constant-time compares matter — use `hmac.compare_digest`/argon2's own verify, never `==`.
- `segno` must emit self-contained SVG (no external font/URL) to stay CSP/charter-safe.
