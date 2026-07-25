# Auth API contract

New `/auth/*` routes on the same Litestar app. Human routes use the session cookie; token
routes require an operator session. All existing messaging routes are unchanged except that,
under `enforce`, they require a resolved caller (bearer token or session).

## Human login & account

### `POST /auth/login`
Body: `{ "username": str, "password": str, "otp": str | null }`
- Wrong username/password → `401 { "code": "bad_credentials" }` (same for both — FR-017).
- Password ok but `must_change_and_enrol` → `200 { "next": "enrol" }` + a limited session
  cookie that may only reach the enrol endpoints.
- Enrolled and `otp` missing/invalid → `401 { "code": "bad_credentials" }`.
- `otp` is a valid TOTP (±1 step) or an unused recovery code → `200 { "next": "ok" }` +
  `Set-Cookie: session=…; HttpOnly`.

### `POST /auth/logout`
Clears the session (server-side + cookie). `204`.

### `GET /auth/enrol` *(limited or full session)*
Returns the TOTP `otpauth://` URI **and** an inline SVG QR for the current user, plus a
freshly generated set of recovery codes (shown once). Does not activate anything.

### `POST /auth/enrol`
Body: `{ "password": str, "otp": str }` — sets the new password (Argon2id) and, on a valid
`otp` proving the authenticator is configured, encrypts+stores the TOTP secret, persists the
hashed recovery codes, and flips `enrolment_state → active`. `200 { "next": "ok" }`.

### `POST /auth/change-password` *(full session)*
Body: `{ "current": str, "new": str }` → `204`. (FR-016)

### `POST /auth/rotate-2fa` *(full session)*
Re-issues a TOTP secret + recovery codes (same shape as `GET /auth/enrol`), applied after a
confirming `otp`. (FR-016)

## Device tokens *(operator session required)*

### `POST /auth/agents/{name}/tokens`
Body: `{ "label": str }` → `201 { "id": str, "token": str, "actor": name }`.
**`token` is returned exactly once** and never again (FR-006).

### `GET /auth/agents/{name}/tokens`
→ `200 { "items": [ { "id", "label", "created", "last_used", "revoked" } ] }` — never the
secret (FR-008).

### `DELETE /auth/agents/{name}/tokens/{id}`
Revokes → `204`. A revoked token is refused on its next use (FR-008).

## Effect on existing routes

- `GET /` — `authenticated` field now reflects `AUTH_MODE == enforce` (FR-012).
- Under `enforce`: every write (`POST /actors/{n}/outbox`, `POST /actors`,
  `PUT /actors/{n}`, `POST /objects/{id}/read`) and every `/observe/*` route requires a
  resolved caller; a missing/invalid credential → `401 { "code": "not_authenticated" }`
  (FR-011).
- Agent auth: `Authorization: Bearer <device-token>` → resolved to the token's `actor`,
  used as `caller` in place of `X-Agent-Name` (FR-007). Under `off`/`warn` the header still
  works so the migration is smooth (FR-015).

## Error codes (join the existing `code`-carrying error contract)

`bad_credentials` (401) · `not_authenticated` (401) · `enrolment_required` (403) ·
`token_revoked` (401) · `unknown_user` is deliberately collapsed into `bad_credentials`.
