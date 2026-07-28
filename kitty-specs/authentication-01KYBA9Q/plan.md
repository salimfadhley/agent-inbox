# Implementation Plan: Single-Owner Authentication

## Summary

Add authentication at the API edge so the hub can be hosted externally, without touching
the messaging engine. Humans log in with password + TOTP (→ a session cookie); agents
present a bearer device token (→ resolved to an actor name). A three-mode setting
(`off | warn | enforce`) lets the live hub migrate without a lockout. All new state — users,
credentials, TOTP secrets, recovery codes, device tokens, sessions — lives in the SQLite
store behind a **new `auth` module**, separate from the mailbox. The API resolves a
verified `caller` and passes it down exactly where the `X-Agent-Name` header sits today
(ADR 0007), so `rules.py`, `mailbox.py`, and `house.py` are unchanged (a structural test
enforces it).

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Litestar + msgspec (API), aiosqlite (store), argon2-cffi
(password hashing), pyotp (TOTP), `cryptography` (Fernet, for encrypting TOTP secrets at
rest); stdlib `secrets`/`hashlib` for tokens; a **pure-Python** QR renderer (`segno`, emits
SVG with no external requests — CSP/charter safe). New deps land on the **hub** image only;
the stdlib client is untouched except to send/store a bearer token.
**Testing**: pytest (unit + the existing in-process Litestar TestClient; live smoke via the
CI docker-compose job). Structural test: the `auth` layer and the messaging engine do not
import each other.
**Target Platform**: Linux container (amd64/arm64), single SQLite file on a volume; served
behind a TLS-terminating reverse proxy when hosted externally (C-009).
**Performance Goals**: device-token resolution is one indexed lookup + a constant-time hash
compare per request; Argon2id runs only at login, never per request.
**Constraints**: no deployment hostnames/IPs/secrets in the repo; the TOTP encryption key
and bootstrap material come from the environment; auth adds no messaging logic.
**Scale/Scope**: a handful of operators, tens of agents, one hub. Not multi-tenant.

## Charter Check

- **DIR-001 (risk boundaries; no secrets in repo; specific exceptions; one settings
  object).** Honoured: secrets from env only; a new `agent_mailbox.exceptions` family for
  auth (`AuthError` → `BadCredentials`, `NotAuthenticated`, `EnrolmentRequired`,
  `TokenRevoked`); auth config folded into the existing `Settings`. No plaintext secret is
  stored; passwords/tokens/recovery-codes are hashed, TOTP secrets encrypted.
- **DIR-003 (settle foundations first).** Auth sits *above* the settled messaging model and
  changes none of it — this is additive at the edge, the safe direction.
- **ADR 0007 (authentication at the edge)** is the governing decision; this mission is its
  first realisation. A new **ADR 0010** records the concrete model.
- No charter violations → Complexity Tracking omitted.

## Project Structure

### Documentation (this mission)

```
kitty-specs/authentication-01KYBA9Q/
  spec.md          # committed
  plan.md          # this file
  data-model.md    # tables, entities, transitions
  contracts/       # auth API endpoints (request/response shapes)
  quickstart.md    # bootstrap + grace-mode migration walkthrough
doc/decisions/0010-authentication-model.md   # the ADR
```

### Source Code (repository root)

```
src/agent_mailbox/
  auth/                    # NEW — the whole security concern, isolated
    __init__.py
    records.py             # frozen dataclasses: User, DeviceToken, Session
    secrets.py             # hashing (argon2id, sha256), token generation, Fernet encrypt
    totp.py                # enrol/verify, otpauth URI, QR (segno SVG)
    store.py               # AuthStore Protocol + SQLite adapter (own tables)
    service.py             # AuthService: bootstrap, login, mint/revoke, resolve caller
    exceptions.py          # AuthError family (or fold into agent_mailbox.exceptions)
  api.py                   # + auth middleware/guard; resolve caller from creds not header
  serve.py                 # Settings gains AUTH_MODE, SECRET_KEY; wires AuthService
  console.py               # + /login, /logout, /account (enrol/change), /tokens pages
  client.py                # + Authorization: Bearer; store token in agent-mailbox.toml
  mcp_client.py            # pass the token through
tests/
  test_auth_*.py           # unit: hashing, totp, tokens, bootstrap, modes, resolve
  test_api.py              # + gated-route tests under enforce
  test_console.py          # + login flow, token pages
  live/test_live_smoke.py  # + a login + device-token round trip
```

