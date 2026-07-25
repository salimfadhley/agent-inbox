# Spec — Single-Owner Authentication

## What this is

The hub trusts whoever claims an identity. Today the caller's name arrives in a header
and is taken at face value — fine on a private LAN, an open door the moment the hub is
reachable from the internet. This mission adds **authentication** so the owner can host
it publicly.

The shape is settled and follows from one fact: the hub has **two kinds of principal, and
they cannot authenticate the same way.**

- **Humans** (operators, at the console) can authenticate *interactively*: a username and
  password, plus a second factor from a phone authenticator app (TOTP), plus recovery
  codes for a lost phone. That yields a **session**.
- **Agents** (LLMs, over MCP/CLI) *cannot* do interactive 2FA — an LLM can't scan a QR or
  read a rotating code. They authenticate *non-interactively* with a **device token**: a
  bearer credential minted by a logged-in operator, presented on every request. The 2FA
  does not vanish; it moves to the human who mints the token.

This is deliberately **single-owner**: every authenticated human is an admin. There are no
roles, no scopes, no per-user isolation, and the messaging rules gain no tenancy
dimension. Authentication is a gate at the front door; what is behind it is unchanged.

## The engine does not change

[ADR 0007](../../docs/decisions/0007-authentication-at-the-edge.md) already made
identity an explicit argument that the **edge** is responsible for proving — the engine
takes a `caller` and never trusts ambient state. Today the edge trusts the
`X-Agent-Name` header. This mission replaces "trust the header" with "resolve a **verified**
principal from a credential, then pass that same `caller` down." The pure rules
(`rules.py`), the mailbox, and the House are untouched. Almost everything here is *new*
state at the boundary — users, credentials, TOTP secrets, sessions, device tokens,
recovery codes — plus middleware that checks them. This is why the security state lives in
the API, and why the stateless console keeps holding none of it.

## The two-principal model, on the wire

- A human logs in → password → second factor (TOTP or a recovery code) → a session the
  console carries to the API on the human's behalf.
- An agent presents `Authorization: Bearer <device-token>`; the API resolves the token to
  the agent's actor name and uses it as `caller`, exactly where `X-Agent-Name` sits today.

A device token *is* its agent's identity — there are no read-only vs full tokens. Per
device, so one machine can be revoked without unmaking the identity.

## The bootstrap (Jenkins-style)

There is no one logged in to create the first user, so the system seeds itself. On startup
with an **empty users table**, it creates a user named `admin` with a random strong
password, prints that password **once** to the boot log, and stores only the hash — the
same move Jenkins makes with its initial admin password.

That printed secret is **one-time**. The bootstrap account lands in a *must set a real
password and enrol 2FA* state; until both are done it cannot be used for external login or
sensitive actions. You read the log once, log in, are walked straight through the QR, and
the printed password is dead.

The bootstrap `admin` **user** is a separate concept, in a separate table, from the
reserved `admin` **mailbox** actor (the standing resident agents write to about the
system). They share a name across different namespaces and must never be conflated.

## Turning it on without a lockout (grace mode)

The live hub already has real agents on it. Flipping authentication to *enforce* would
lock every one of them out at once. So auth has three modes:

- **off** — today's behaviour; the header is trusted; the hub reports itself unauthenticated.
- **warn** — credentials are checked; a missing or invalid one is **logged** but the
  request still proceeds. This is the migration window: the operator mints device tokens
  for the agents already on the hub and watches the warnings drain to zero.
- **enforce** — a missing or invalid credential is refused. The hub reports itself
  authenticated; write paths and `/observe/*` become gated.

Switching modes needs no schema change and no data migration — it is a setting. This is
also what finally lets `/observe/*` be exposed safely, closing the
[M2 FR-010](../the-api-01KYADKK/spec.md) "unguarded privileged surface" caveat: an
operator's login is what unlocks the operator's view.

## User scenarios & testing

1. **First run.** A fresh database boots. The operator finds the `admin` password in the
   boot log, logs into the console, is required to set a real password and to scan a QR
   into their authenticator, confirms with a code, and is handed recovery codes. No file
   or database editing anywhere.
2. **Provisioning an agent.** A logged-in operator mints a device token for an agent, sees
   the secret exactly once, and hands it to the agent. The agent stores it and sends mail.
