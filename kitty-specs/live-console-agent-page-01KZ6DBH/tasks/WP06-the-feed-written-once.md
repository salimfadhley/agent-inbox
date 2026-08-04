---
work_package_id: WP06
title: The feed, written once
dependencies: []
requirement_refs:
- FR-013
- FR-014
- FR-015
- FR-016
- FR-018
- FR-020
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T023
- T024
- T025
- T026
- T027
- T028
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/static/feed.js
create_intent:
- src/agent_inbox/static/feed.js
- src/agent_inbox/static/feed.css
- tests/test_feed_asset.py
execution_mode: code_change
owned_files:
- src/agent_inbox/static/feed.js
- src/agent_inbox/static/feed.css
- tests/test_feed_asset.py
role: implementer
tags: []
---

# WP06 — The feed, written once

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

The component both pages mount: rows, the direction rail, the wash, the self-ageing clock,
the head-row state display, the subscription, and the filter pills. Written once, because
building it twice is the reason #46 and #51 are one mission.

## Design — settled, not open

Chosen by the owner across four rounds of mockups on 2026-08-04. Build this, do not
redesign it.

- **Two-line rows.** Correspondent and relative time on a mono line; subject beneath at
  reading size. Long subjects are not truncated — that is why this shape won.
- **Blue in, amber out.** Light `--in: #2F6F9E` / `--out: #A8710F`; dark `--in: #74B4E6` /
  `--out: #DFAA46`. A complementary pair that survives the common colour-vision
  deficiencies, unlike a ledger's red/green.
- **The wash**: `color-mix(in srgb, var(--accent) 11%, transparent)` (14% dark), decaying
  to transparent with a slight downward settle.
- **Times**: `just now → 12s → 4m → 14:32`, absolute time on hover.

## Subtasks

### T023 — Rows, rail, and direction in words

Two-line rows with a coloured rail at the left edge. **Colour is never the only cue** —
every row also carries `from` or `to` in words (FR-013). Someone who cannot separate the
hues still reads the direction.

The row names **the other party**: on an agent's page the agent is a given, so received
rows name the sender and sent rows name the recipient.

### T024 — The wash, and reduced motion

The arrival wash, tinted to direction. Under `prefers-reduced-motion`, the row still
distinguishes itself as new — the console already uses `font-weight: 600` for unread, which
is the existing vocabulary — but it does not move.

### T025 — Times that age themselves

Re-render on a timer so the page keeps moving when the hub does not. This is half of why a
stale page is visible as stale.

### T026 — The head row shows state, and never infers it

Render exactly the three states the relay publishes: **open**, **reconnecting**, **lost**.

**Never conclude health from silence.** No "we have not heard anything, so it is probably
fine", and no timer that decides a feed is dead. The relay says; the page shows.

### T027 — Subscribe, same-origin

`EventSource` at the console's own `/events`. No external host — `connect-src 'self'` must
stand unchanged. An event of an unknown type is ignored rather than rendered (FR-020), so
the hub can add one without breaking an older console.

### T028 — Filter pills

All / Received / Sent, used by the agent page and not by the realtime tab. Arrivals in a
hidden direction are retained, not dropped, so switching back shows them.

## Constraints

- **Vendored only.** No CDN, no build step, no framework. `STATIC_DIR` already holds
  vendored assets and the comment there says "never a CDN".
- Both colour schemes: `prefers-color-scheme` plus the `data-theme` overrides the console
  already uses.
- Subjects and correspondents only. **Never a message body.**

## Tests — T029 lives in WP07, so what can be tested here?

In `tests/test_feed_asset.py`, assert the things that are checkable without a browser and
that a later refactor could silently break:

- The asset is served from the vendored static directory and references no external host.
- Both direction hues are defined for both colour schemes.
- A `prefers-reduced-motion` block exists and disables the movement.
- All three connection states appear as distinct rendered strings — so a build that
  dropped one is caught.

This is deliberately modest. The behavioural proof of the head row is WP05's (the relay
publishes) and WP07's (the page renders what it is given).

## Definition of Done

- One component, parameterised enough to mount twice.
- No external request, no build step, no new dependency.
- The four gates pass.

## Reviewer guidance

Search the JavaScript for any timer that changes connection state. There should be exactly
none: the only timer here ages the clock.
