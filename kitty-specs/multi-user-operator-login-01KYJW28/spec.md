# Spec - Multi-User Operator Login

> **Audited 2026-08-03 — NOT complete.** Most of this shipped, but requirements
> listed in **issue #43** have no implementation. Read that issue before assuming
> anything here is done.

## What this is

The hub already has password, TOTP, recovery-code, session, and device-token
authentication, but its human account model is still effectively single-owner:
the bootstrap login is the hardcoded `admin` user, every full session is treated as an
operator, and there is no email address or invitation lifecycle for additional humans.

This mission extends the existing authentication layer so one hub can have multiple
human operators. All active humans are admins/operators for now. Account lifecycle is
modelled as **state**, not role: pending-enrolment accounts have no operator powers,
active accounts have full operator powers, and disabled accounts cannot log in. There
is no public self-registration and no role-based authorization in this mission.

The important product change is the bootstrap shape:

1. A fresh hub still prints a random password for `admin` at startup.
2. The first human uses `admin` plus that random password only to enter a limited
   first-run flow.
3. That human must create a real operator account with a chosen username, email
   address, password, and verified TOTP setup.
4. After a real operator exists, the bootstrap `admin` auth user is marked
   `bootstrap_spent`, its sessions are invalidated, and ordinary login is by named
   operator account only.
5. Operators can invite additional operators. Invitees log in with a system-generated
   one-time invite secret, choose their own password, and must complete 2FA enrolment
   before receiving operator powers.

2FA is compulsory whenever hub authentication is enabled (`warn` or `enforce`). There
is no separate "password but no 2FA" mode. An isolated deployment may still opt out of
security by using the existing `AGENT_MAILBOX_AUTH_MODE=off`, and the product should
describe that as a deliberate trusted-environment trade-off.

The reserved `admin` mailbox actor remains a separate standing postbox. It is not the
human login account, and holding or retiring an auth user named `admin` must not change
the reserved mailbox actor.

## Current shape

The existing auth package already supplies the primitives this mission should reuse:

- `User` stores username, password hash, enrolment state, encrypted TOTP secret,
  created, and last-login fields.
- `AuthService.login()` already creates limited sessions for first-run accounts and full
  sessions only after enrolment.
- TOTP enrolment already generates the secret server-side, renders an `otpauth://` URI
  and QR, verifies a returned code, and issues recovery codes.
- `provide_operator()` currently treats any full human session as an operator, which is
  the desired authorization policy for this mission.

The work is therefore a user-lifecycle extension, not a replacement of authentication.
The messaging engine, mailbox rules, ActivityStreams wire model, and agent device-token
model must not learn about human account state.

## User scenarios

1. **Fresh hub first run.** A deployment with an empty auth user table starts. The log
   prints a random `admin` bootstrap password. The first human signs in with `admin`,
   is not allowed into the operator console yet, creates a real username and email,
   chooses a password, scans a TOTP QR, verifies a code, stores recovery codes, and is
   then logged in as the real operator account.
2. **Existing single-admin hub upgrades.** A hub that already has an active `admin`
   auth user does not lock out its operator. On next login, it can continue far enough
   to create a real named operator account and complete/confirm 2FA. Once at least one
   real operator exists, the `admin` bootstrap login is no longer the normal account.
3. **Operator invites another operator.** A signed-in operator opens user management,
   enters a username and email address, and creates an invitation. The system generates
   a one-time invite secret, shown once for delivery out of band. The invited user signs
   in with username + invite secret, chooses their own password, enrols TOTP, and
   becomes an active operator.
4. **Invite not yet enrolled.** An invited account can only reach the enrolment flow.
   It cannot observe mailboxes, purge, mint/revoke tokens, invite users, or otherwise
   act as an operator until TOTP has been verified.
5. **Disable a user.** An operator disables another human account. Existing sessions for
   that account stop working, future login is refused, and other operators and agents
   continue unaffected.
6. **Daily multi-user operation.** Any active human operator can log in with
   username/password/TOTP, see all mailboxes through the console, manage device tokens,
   invite users, reset invited/disabled users according to the supported flow, and act
   as their own `Person` mailbox actor where the console sends or receives mail.
7. **Upgrade recovery.** If the upgrade-time conversion from a single active `admin`
   auth user to a real named operator fails, the deployment-controlled reset channel
   remains available so the operator can re-enter setup without editing database rows by
   hand.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Auth users have a unique `username` and a unique normalized `email` address. Usernames remain the stable login identity; email is stored for account management and future notification/password-reset work. | proposed |
