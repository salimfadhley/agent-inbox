# Tasks — Single-Owner Authentication

Seven work packages, mapped from the plan's Implementation Concern Map. A strict dependency
chain through the core (WP01 → WP02 → WP03 → WP04), then two parallel edges (WP05, WP06) and
docs (WP07) off WP04. Tests are required in every WP; the four gates stay green throughout.

Branch: planning on `feat/authentication`; completed WPs merge back to `feat/authentication`,
which PRs to `main`.

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | argon2id hash/verify; sha256 token hash; token generation | WP01 | |
| T002 | Fernet encrypt/decrypt for TOTP secrets, key from env | WP01 | |
| T003 | TOTP enrol/verify (pyotp), otpauth URI, segno SVG QR | WP01 | |
| T004 | unit tests for all primitives (round-trips, tamper, ±1 step) | WP01 | |
| T005 | frozen records: User, DeviceToken, Session | WP02 | |
| T006 | AuthStore Protocol + in-memory impl | WP02 | |
| T007 | SQLite adapter: own tables, schema/meta, atomic recovery-code use | WP02 | |
| T008 | auth exceptions family | WP02 | |
| T009 | store contract tests | WP02 | |
| T010 | bootstrap: empty→admin+random pw to log, must_change_and_enrol | WP03 | |
| T011 | login: password + TOTP/recovery, generic failure, enrolment gate | WP03 | |
| T012 | mint/list/revoke device tokens; resolve token→actor | WP03 | |
| T013 | enrol/change-password/rotate-2fa; session lifecycle | WP03 | |
| T014 | service unit tests | WP03 | |
| T015 | AUTH_MODE off/warn/enforce on Settings | WP04 | |
| T016 | auth middleware: resolve caller from bearer/session, not header | WP04 | |
| T017 | /auth/* routes wired to the service | WP04 | |
| T018 | hub_info.authenticated; gate writes + /observe/* under enforce | WP04 | |
| T019 | structural test: engine⊥auth; api tests across modes | WP04 | |
| T020 | pin new hub deps (argon2-cffi, pyotp, cryptography, segno) | WP04 | |
| T021 | console /login, /logout, session relay | WP05 | |
| T022 | forced first-run change+enrol with inline QR | WP05 | |
| T023 | /account (change pw, rotate 2fa) | WP05 | |
| T024 | device-token mint/list/revoke pages | WP05 | |
| T025 | console tests (login flow, token pages) | WP05 | |
| T026 | client sends Authorization: Bearer; token in agent-mailbox.toml | WP06 | [P] |
| T027 | mcp_client threads the token; join records a minted token | WP06 | [P] |
| T028 | client token tests | WP06 | [P] |
| T029 | ADR 0010 — authentication model | WP07 | [P] |
| T030 | update prompts.py to mention device tokens | WP07 | [P] |
| T031 | live smoke: login + device-token round trip | WP07 | [P] |

## WP01 — Security primitives

- **Goal**: The cryptographic leaf: password hashing, token generation+hashing, at-rest
  encryption, and TOTP enrol/verify + QR. Pure, exhaustively tested.
- **Depends on**: none. **Independent test**: unit round-trips and tamper cases.
- [ ] T001 argon2id hash/verify; sha256 token hash; token generation (WP01)
- [ ] T002 Fernet encrypt/decrypt for TOTP secrets, key from env (WP01)
- [ ] T003 TOTP enrol/verify (pyotp), otpauth URI, segno SVG QR (WP01)
- [ ] T004 unit tests for all primitives (WP01)

## WP02 — Auth store and records

- **Goal**: Persist all security state in its own tables behind an `AuthStore` Protocol, with
  an in-memory and a SQLite adapter, decoupled from the messaging store.
- **Depends on**: WP01. **Independent test**: store contract tests over both adapters.
- [ ] T005 frozen records: User, DeviceToken, Session (WP02)
- [ ] T006 AuthStore Protocol + in-memory impl (WP02)
- [ ] T007 SQLite adapter: own tables, schema/meta, atomic recovery-code use (WP02)
- [ ] T008 auth exceptions family (WP02)
- [ ] T009 store contract tests (WP02)

## WP03 — Auth service

- **Goal**: Orchestrate bootstrap, login + second factor, device-token lifecycle, caller
  resolution, and the enrolment state machine.
- **Depends on**: WP02. **Independent test**: service unit tests over the in-memory store.
- [ ] T010 bootstrap: empty→admin+random pw to log, must_change_and_enrol (WP03)
- [ ] T011 login: password + TOTP/recovery, generic failure, enrolment gate (WP03)
- [ ] T012 mint/list/revoke device tokens; resolve token→actor (WP03)
- [ ] T013 enrol/change-password/rotate-2fa; session lifecycle (WP03)
- [ ] T014 service unit tests (WP03)

## WP04 — Edge integration and grace mode

- **Goal**: Wire the service into the API as middleware; the three-mode switch; the `/auth/*`
  routes; flip `authenticated`; gate writes + `/observe/*` under enforce — engine untouched.
- **Depends on**: WP03. **Independent test**: api tests across off/warn/enforce; structural test.
- [ ] T015 AUTH_MODE off/warn/enforce on Settings (WP04)
- [ ] T016 auth middleware: resolve caller from bearer/session, not header (WP04)
- [ ] T017 /auth/* routes wired to the service (WP04)
- [ ] T018 hub_info.authenticated; gate writes + /observe/* under enforce (WP04)
- [ ] T019 structural test: engine⊥auth; api tests across modes (WP04)
- [ ] T020 pin new hub deps (argon2-cffi, pyotp, cryptography, segno) (WP04)

## WP05 — Console login and token management

- **Goal**: The human side — login, forced first-run change+enrol with QR, account page,
  and device-token pages. Carries the session, holds no security state.
- **Depends on**: WP04. **Independent test**: console tests for login + token pages.
- [ ] T021 console /login, /logout, session relay (WP05)
- [ ] T022 forced first-run change+enrol with inline QR (WP05)
- [ ] T023 /account (change pw, rotate 2fa) (WP05)
- [ ] T024 device-token mint/list/revoke pages (WP05)
- [ ] T025 console tests (WP05)

## WP06 — Client token support

- **Goal**: The agent side — send the bearer token, store it safely in `agent-mailbox.toml`,
  thread it through the MCP client.
- **Depends on**: WP04. **Independent test**: client token tests.
- [ ] T026 client sends Authorization: Bearer; token in agent-mailbox.toml (WP06)
- [ ] T027 mcp_client threads the token; join records a minted token (WP06)
- [ ] T028 client token tests (WP06)

## WP07 — ADR, docs, and migration

- **Goal**: Record the model (ADR 0010), mention device tokens in the prompt, and add a live
  smoke path exercising login + a device-token round trip.
- **Depends on**: WP04. **Independent test**: the new live smoke assertions.
- [ ] T029 ADR 0010 — authentication model (WP07)
- [ ] T030 update prompts.py to mention device tokens (WP07)
- [ ] T031 live smoke: login + device-token round trip (WP07)
