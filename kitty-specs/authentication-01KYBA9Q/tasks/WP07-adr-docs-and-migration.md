---
work_package_id: WP07
title: ADR, docs, and migration
dependencies:
- WP04
requirement_refs:
- C-008
tracker_refs: []
subtasks:
- T029
- T030
- T031
agent: curator-carla
history: []
agent_profile: curator-carla
authoritative_surface: docs/decisions/0010-authentication-model.md
create_intent: []
execution_mode: code_change
owned_files:
- docs/decisions/0010-authentication-model.md
- src/agent_mailbox/prompts.py
- tests/live/test_live_smoke.py
role: implementer
tags: []
---

# WP07 — ADR, docs, and migration

## ⚡ Do This First: Load Agent Profile

Load your profile with `/ad-hoc-profile-load curator-carla`.

## Objective

Record the authentication model as a binding ADR, tell agents about device tokens in the one
prompt, and add a live-smoke path that exercises login + a device-token round trip against the
real image.

## Subtasks

- **T029 — ADR 0010** (`docs/decisions/0010-authentication-model.md`). Record: the two-principal
  model (humans: password+TOTP+recovery→session; agents: bearer device tokens); auth resolves a
  verified caller at the edge, engine untouched (builds on ADR 0007); single-owner/all-admins,
  no scopes; the three-mode grace migration; secrets hashed, TOTP encrypted at rest with an env
  key; SSO/federation deferred. Follow the house ADR shape (context / decision / consequences).
  No deployment specifics.
- **T030 — prompt** (`prompts.py`). Add a short section: an agent may be issued a **device
  token** by an operator; put it in `agent-mailbox.toml`; it is sent automatically. Keep the
  one-prompt, self-addressed design. Update the console-rendered and `.txt` forms (they share
  the source).
- **T031 — live smoke** (`tests/live/test_live_smoke.py`). Behind the existing `LIVE_HUB_URL`
  gate and a new opt-in (only run when the hub is started with auth): bootstrap-less path where
  the test mints a token via an operator session and confirms a bearer request is accepted and
  an anonymous one is refused under enforce. Keep it skippable so the default smoke run (auth
  off) is unaffected.

## Definition of Done

- ADR 0010 committed under `docs/decisions/`; the prompt mentions device tokens; the live smoke
  gains an auth path that is cleanly skipped when auth is off.
- Charter: no deployment hostnames/IPs/secrets anywhere in these files.
- Four gates green.

## Risks

- Keep the prompt within its budget and self-contained; don't reintroduce a second prompt page.
- The live auth smoke must not break the default (auth-off) CI smoke job — gate it explicitly.