3. **Daily agent use.** The agent presents its token on every call and behaves exactly as
   before — join, send, read, observe-nothing-it-shouldn't. Nothing else about the agent
   changes.
4. **Revocation.** A device token is suspected compromised. The operator revokes it; that
   device is refused on its next call; every other agent and token is unaffected.
5. **Migrating the live hub.** The operator switches to *warn*, mints tokens for the agents
   already present, watches the warnings go quiet, then flips to *enforce* — with no agent
   losing access mid-flight.
6. **Gated observation.** With auth enforced, an anonymous request to a mailbox view or the
   stats page is refused; the operator's session is what makes those pages work.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Authentication has three modes — **off**, **warn**, **enforce** — selectable by configuration. `off` trusts the header (today's behaviour); `warn` checks credentials and logs a missing/invalid one but still serves the request; `enforce` refuses a missing/invalid credential. | proposed |
| FR-002 | A human authenticates with a username and password; the pair is verified against a stored hash, never a stored password. | proposed |
| FR-003 | 2FA enrolment issues a per-user TOTP secret as an `otpauth://` URI rendered as a scannable QR, and completes **only** after the human returns a valid code from their authenticator — proving the app is set up. | proposed |
| FR-004 | Once enrolled, a human must present a current TOTP code (or a recovery code) **in addition to** the correct password to obtain a session. | proposed |
| FR-005 | Recovery codes are issued at enrolment; each is single-use; presenting one satisfies the second factor for that login and is then spent. | proposed |
| FR-006 | A logged-in operator can mint a device token for a named agent; the token secret is shown **exactly once** and is never retrievable afterward. | proposed |
| FR-007 | An agent authenticates by presenting its device token as `Authorization: Bearer …`; the hub resolves it to that agent's actor identity and uses it as the `caller` — the same value the header supplies today. | proposed |
| FR-008 | An operator can list an agent's device tokens (metadata only — label, created, last used — never the secret) and revoke any one; a revoked token is refused on its next use. | proposed |
| FR-009 | On startup with no human user present, the system creates a user `admin` with a randomly generated password, prints that password **once** to the boot log, and persists only its hash. | proposed |
| FR-010 | The bootstrap admin — and any account created without a chosen password — is in a *must set a real password and enrol 2FA* state, and cannot perform sensitive actions or be used for external login until both are complete. | proposed |
| FR-011 | Under **enforce**, every write path and every `/observe/*` route requires a valid credential (a human session or a device token); the caller-gated read semantics that already exist are unchanged. | proposed |
| FR-012 | The hub descriptor (`GET /`) reports `authenticated: true` under enforce and `false` otherwise, truthfully for the active mode. | proposed |
| FR-013 | The console authenticates the human once and carries that session to the API on their behalf; it stores no security state of its own beyond the in-flight session. | proposed |
| FR-014 | Every authentication decision is made at the API edge and resolves to the `caller` the engine already accepts; no messaging rule, the mailbox, or the House changes. | proposed |
| FR-015 | While in **warn** mode, an operator can mint device tokens for agents already on the hub, so the live deployment can reach **enforce** without any agent being locked out. | proposed |
| FR-016 | An authenticated human can change their password and rotate (re-enrol) their 2FA and recovery codes from within a session. | proposed |
| FR-017 | A failed login does not reveal whether the username or the password was wrong; both yield the same generic refusal. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | A leaked database alone is not enough to impersonate anyone. | A full dump of the SQLite file reveals **no** password, **no** usable device token, and **no** usable TOTP seed: passwords/recovery-codes/tokens are stored only as hashes, and TOTP secrets are encrypted at rest with a key supplied by the environment (not stored in the database). | proposed |
| NFR-002 | Authentication adds no messaging logic. | A structural test: the engine and rules modules do not import or reference users, tokens, or sessions; the security layer lives only at the edge. | proposed |
| NFR-003 | Per-request auth is cheap. | Resolving a device token is a single indexed lookup plus a hash compare; the expensive password hash runs only at login, never per request. | proposed |
| NFR-004 | Enabling auth is reversible and observable. | Switching modes needs no schema change and no data migration; **warn** logs every request that would fail under **enforce**, so the migration can be watched to zero. | proposed |
| NFR-005 | The bootstrap password is unguessable. | ≥128 bits of entropy from a cryptographically secure generator. | proposed |
| NFR-006 | Second-factor verification tolerates real-world clocks but not replay. | A TOTP code is accepted within a small time window (±1 step) and a recovery code is refused after its first use. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | Single-owner only: all authenticated humans are admins. No roles, no scopes, no per-user isolation, no tenancy dimension in the rules — this mission. | accepted |
| C-002 | SSO/OIDC is out of scope; it is a later mission. Humans use password + TOTP only. | accepted |
| C-003 | Device tokens carry no scopes — a token is its agent's full identity. | accepted |
| C-004 | No federation and no server-to-server auth (HTTP signatures) in this mission. | accepted |
| C-005 | The bootstrap `admin` **user** is distinct from the reserved `admin` **mailbox** actor; the namespaces must not be conflated. | accepted |
| C-006 | No deployment-specific hostnames, IPs, or secrets in the repo (charter). The TOTP encryption key and any bootstrap material come from the environment. | accepted |
| C-007 | All persistent security state lives in the API layer; clients and the console hold none. | accepted |
| C-008 | An Architecture Decision Record for the authentication model is a deliverable of this mission. | accepted |
| C-009 | This mission secures **identity**, not transport. Bearer credentials assume TLS is terminated in front of the hub by the hosting layer; the hub does not itself provide TLS. | accepted |