| FR-002 | The system supports more than one human auth user in the same hub database. | proposed |
| FR-003 | All active human users are operators/admins in this mission. There are no effective roles, scopes, tenants, or per-user mailbox visibility limits. | proposed |
| FR-004 | A fresh hub still creates a bootstrap auth user named `admin` with a random generated password printed to the startup log. | proposed |
| FR-005 | A login as bootstrap `admin` grants only a limited first-run session whose required next step is creation of the first real operator account. | proposed |
| FR-006 | The first real operator account creation captures username, email address, chosen password, and verified TOTP enrolment before granting a full session. | proposed |
| FR-007 | Once a real operator account exists, the bootstrap `admin` auth user is marked `bootstrap_spent`, any bootstrap `admin` sessions are invalidated, and future `admin` login fails generically. | proposed |
| FR-008 | Existing deployments with an active single `admin` auth user receive an upgrade-safe path: `admin` can log in far enough to create the first real named operator, but not to continue as the normal operator account. | proposed |
| FR-009 | A signed-in active operator can create an invitation for another operator by specifying at least username and email address. | proposed |
| FR-010 | An invited user receives a system-generated one-time invite secret shown once to the inviting operator; the stored value is hashed and cannot be retrieved later. | proposed |
| FR-011 | First login with a one-time invite secret creates only a limited enrolment session. | proposed |
| FR-012 | A limited enrolment session can only complete account setup: set/confirm password if required, begin TOTP enrolment, verify TOTP, and receive recovery codes. | proposed |
| FR-013 | TOTP setup is generated by the server, shown as an `otpauth://` URI and QR code, and completed only after the user submits a valid current code. Users do not supply raw TOTP secrets. | proposed |
| FR-014 | When auth mode is `warn` or `enforce`, an active user must supply password plus TOTP code or one unused recovery code to obtain a full session. The existing `AGENT_MAILBOX_AUTH_MODE=off` is the only way to disable this security boundary. | proposed |
| FR-015 | Recovery codes remain single-use and per user; rotating/enrolling 2FA replaces that user's recovery-code set only. | proposed |
| FR-016 | A signed-in active operator can list human users with username, email, account state, created time, and last login. Password hashes, TOTP secrets, recovery-code hashes, and invite secrets are never returned. | proposed |
| FR-017 | A signed-in active operator can disable a human account. Disabled users cannot log in, cannot resolve existing sessions, and cannot act as operators. | proposed |
| FR-018 | The system prevents disabling the last active non-bootstrap operator unless an explicit recovery path exists, so the hub is not accidentally locked out. | proposed |
| FR-019 | A signed-in active operator can reset an invited or locked-out user's enrolment state, issuing a new one-time initial secret and clearing that user's existing TOTP secret and sessions. | proposed |
| FR-020 | Human auth users and mailbox actors remain separate namespaces, but each active operator automatically receives a same-name `Person` actor before the account becomes active. | proposed |
| FR-021 | The reserved `admin` mailbox actor remains a standing postbox and is not deleted, disabled, renamed, or granted authority by changes to auth users. | proposed |
| FR-022 | Login failures remain generic to the browser: wrong username, wrong password, wrong second factor, disabled account, and unknown user do not reveal which part matched. Operator logs may remain more specific. | proposed |
| FR-023 | All user-management API routes require a full human session. Agent bearer tokens, shared or otherwise, cannot invite, disable, reset, or list human users. | proposed |
| FR-024 | The console exposes user-management screens for listing users, creating invites, showing the one-time invite secret, disabling users, and resetting enrolment. | proposed |
| FR-025 | The hub descriptor or an auth status route reports whether first-run real-operator setup is required, without exposing the list of users to unauthenticated callers. | proposed |
| FR-026 | If bootstrap or upgrade-time first-operator setup fails, the existing deployment-controlled password reset/user reset channel remains available and documented as the recovery path. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | The auth boundary remains outside the messaging engine. | `rules.py`, `mailbox.py`, `house.py`, and storage rules do not import auth users, sessions, invitations, or email fields. | proposed |
| NFR-002 | A leaked database alone is not enough to impersonate a human. | Passwords, invite secrets, recovery codes, and device tokens are stored only as hashes; TOTP secrets remain encrypted with the configured Fernet key. | proposed |
| NFR-003 | User management avoids accidental lockout. | Tests cover first-user creation, upgrade from existing `admin`, disabling users, and the last-active-operator guard. | proposed |
| NFR-004 | No deployment-specific material is committed. | Specs, docs, tests, examples, and fixtures contain no private hostnames, tokens, real email addresses, or organisation names. | proposed |
| NFR-005 | The console stays a client of the API. | User-management pages call API routes and do not read or write the SQLite database directly. | proposed |
| NFR-006 | Login enumeration resistance is preserved. | Public login responses remain generic across missing user, disabled user, bad password, bad OTP, and bad recovery code. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | No public self-registration in this mission. New human users arrive through bootstrap or invitation by an existing operator. | accepted |
| C-002 | All active humans are operators/admins for now. Role-based authorization is a later mission. | accepted |
| C-003 | Operators can see all mailboxes. There is no per-human mailbox isolation, tenancy, or audit redaction in this mission. | accepted |
| C-004 | TOTP enrolment is mandatory before a user receives a full session. | accepted |
| C-005 | The initial `admin` login is a bootstrap doorway, not the permanent required username. | accepted |
| C-006 | Human auth users and ActivityStreams actors remain different concepts even when they share a visible name. | accepted |
| C-007 | Email delivery is out of scope. Invite secrets are shown once for out-of-band delivery; SMTP or notification work can follow later. | accepted |
| C-008 | SSO/OIDC, passkeys, WebAuthn, passwordless login, and external identity providers are out of scope. | accepted |
| C-009 | The existing device-token authentication model for agents is not redesigned by this mission. | accepted |
| C-010 | The implementation must remain releasable generic infrastructure: no local deployment names, private addresses, or secrets in code, docs, or tests. | accepted |
| C-011 | No partial 2FA bypass flag is added. With auth enabled, 2FA is required; with `AGENT_MAILBOX_AUTH_MODE=off`, the hub is explicitly unauthenticated for isolated/trusted use. | accepted |