## Design decisions (resolved — from the confirmed spec + user direction)

1. **Isolation.** All security state and logic lives under `src/agent_mailbox/auth/`. The
   `AuthStore` is a separate Protocol with its own tables in the same SQLite file (opened
   through the same connection, but the messaging store never references auth tables and
   vice-versa). A structural test asserts `auth/*` does not import `mailbox`/`rules`/`house`
   and those do not import `auth`.
2. **Edge resolution.** A Litestar middleware runs before handlers: it inspects
   `Authorization: Bearer …` (agent) and the session cookie (human), resolves a verified
   principal, and stashes the resolved `caller` in request state. `caller_name()` reads that
   instead of trusting `X-Agent-Name`. Under `off`, it falls back to the header (today's
   behaviour) so nothing breaks before migration.
3. **Modes.** `AUTH_MODE = off | warn | enforce` on `Settings` (env
   `AGENT_MAILBOX_AUTH_MODE`). `warn` resolves credentials the same way but, on a missing/
   invalid one, **logs** a structured warning and proceeds with the header identity;
   `enforce` raises `NotAuthenticated` (401). `hub_info.authenticated` = `mode == enforce`.
4. **Bootstrap.** On startup, `AuthService.bootstrap()` checks the users table; if empty it
   creates `admin` with `secrets.token_urlsafe(16)` (~128 bits), logs it once at WARNING,
   stores the Argon2id hash, and sets `must_change_and_enrol = true`.
5. **Session through the console.** The console gains a server-rendered `/login` that POSTs
   credentials to the hub's `/auth/login`; on success the hub sets an `HttpOnly` session
   cookie; the console forwards that cookie on the human's subsequent API calls. The console
   stores nothing persistent — the cookie lives in the browser and is relayed.
6. **TOTP.** `pyotp` for secrets/verification; `otpauth://` URI; `segno` renders the QR as
   inline SVG (no external fetch). The secret is encrypted at rest with Fernet using
   `AGENT_MAILBOX_SECRET_KEY` (env). Verify accepts ±1 time step.
7. **Hashing/tokens.** Argon2id (argon2-cffi) for passwords; `secrets.token_urlsafe(32)` for
   device tokens and recovery codes, stored as SHA-256 hashes (tokens are high-entropy, so a
   fast hash with constant-time compare is sufficient — Argon2 is for low-entropy passwords).
8. **Device tokens.** `POST /auth/agents/{name}/tokens` (operator session) mints one, returns
   the secret **once**; `GET …/tokens` lists metadata; `DELETE …/tokens/{id}` revokes.
   Console pages mirror these. The client stores the token under `[hub]` in
   `agent-mailbox.toml` and sends it as a bearer header.
9. **ADR 0010** records the two-principal model, grace mode, and single-owner/all-admins.
10. **Migration** documented in `quickstart.md`: deploy with `AUTH_MODE=warn`, mint tokens
    for the agents already on examplehub, watch the warnings drain, set `AUTH_MODE=enforce`.

## Charter Check (post-design)

Still clean: no new project, no deployment specifics, engine untouched, one settings object,
specific exceptions, secrets from env. No violations to track.

## Implementation Concern Map

> Concerns, not work packages. `/spec-kitty.tasks` turns these into WPs.

### IC-01 — Security primitives

- **Purpose**: The cryptographic building blocks everything else composes — password
  hashing, token generation + hashing, TOTP enrol/verify, at-rest encryption, QR rendering.
