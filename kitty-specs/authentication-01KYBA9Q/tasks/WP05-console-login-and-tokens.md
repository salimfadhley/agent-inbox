---
work_package_id: WP05
title: Console login and token management
dependencies:
- WP04
requirement_refs:
- FR-010
- FR-013
- FR-016
tracker_refs: []
planning_base_branch: feat/authentication
merge_target_branch: feat/authentication
branch_strategy: Planning artifacts for this mission were generated on feat/authentication. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/authentication unless the human explicitly redirects the landing branch.
subtasks:
- T021
- T022
- T023
- T024
- T025
agent: python-pedro
history: []
agent_profile: python-pedro
authoritative_surface: src/agent_mailbox/console.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_mailbox/console.py
- tests/test_console.py
role: implementer
tags: []
---

# WP05 — Console login and token management

## ⚡ Do This First: Load Agent Profile

Load your profile with `/ad-hoc-profile-load python-pedro`.

## Objective

The human-facing side. The console gains a login, a forced first-run change+enrol flow with
the QR, an account page, and device-token pages — carrying the session to the hub and holding
no security state of its own.

## Subtasks

- **T021 — login/logout** (`console.py`). `GET /login` renders a form; `POST /login/submit`
  (distinct path — the Litestar sync GET+POST-same-path quirk 500s otherwise) calls the hub's
  `/auth/login` and relays the `Set-Cookie` session to the browser. `POST /logout/submit`
  clears it. When the hub is in `enforce` and the operator is not logged in, the observe pages
  redirect to `/login`.
- **T022 — forced enrol** (`console.py`). If login returns `next=enrol`, land on an enrolment
  page that shows the inline QR (from the hub's `/auth/enrol`) and recovery codes, takes a new
  password + a confirming code, and posts to `/auth/enrol`. On success, proceed to the
  overview.
- **T023 — account** (`console.py`). `GET /account` with change-password and rotate-2fa forms
  (distinct POST paths), each relaying to the hub.
- **T024 — token pages** (`console.py`). On a mailbox/agent view, a "device tokens" section:
  list tokens (metadata), a mint form (shows the secret **once**, with a copy control like the
  prompt page), and a revoke button per token. All via the hub's token endpoints, as the
  operator session.
- **T025 — tests** (`tests/test_console.py`). Extend the StubHub with the auth endpoints:
  logging in relays the cookie; an `enforce` hub with no session redirects observe pages to
  login; minting shows the secret once; revoke calls the hub. Keep the existing console tests
  green.

## Definition of Done

- Login → (forced enrol) → overview works against a stub; token mint/list/revoke pages work.
- No security state stored in the console beyond the in-flight cookie relay.
- Distinct GET/POST paths everywhere (no shared-exact-path handlers). Four gates green.

## Risks

- The session relay: the browser holds the cookie; the console forwards it to the hub. Keep it
  simple — the console is a pass-through, not a session store.
- Don't regress the existing console/prompt behaviour (tests pin it).
