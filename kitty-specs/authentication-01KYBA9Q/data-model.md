# Data model — authentication

New tables in the same SQLite file, owned by the `auth` module. The messaging tables are
untouched and never joined against these. Everything sensitive is stored hashed or
encrypted — a raw dump reveals no usable secret (NFR-001).

## Tables

### `auth_users`
| column | type | notes |
|---|---|---|
| `username` | TEXT PK | the login name; `admin` for the bootstrap account |
| `password_hash` | TEXT | Argon2id encoded hash; never the password |
| `totp_secret_enc` | BLOB NULL | Fernet-encrypted TOTP secret; NULL until enrolled |
| `enrolment_state` | TEXT | `must_change_and_enrol` \| `active` |
| `created` | TEXT | ISO-8601 UTC |
| `last_login` | TEXT NULL | ISO-8601 UTC |

All users are admins — there is no role column, on purpose (C-001).

### `auth_recovery_codes`
| column | type | notes |
|---|---|---|
| `username` | TEXT | FK → `auth_users.username` |
| `code_hash` | TEXT | SHA-256 of a single-use code |
| `used` | INTEGER | 0/1; set to 1 atomically on use (FR-005, NFR-006) |

### `auth_device_tokens`
| column | type | notes |
|---|---|---|
| `id` | TEXT PK | opaque token id (safe to show/list) |
| `actor` | TEXT | the mailbox actor this token authenticates as |
| `token_hash` | TEXT | SHA-256 of the secret; the secret itself is shown once, never stored |
| `label` | TEXT | human note, e.g. "jed on workshop" |
| `created` | TEXT | ISO-8601 UTC |
| `last_used` | TEXT NULL | updated on each successful resolve |
| `revoked` | INTEGER | 0/1; a revoked token is refused (FR-008) |

`actor` is a plain name and is **not** a foreign key into the messaging store — the two
stores stay decoupled (NFR-002). A token names who it speaks as; whether that actor exists
is the mailbox's concern at send time, exactly as today.

### `auth_sessions`
| column | type | notes |
|---|---|---|
| `id` | TEXT PK | random session id, set as an HttpOnly cookie |
| `username` | TEXT | FK → `auth_users.username` |
| `created` | TEXT | ISO-8601 UTC |
| `expires` | TEXT | ISO-8601 UTC; past → invalid |

### `auth_meta`
A tiny key/value table for the auth schema version, so it migrates independently of the
mailbox schema.

## Records (frozen dataclasses, `auth/records.py`)

- `User(username, password_hash, totp_secret_enc, enrolment_state, created, last_login)`
- `DeviceToken(id, actor, token_hash, label, created, last_used, revoked)`
- `Session(id, username, created, expires)`

Recovery codes are handled as `(username, code_hash, used)` rows, not a record class.

## State transitions

**User enrolment**
```
(bootstrap or admin-created)  --set-password + verify-TOTP-->  active
must_change_and_enrol ─────────────────────────────────────────┘
```
While `must_change_and_enrol`: the user may log in *only* to complete enrolment; every
other action, and external login, is refused (FR-010).

**Login**
```
password ok? ──no──> generic failure (FR-017)
   │yes
   ▼
enrolled? ──no──> allow only the change+enrol flow
   │yes
   ▼
second factor (TOTP ±1 step, or an unused recovery code) ok? ──no──> generic failure
   │yes
   ▼
create Session, set cookie, stamp last_login
```

**Device token**
```
mint ──> (secret shown once) ──> active ──use──> resolve to actor, stamp last_used
                                    │
                                  revoke ──> refused thereafter (FR-008)
```

## Auth mode (not a table — a setting)

`AUTH_MODE ∈ {off, warn, enforce}` from `AGENT_MAILBOX_AUTH_MODE`.
- `off` → header trusted (today); `hub_info.authenticated = false`.
- `warn` → credentials resolved; missing/invalid logged, request proceeds on the header.
- `enforce` → missing/invalid → 401; `hub_info.authenticated = true`; writes and
  `/observe/*` gated.