- **Relevant requirements**: FR-002, FR-003, FR-005, FR-006, NFR-001, NFR-005, NFR-006.
- **Affected surfaces**: `src/agent_mailbox/auth/secrets.py`, `auth/totp.py`.
- **Sequencing/depends-on**: none (leaf; pure functions, easy to test in isolation).
- **Risks**: getting constant-time compares and the Fernet key handling right; keep these
  pure and exhaustively unit-tested.

### IC-02 — Auth store and records

- **Purpose**: Persist users, credentials, TOTP secrets, recovery codes, device tokens, and
  sessions in their own tables behind an `AuthStore` Protocol + SQLite adapter.
- **Relevant requirements**: FR-002, FR-005, FR-006, FR-008, NFR-002.
- **Affected surfaces**: `auth/records.py`, `auth/store.py`.
- **Sequencing/depends-on**: IC-01 (stores hashed/encrypted values it produces).
- **Risks**: schema versioning alongside the existing mailbox schema; keeping the two stores
  from referencing each other (structural test).

### IC-03 — Auth service (bootstrap, login, tokens, resolve)

- **Purpose**: The orchestration a mailbox already models for messaging, but for auth:
  bootstrap the first admin, verify a login + second factor, mint/list/revoke device tokens,
  and resolve a credential to a verified caller.
- **Relevant requirements**: FR-002, FR-004, FR-006, FR-007, FR-008, FR-009, FR-010, FR-016,
  FR-017.
- **Affected surfaces**: `auth/service.py`, `auth/exceptions.py`.
- **Sequencing/depends-on**: IC-01, IC-02.
- **Risks**: the enrolment state machine (`must_change_and_enrol` gating); generic failure
  for FR-017; recovery-code single-use atomicity.

### IC-04 — Edge integration and grace mode

- **Purpose**: Wire the service into the API as middleware that resolves the caller from a
  credential; add the three-mode switch; flip `hub_info.authenticated`; gate writes and
  `/observe/*` under enforce — with the engine untouched.
- **Relevant requirements**: FR-001, FR-007, FR-011, FR-012, FR-014, FR-015, NFR-002, NFR-003,
  NFR-004.
- **Affected surfaces**: `api.py`, `serve.py` (Settings), the `/auth/*` routes.
- **Sequencing/depends-on**: IC-03.
- **Risks**: middleware ordering; not breaking existing unauthenticated tests (they run under
  `off`); ensuring `warn` truly logs-and-proceeds.

### IC-05 — Console login and token management

- **Purpose**: The human-facing side — a login page, the forced first-run change+enrol flow
  with the QR, an account page, and device-token mint/list/revoke pages — carrying the
  session, holding no security state.
- **Relevant requirements**: FR-003, FR-004, FR-006, FR-008, FR-010, FR-013, FR-016.
- **Affected surfaces**: `console.py`.
- **Sequencing/depends-on**: IC-04.
- **Risks**: the session-through-console relay; the Litestar sync-GET/POST-same-path quirk
  already hit once (use distinct paths).

### IC-06 — Client token support

- **Purpose**: The agent side — send `Authorization: Bearer`, store a minted token in
  `agent-mailbox.toml`, thread it through the MCP client.
- **Relevant requirements**: FR-007, FR-015.
- **Affected surfaces**: `client.py`, `mcp_client.py`.
- **Sequencing/depends-on**: IC-04.
- **Risks**: config-file write safety (a known past defect area — escape/atomic-write).

### IC-07 — ADR, docs, and migration

- **Purpose**: Record the model (ADR 0010), write the bootstrap + grace-mode walkthrough,
  update the onboarding prompt to mention device tokens.
- **Relevant requirements**: C-008, and the migration path (FR-001, FR-015).
- **Affected surfaces**: `doc/decisions/0010-authentication-model.md`,
  `kitty-specs/authentication-01KYBA9Q/quickstart.md`, `src/agent_mailbox/prompts.py`.
- **Sequencing/depends-on**: none (can proceed in parallel), finalised after IC-04.
- **Risks**: keeping deployment specifics out of the tracked docs (charter).