## Account states

The exact enum names are implementation detail, but the product states are:

- **bootstrap** — the special startup `admin` auth user, allowed only to create the
  first real operator account.
- **bootstrap_spent** — the startup `admin` auth user after a real operator exists.
  It remains as history/recovery context but cannot log in or hold sessions.
- **invited / must enrol** — a named user exists and has an initial secret, but has not
  completed password + TOTP setup. The user may only use enrolment routes.
- **active** — password and TOTP are established; the user can obtain full operator
  sessions.
- **disabled** — login and session resolution are refused; the account remains visible
  in user management for audit/history.

There is deliberately no effective authorization role in this mission. If a database
column is added for future compatibility, it must not create partial-admin semantics
yet.

## Proposed API shape

Final route naming belongs in the plan, but the required surface is:

- `POST /auth/bootstrap/operator` or equivalent: complete first-run creation of the
  first real operator from a limited bootstrap session.
- `GET /auth/users`: list human users. Operator-only.
- `POST /auth/users`: invite/create a new human user. Operator-only.
- `POST /auth/users/{username}/disable`: disable a human user. Operator-only.
- `POST /auth/users/{username}/reset-enrolment`: reset a user's password/2FA enrolment
  and issue a new one-time secret. Operator-only.
- Existing `/auth/login`, `/auth/enrol`, `/auth/change-password`, and
  `/auth/rotate-2fa` continue to serve normal login and enrolment.

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | From an empty auth database, a human can use the logged `admin` bootstrap password to create a real named operator with username, email, password, and verified TOTP, without editing files or the database. |
| SC-002 | After the first real operator exists, that operator can invite a second operator, and the second operator cannot do anything except enrol until TOTP has been verified. |
| SC-003 | Two active human operators can log in independently and both can use the console's operator views and user-management screens. |
| SC-004 | A disabled user cannot log in and any existing session for that user stops authorizing operator actions. |
| SC-005 | The reserved `admin` mailbox actor remains present and usable as a postbox regardless of what happens to the bootstrap auth user. |
| SC-006 | A browser/client cannot distinguish unknown user, wrong password, wrong OTP, or disabled account from the login response alone. |
| SC-007 | All four quality gates pass: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright`. |

## Assumptions

- Operators trust each other. This mission does not defend one operator from another.
- Email addresses are stored and displayed, but no email is sent by this mission.
- A stable `AGENT_MAILBOX_SECRET_KEY` is already required for durable TOTP enrolments
  and remains required.
- Recovery from losing all operator access can still use the deployment-controlled
  reset path, but normal UI flows should avoid needing it.
- The existing auth migration/workflow can evolve without changing the messaging
  storage schema.

## Out of scope

- Public signup.
- Email verification, SMTP, invite email delivery, or password-reset email delivery.
- Roles, scopes, read-only operators, or owner-only powers.
- Per-user mailbox privacy for humans.
- SSO/OIDC, passkeys, WebAuthn, or external identity providers.
- Changes to agent mailbox identity, message visibility rules, ActivityStreams wire
  shape, or device-token bearer-header semantics.

## Open decisions for plan

1. Whether username and email normalization rules should be stricter than current actor
   name validation. At minimum, uniqueness must be case-insensitive where users would
   reasonably expect it.
2. Whether `bootstrap_spent` should be visible on the Users page as a system account or
   omitted from the ordinary operator list while still represented in storage.

## Proposed work-package slices

| ID | Slice | Acceptance focus |
|---|---|---|
| WP01 | Auth records and store migration | User email/account-state fields, unique indexes, list/create/disable/reset storage operations, migration tests. |
| WP02 | Auth service lifecycle | Bootstrap-to-real-user flow, invitation flow, limited-session restrictions, disabled-user behavior, last-active-operator guard. |
| WP03 | API routes and authorization | Operator-only user-management routes, first-run completion route, generic login failures, no agent-token access to user management. |
| WP04 | Console user management | First-run page, Users page, invite-secret display, disable/reset actions, clear messaging for limited enrolment. |
| WP05 | Actor integration and docs | `Person` actor behavior for operators, reserved `admin` postbox distinction, README/operator docs, upgrade notes. |
| WP06 | Regression and security tests | Multi-user login, invitation, disabled sessions, enumeration resistance, structural auth boundary, quality gates. |