## Key entities

- **User** — a human operator. Holds a username, a password hash, an (encrypted) TOTP
  secret, an enrolment state (`must_change_and_enrol` vs `active`), and hashed recovery
  codes. Every user is an admin.
- **Session** — a human's authenticated state after password + second factor; carried by
  the console to the API. Has a lifetime.
- **DeviceToken** — a bearer credential belonging to one agent actor. Holds a token *hash*,
  a label, created/last-used timestamps, and a revoked flag. No scope.
- **AuthMode** — a single hub-level setting: `off | warn | enforce`.

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | From an empty database, an operator can find the admin password in the boot log, log in, set a real password, and finish 2FA by scanning a QR — in one sitting, touching no files and no database. |
| SC-002 | With auth enforced, a request bearing no credential (or a revoked/invalid one) to a write or observe route is refused; the identical request with a valid credential succeeds. |
| SC-003 | An agent holding a valid device token sends and reads mail exactly as before; revoking that token stops that device on its next call and affects no other agent. |
| SC-004 | The live hub is moved from unauthenticated to enforced with no agent losing access mid-flight, by going through warn mode and minting tokens first. |
| SC-005 | A copy of the database alone lets an attacker log in as nobody, use no device token, and generate no user's 2FA codes. |
| SC-006 | The hub truthfully reports, at `GET /`, whether it is authenticated. |

## Assumptions

- The operators are trusted; the threat model is the public internet and a leaked database,
  not a malicious insider (which is what "single-owner, all admins" assumes).
- One authenticator app per human is sufficient; recovery codes cover device loss.
- The hosting environment can supply a **stable** secret key across restarts for encrypting
  TOTP secrets; losing it means re-enrolling 2FA, not losing accounts.
- TLS is terminated by a reverse proxy in front of the hub (see C-009).
- The existing live agents can each be issued a device token during the warn window before
  enforce is turned on.

## Out of scope (non-goals)

- SSO / OIDC (a later mission).
- Roles, permission scopes, per-user or per-tenant isolation.
- Federation and server-to-server authentication.
- Transport security (TLS) — delegated to the hosting layer.
- Rate limiting / brute-force lockout beyond the generic-failure requirement (a candidate
  follow-up, not required here).

## Edge cases

- **Lost authenticator and no recovery codes** → recovery needs another admin to re-enrol
  the account, or a re-bootstrap; documented, not silently unrecoverable.
- **Users table emptied** → the next startup re-bootstraps a fresh `admin` password to the
  log; existing agents and their tokens are unaffected (separate namespace).
- **Clock skew** → a TOTP code just outside the current step is still accepted within the
  ±1-step window; further out is refused.
- **Enforce flipped before tokens are minted** → agents are locked out; this is exactly the
  failure warn mode and the migration procedure exist to prevent.
- **A bearer token over plain HTTP** → leaks the credential; C-009 makes TLS-in-front an
  explicit assumption, and the risk is stated rather than hidden.
- **Console session expiry mid-use** → the operator is returned to login; no partial
  privileged state persists.
