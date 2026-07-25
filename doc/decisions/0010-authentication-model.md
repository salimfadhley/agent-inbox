# ADR 0010 — Two-principal authentication, single-owner, with a grace-mode migration

- Status: Accepted
- Date: 2026-07-25
- Context: `agent-mailbox` — making the hub safe to host on the public internet
- Related: [ADR 0007](0007-authentication-at-the-edge.md),
  [ADR 0008](0008-no-actor-has-authority.md),
  [ADR 0005](0005-one-api-every-client-is-a-client.md)

## Context

The hub trusts whoever claims an identity via the `X-Agent-Name` header — fine on a
trusted LAN, an open door the moment it is reachable from the internet. ADR 0007 already
placed the *responsibility* for proving identity at the edge and kept the engine trusting
its caller; this decision is the concrete realisation of that promise, and it is what lets
the hub be hosted externally.

## Decision

**The hub has two kinds of principal, and they authenticate differently.**

- **Humans** (operators, at the console) authenticate *interactively*: a username and
  password (Argon2id), a TOTP second factor (scan an `otpauth://` QR), and single-use
  recovery codes — yielding a session.
- **Agents** (LLMs, over MCP/CLI) *cannot* do interactive 2FA. They authenticate
  *non-interactively* with a **device token** — a bearer credential minted by a logged-in
  operator, presented as `Authorization: Bearer <token>` on every request. The 2FA does
  not disappear; it moves to the human who mints the token.

**Single-owner.** Every authenticated human is an admin. No roles, no scopes, no per-tenant
isolation, and the messaging rules gain no tenancy dimension. Authentication is a gate at
the front door; what is behind it is unchanged. (Multi-tenant, roles, and SSO are possible
later; they are deliberately out of scope here.)

**The engine does not change.** Auth resolves a *verified* caller at the edge and hands it
down exactly where the header used to be (ADR 0007). `rules.py`, `mailbox.py`, and
`house.py` are untouched; a structural test forbids the import both ways. All new state —
users, credentials, TOTP secrets, recovery codes, device tokens, sessions — lives in a
separate `auth` module with its own `auth_*` tables in the same SQLite file.

## Three modes, so a live hub can migrate without a lockout

Turning authentication straight to *enforce* on a hub that already has agents would lock
every one of them out at once. So the mode is a setting, `AGENT_MAILBOX_AUTH_MODE`:

| mode | behaviour | `hub_info.authenticated` |
|---|---|---|
| `off` | the header is trusted (today's LAN behaviour) | `false` |
| `warn` | credentials are checked; a missing/invalid one is **logged** but the request is served on the header | `false` |
| `enforce` | a missing/invalid credential is refused; writes and `/observe/*` are gated | `true` |

The migration is `off → warn → mint tokens for the existing agents → enforce`. Switching
modes needs no schema change and no data migration. `enforce` is also what finally makes
the `/observe/*` routes safe to expose, closing the M2 FR-010 caveat.

## Bootstrap (Jenkins-style)

There is no one logged in to create the first user, so on startup with an empty users
table the hub creates `admin` with a random ~128-bit password, prints it **once** to the
boot log, and stores only the Argon2id hash. That account lands in a
*must-change-and-enrol* state: it cannot act, or be used for external login, until it has
set a real password and enrolled 2FA. The printed password is therefore one-time.

The bootstrap `admin` **user** is distinct from the reserved `admin` **mailbox** actor
(ADR 0008): different namespaces, different tables, never conflated.

## What a leaked database must not reveal (NFR-001)

- Passwords, device tokens, and recovery codes are stored **only as hashes** (Argon2id for
  the low-entropy password; SHA-256 with a constant-time compare for the high-entropy
  tokens and codes — Argon2 on a 256-bit random token would buy nothing).
- TOTP secrets must be recovered to compute codes, so they are **encrypted at rest**
  (Fernet) with a key from the environment (`AGENT_MAILBOX_SECRET_KEY`), never stored in
  the database. A leaked file yields no usable 2FA seed without that key.

## Consequences

- The hub can be hosted externally behind a TLS-terminating proxy. This ADR secures
  *identity*, not *transport* — bearer credentials assume TLS in front (they are not a
  secret if the connection is plaintext).
- Agents gain a token in `agent-mailbox.toml`; the client sends it automatically. Nothing
  about the messaging model changes for them.
- The console gains a login and enrolment flow but holds no security state — it relays the
  human's session cookie to the hub (ADR 0005: it is a client like any other).
- SSO/OIDC, roles, rate-limiting, and federation server-to-server auth are follow-ups, not
  regressions — each is called out as out of scope in the mission spec.
