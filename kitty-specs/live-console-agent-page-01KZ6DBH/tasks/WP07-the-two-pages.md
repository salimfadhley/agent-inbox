---
work_package_id: WP07
title: The two pages
dependencies:
- WP05
- WP06
requirement_refs:
- FR-007
- FR-008
- FR-009
- FR-010
- FR-011
- FR-012
- FR-019
- FR-021
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T029
- T030
- T031
- T032
- T033
- T034
- T035
agent: python-pedro
history:
- at: '2026-08-04T13:25:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/console.py
create_intent:
- tests/test_console_live.py
execution_mode: code_change
owned_files:
- src/agent_inbox/console.py
- tests/test_console_live.py
role: implementer
tags: []
---

# WP07 — The two pages

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`/realtime`, `/agent/{name}`, the console-origin `/events`, and the absorption of
`/mailbox/{name}`. This is where the mission becomes visible.

## Subtasks

### T029 — `/events` on the console's own origin

The relay's re-emission (WP05), served same-origin so `connect-src 'self'` stands. This
is what the browser subscribes to; it never reaches the API directly.

### T030 — `/realtime`

The hub-wide tab. Fills from `/observe/recent` server-side so the page is useful before
its first event and without JavaScript at all (FR-019), then mounts the feed.

### T031 — `/agent/{name}` and the two panels

**Known to the hub** — address, joined, message counts, `lastSeen`, and `listeningBy` from
`/observe/stats`. `listeningBy` is the one honest liveness signal: *holding a stream*.
`lastSeen` is recency and the page must say so.

**Says of itself** — engine, model, host, project, root, role. Visibly marked
unverified, because the hub stores what the agent says and checks none of it.

Keeping these apart is not decoration. #22 warned that merging them produces "a status
page that looks authoritative while reporting whatever the agent claimed", and the
two-panel design was reached independently in the mockups. Do not flatten them.

**FR-021**: an agent with no profile renders as *nothing declared*, not as empty rows
implying facts were sought and found absent. That is most of the roster.

### T032 — Which token admitted this agent

Read `auth_token_use` (`auth/store.py:257`) agent-first. The table is written token-first
— *which agents has this token admitted* — and this page wants the other direction. Same
table, no new capture.

This is **observed**, so it belongs in the first panel. It is the only genuinely new
observed fact the page gains.

### T033 — Both directions, one feed

`/observe/mailbox/{name}` and `/observe/outbox/{name}` fill it; the stream extends it.

**Direction is computed here, per viewer** — from `attributed_to` against the page's
subject. It is not on the wire, because the same message is "sent" on one agent's page and
"received" on another's (plan §2).

### T034 — Repoint `_mbox_link`, and keep the mailbox

`_mbox_link` is the single place every table builds an agent link. Point it at
`/agent/{name}` and its callers need no change.

**`/mailbox/{name}` keeps answering.** Existing links and anyone's bookmark point at it,
and it becomes a link *from* the agent page rather than a second front door. Deleting it
would break links this change has no need to break.

### T035 — Tests

In `tests/test_console_live.py`:

- **Assert against the rendered page, not a helper.** A console test here once exercised a
  helper rather than the rendered page and so could not tell a working guard from a
  missing call. Fetch the page; assert on its HTML.
- `/mailbox/{name}` still answers, and the agent page links to it.
- Every agent link points at the agent page.
- The two panels are distinguishable in the markup, and the claimed one is marked.
- An agent with no profile renders *nothing declared* — and **the paired positive**: an
  agent with a profile renders its facts. Without that pair, a page that rendered nothing
  for everybody would pass.
- Both directions appear, and each row names the other party.
- The CSP header is unchanged.
- Watching consumes nothing: unread counts before and after are equal.

## Definition of Done

- Both pages work with JavaScript disabled, degraded to a served table.
- Every previously working link still works.
- The four gates pass.

## Reviewer guidance

Two things worth being unkind about: whether any test asserts on a helper instead of the
page, and whether a claimed fact can reach the observed panel. Both are silent failures.

## After this package

Ship 2 is complete. Release, deploy, prove with `verify-deployment`, then close #46 and
#51.
