---
work_package_id: WP06
title: Client token support
dependencies:
- WP04
requirement_refs:
- FR-007
- FR-015
tracker_refs: []
subtasks:
- T026
- T027
- T028
agent: python-pedro
history: []
agent_profile: python-pedro
authoritative_surface: src/agent_mailbox/client.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_mailbox/client.py
- src/agent_mailbox/mcp_client.py
- tests/test_client.py
role: implementer
tags: []
---

# WP06 — Client token support

## ⚡ Do This First: Load Agent Profile

Load your profile with `/ad-hoc-profile-load python-pedro`.

## Objective

The agent side. The stdlib client sends its device token as a bearer header and stores it in
`agent-mailbox.toml`; the MCP client threads it through. Stdlib-only on the client (no new
deps).

## Subtasks

- **T026 — bearer + config** (`client.py`). `Config` gains an optional `token`. `HubClient._call`
  adds `Authorization: Bearer <token>` when present (alongside, or instead of, the identity
  header). `write_config` persists `token` under the hub/engine section — reuse the existing
  safe-write path (escape values, atomic write; this module has had escaping/atomicity bugs
  before — do it correctly). `load_config` reads it back.
- **T027 — MCP + join** (`mcp_client.py`, `client.py`). The MCP tools use the token-bearing
  client. If `join`/registration returns (or is given) a device token, record it into the
  config so a subsequent session authenticates automatically.
- **T028 — tests** (`tests/test_client.py`). A token in `Config` produces the bearer header;
  `write_config`→`load_config` round-trips a token with special characters intact and does not
  drop other keys; a client with no token still works (off/warn hubs).

## Definition of Done

- Bearer header sent when a token is configured; config round-trips it safely.
- No new runtime dependency on the client side.
- Four gates green.

## Risks

- `agent-mailbox.toml` writing is a known past defect area (unescaped TOML, non-atomic,
  dropped keys). Reuse/keep the corrected write path and test the special-character case.
