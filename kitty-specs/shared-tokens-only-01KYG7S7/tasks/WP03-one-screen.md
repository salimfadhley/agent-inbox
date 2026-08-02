---
work_package_id: WP03
title: One screen that lists tokens, not agents
dependencies:
- WP02
requirement_refs:
- FR-001
- FR-008
- FR-010
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T013
- T014
- T015
- T016
- T017
- T018
phase: Phase 3 - the console
agent: python-pedro
history:
- at: '2026-08-02T12:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/console.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/console.py
- tests/test_console.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP03 — One screen that lists tokens, not agents

## ⚡ Do This First: Load Agent Profile

Load `python-pedro` via `/ad-hoc-profile-load` before reading further.

---

## Objective

The screen the mission exists for. Today a shared token cannot be found again at all: the
Tokens screen lists tokens *per agent*, a shared token belongs to no agent, and once the
"shown once" page is closed there is no screen on which it appears. It cannot be reviewed
and cannot be revoked from the console — the operator's only recourse is the database.

## Subtasks

### T013 — `/tokens` lists every token on the hub

Columns: **label**, **issued**, **last used**, **agents admitted**, **Revoke**.

**Last used is the field that makes the screen worth having.** Issued-date tells an
operator a token is old; only last-used tells them it is *dead*. Without it, revoking is a
guess, the safe-feeling choice is to leave every credential alive, and secrets outlive the
machines they were minted for. "Never" must read differently from a date — they are
different facts leading to different actions.

The console is a client and holds no security judgement (ADR 0005): it relays the
operator's session and renders what the hub said. The guard stays on the API route.

### T014 — The mint form

A label, and a Mint button. The secret appears exactly once, with the existing copy button
and the `agent-inbox config set --global token <token>` instruction beside it.

Nothing on this form names an agent. If the label is empty, the hub refuses (WP02) and the
screen reports that refusal — it does not invent a label to avoid the round trip.

### T015 — Revoking says what it cut off

The confirmation names the agents that token had admitted. An operator revoking a
credential is asking exactly one question — *what will this break?* — and the screen is
where it gets answered.

Revoked rows stay in the list, marked, with their history.

### T016 — Remove what is replaced

`/tokens/{name}` goes. The Agents directory's Tokens column goes. Any nav or link into
them goes with them — a link to a page that no longer exists is worse than no link,
because it looks like a fault in the hub rather than a change in the design.

### T017 — Tests

`tests/test_console.py`, extended. The screen renders a token with its label and issue
date; an admitted agent appears against the right token; a revoked token stays listed and
marked; the removed page is gone.

**And the one that matters**: *issued to* and *admitted* render as separate columns. FR-010
is not decoration — a stale label sitting where a fact appears to be is how an operator
revokes the wrong credential, and merging the columns is an easy mistake to make while
tidying a table.

### T018 — Directive 4

One narrow question. The strongest: whether anything the operator typed is rendered
anywhere the page presents observed facts.

## Definition of Done

- The four gates pass.
- Mint, list, revoke all work from the console against an enforcing hub.
- A shared token can be found again after its "shown once" page is closed — the fault this
  mission opened with.
- Claim and finding are visibly separate columns.
- Released and deployed to **both** hubs, proved with `verify-deployment`.

## Reviewer guidance

Open the screen and ask: *could I decide, from this alone, whether it is safe to revoke
this token?* If the answer needs a second screen or a database, the screen has not done its
job.
