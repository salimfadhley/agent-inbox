---
work_package_id: WP02
title: 'Retrying delivery: classify the failure, retry only the world'
dependencies:
- WP01
requirement_refs:
- FR-001
- FR-002
- FR-004
- FR-005
- FR-006
- NFR-001
- NFR-003
- NFR-004
tracker_refs: []
planning_base_branch: kitty/mission-retry-delivery-to-a-sleeping-peer
merge_target_branch: kitty/mission-retry-delivery-to-a-sleeping-peer
branch_strategy: Planning artifacts for this mission were generated on kitty/mission-retry-delivery-to-a-sleeping-peer. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into kitty/mission-retry-delivery-to-a-sleeping-peer unless the human explicitly redirects the landing branch.
subtasks:
- T005
- T006
- T007
- T008
- T009
- T010
phase: Phase 2 - The mission
agent: python-pedro
history:
- at: 2026-07-31T16:40:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/retry.py
create_intent:
- src/agent_inbox/retry.py
- tests/test_delivery_retry.py
execution_mode: code_change
owned_files:
- src/agent_inbox/retry.py
- tests/test_delivery_retry.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP02 – Retrying delivery: classify the failure, retry only the world

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro`
- **Role**: `implementer`
- **Agent/tool**: `python-pedro`

If no profile is specified, run `spec-kitty agent profile list` and select the best match
for this work package's `task_type` and `authoritative_surface`.

---

## Objective

A message to a peer that is **unreachable** is retried with bounded backoff until it
arrives or the bound is spent. A message we **refused** to send is never retried.

## The one rule this package must not break

> Authorization is re-derived on every attempt and never carried from queue time.

This is FR-050 of the parent federation spec — the finding from the very first outside
review. Step 6 could not violate it because there was no interval between deciding and
sending. **You are creating that interval.**

The guard already exists, in the right place:

```python
# FederatedDelivery.deliver — do not change this, and do not go around it
settings = await self.mailbox.hub_settings()   # read now
peers    = await self.mailbox.peers()          # read now
await asyncio.to_thread(outbound.deliver, ..., settings=settings, peers=peers)
```

`outbound.deliver` raises `DeliveryRefused` if federation is off or the peer is not trusted.

**Therefore: every retry re-calls `RemoteDelivery.deliver` and passes no decision into it.**
Never call `outbound.deliver` from the retry loop. Never cache `settings` or `peers`. Never
store "this peer was allowed" alongside the queued item.

Get this right and FR-002 and FR-005 are structural — enforced by code you did not write.
Get it wrong and every happy-path test still passes.

## The distinction the original sketch missed

Two exceptions, opposite meanings:

| Failure | Is | Retry? |
|---|---|---|
| `DeliveryRefused` | **our** decision — federation off, peer untrusted | **Never.** Terminal |
| connection refused, timeout, DNS failure, 5xx | the world, and it may pass | Yes, until the bound |
| 4xx from the peer | the peer rejecting this message | **Never.** They will not change their mind |

Retrying a refusal would be the hub arguing with its own configuration for five minutes,
and would make a withdrawal of trust take five minutes to take effect instead of happening
at the next attempt.

## Subtasks

### T005 — `Queued` signal and the failure taxonomy

New module `src/agent_inbox/retry.py`.

- A `Queued` exception (or equivalent signal) carrying the recipient, so the caller can
  mint a `queued` receipt rather than a failed one.
- A predicate that classifies an exception as retryable or terminal, per the table above.

Make the predicate **explicitly allow-list what is retryable** rather than deny-list what is
not. An unrecognised exception should be terminal: retrying something we do not understand,
against somebody else's server, five more times, is the wrong default.

### T006 — `RetryingDelivery`

A `RemoteDelivery` that wraps another and adds a queue.

- `resolve` and `actor_uri` delegate, untouched.
- `deliver` attempts **once, inline**. Success returns. A terminal failure re-raises. A
  retryable failure enqueues and raises `Queued`.

The inline first attempt is NFR-002: the caller waits for one attempt, never for the window.

Take the wrapped delivery as a constructor argument. It satisfies the same Protocol, so
`House` needs no knowledge that retrying exists.

### T007 — The retry loop

Backoff `2s, 8s, 30s, 60s, 90s` after the inline attempt — six attempts total (3m10s worst
case), then give up and mark failed (FR-006). Strictly increasing (NFR-004).

NFR-001's five minutes is a **ceiling the schedule fits under**, not a figure to round to.
An earlier draft ran to 7m40s and explained the overshoot in prose; analysis finding A1
rejected that.

**One asyncio task per queued delivery.** Per-peer independence (NFR-003) then costs
nothing: two peers cannot block each other because they were never sharing anything. At the
volume this hub sees, a worker pool would be machinery guarding against a problem we do not
have.

Be clear about what this permits: ten messages waiting for one sleeping peer produce **ten
concurrent attempts**. That was decided deliberately on 2026-07-31, and NFR-004 is worded
per-message rather than per-peer to match. Do not add a per-peer lock without changing the
NFR first.

Reuse the recipient resolved at queue time (C-002) — do not re-run WebFinger. Within five
minutes an actor has not moved, and re-resolving would multiply traffic against a peer that
is already failing. **This is the only thing a retry may reuse.**

### T008 — Terminal on refusal: the removal proof for FR-004

Test that a `DeliveryRefused` is not retried.

**This passes trivially if nothing is ever retried.** Prove it properly: first show a
retryable failure *is* retried (so the loop demonstrably runs), then show the refusal is
not. Then delete the terminal branch and watch this test fail. If it still passes, it is
testing nothing.

### T009 — Re-derived authorization: the removal proof for FR-002 and FR-005

The most important test in the mission.

Queue a delivery while the peer is trusted. **Then remove the peer** (or switch federation
off). The next attempt must refuse and the message must fail.

This passes trivially if the retry never fires. Prove it by removal: make the retry cache
`settings`/`peers` from queue time and watch this test fail. If it still passes, you are
testing the absence of a queue.

### T010 — Backoff and bound tests without real waiting

The bound is minutes; the test suite must not be. Inject the sleep (or the clock) so the
schedule can be asserted without elapsing.

Assert the *schedule*, not just the count: a bug that retries six times immediately would
pass a count-only test and hammer a struggling peer, which is exactly what NFR-004 forbids.

## Definition of Done

- [ ] A delivery failing twice then succeeding arrives, and the caller never waited for it
- [ ] A refusal is terminal, proved by removal
- [ ] Trust withdrawn mid-queue prevents delivery, proved by removal
- [ ] The bound is enforced and the message ends `failed` with a reason distinguishing
      "unreachable throughout" from "refused"
- [ ] `outbound.deliver` is not called anywhere in this module — grep for it and confirm
- [ ] No `settings` or `peers` value is stored on a queued item — grep and confirm
- [ ] Backoff strictly increasing, asserted as a schedule
- [ ] The four charter gates green, each exit code captured separately:
      `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
      `uv run pyright`. **There is no `black` in this project** — piping a gate to
      `tail` and reading `$?` gives you the pipe's status, not the tool's.

## Risks

The safety property is invisible in normal operation. Everything in this package works
identically whether or not authorization is re-derived, **until the day someone withdraws
trust from a peer and mail goes to them anyway.** T009 is the only thing standing between
this design and that outcome; treat a passing T009 with suspicion until you have watched it
fail.
