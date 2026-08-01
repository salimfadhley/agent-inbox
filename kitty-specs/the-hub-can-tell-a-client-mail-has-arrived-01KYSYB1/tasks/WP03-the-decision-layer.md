---
work_package_id: WP03
title: The decision layer, and the promise that changes
dependencies:
- WP02
requirement_refs:
- FR-010
- FR-011
- FR-012
- FR-013
- FR-014
- FR-015
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
phase: Phase 3 - The decision layer
agent: python-pedro
history:
- at: '2026-08-01T20:55:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/interrupt.py
create_intent:
- src/agent_inbox/interrupt.py
- tests/test_interrupt_policy.py
execution_mode: code_change
owned_files:
- src/agent_inbox/interrupt.py
- src/agent_inbox/prompts.py
- tests/test_interrupt_policy.py
- doc/**
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP03 – The decision layer, and the promise that changes

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro` · **Role**: `implementer` · **Agent/tool**: `python-pedro`

---

## Objective

Between being told mail exists and interrupting an agent there is a **decision**, and it
belongs to the recipient. Default-deny, gated on who sent it rather than what they claimed,
rate-limited, and inspectable.

And the sentence every agent has been given — *"mail cannot reach you mid-turn: you see it
only when you look"* — stops being unconditionally true, so it stops being said
unconditionally.

## The rule this exists to enforce

**Priority claimed by a sender is not priority.**

If a message can make itself interrupting — by subject, by a flag, by saying URGENT — then
every message becomes urgent, and the mailbox has handed senders a lever over the
recipient's attention. That is ADR 0008 (*no actor has authority over the mailbox*) arriving
at the last layer, and it is the failure to design against.

The decision reads:

- **who it is from**, against the recipient's own configuration — a wake is gated on the
  *reader's* trust, never the writer's claim;
- **what else is happening** — mid-turn, idle, between sessions;
- **what has happened recently** — an agent interrupted five times in a minute has been
  denial-of-serviced by anyone who can send mail.

It must not read anything the **sender** controls as a priority signal. Subject and sender
are shown so the *agent* can decide what to do; they are not inputs to whether it is
disturbed.

## Context you need before you start

**Why this is client-side, and it is not only the ADR.** Claude Code, Codex and OpenCode do
not share a way of being interrupted, and what is even *possible* differs between them — one
may accept an event into a running session, another may only be able to leave something for
the next turn. A hub deciding when to interrupt would have to know what harness each
recipient runs, track which are running, and carry a per-harness strategy, every one of
which goes stale the day a new harness appears.

**Delivery is not yours.** `live-session-push-01KYCGZ1` owns the wake adapter — the thing
that actually reaches into a session. This WP decides *whether* and *when*; it hands the
answer to an adapter seam. Do not build the adapter here.

**The default must be indistinguishable from today.** FR-012 is not a nicety: every existing
agent was given a guarantee, and a release that quietly starts interrupting them has broken
it. Default configuration interrupts for nobody.

## Subtasks

### T013 — The decision layer

New module `src/agent_inbox/interrupt.py`. A **pure function** at its heart — event plus
configuration plus recent history in, decision plus reason out — with the I/O somewhere
else. `wake.py` already has this shape (`wake_response` is pure, `run` is the fail-silent
wrapper) and it is why that module is testable without a network. Follow it.

- Gated on **sender identity** against the recipient's configuration.
- **Default-deny.** No configuration at all means no interruption, ever.
- Configuration lives client-side, beside the existing per-project config the client already
  reads. The review flagged this as a deliberate deferral (U1); settle it here and say where
  it lives in the docs.

### T014 — The rate limit

An agent that can be woken without bound has been handed to whoever sends most. Cap the
wakes per unit time, and **report the cap when it bites** — a limit that silently swallows
things is one nobody can debug. Twenty messages in a minute must produce a bounded number of
wakes and a record saying the rest were capped.

### T015 — Every decision recorded with its reason

FR-014: what arrived, what was chosen, and why. An interrupt policy nobody can inspect is
one nobody can trust or debug — and this is the layer most likely to be blamed for
behaviour it did not cause.

The reason must distinguish *"sender not trusted"* from *"rate limited"* from *"no adapter
available"*. All three look identical from outside, and they need different fixes.

### T016 — FR-011 proved by removal

The spec asks for this one specifically, and it is the most valuable test in the mission:

> stand up a sender that claims urgency, confirm no wake, then remove the guard and watch a
> subject line move the recipient's attention.

Both halves. A test asserting "an alarming subject did not wake" passes just as well against
code that never wakes anybody at all — so it proves nothing unless you have also shown the
same test failing when the guard is gone. Record that you ran the removal.

Two cases, adjacent on purpose:

- an alarming subject from a sender **not** trusted to interrupt → **no wake**;
- the **same subject** from a sender who is → wake.

That pairing is what shows the gate is on identity, not on text.

### T017 — The documentation stops promising what is no longer true

FR-015. The promise appears in **two** places, and the analysis found that this WP owns only
one of them:

- `src/agent_inbox/mcp_client.py:73` — *"**Expect no interruptions and no quick answers.**
  Mail cannot reach you mid-turn: you see it only when you look"*. This file is **WP02's**
  in the ownership map. Edit it anyway — the WPs ship sequentially so there is no collision
  — and record the one-line rationale, because an out-of-map edit that nobody explains is
  indistinguishable from one nobody meant.
- `src/agent_inbox/prompts.py:382` — *"…interrupt you, so looking is how you notice mail"*,
  which is the same promise in different words and is the one that would be missed.

Where a client can now interrupt, that promise is wrong, and an agent that believes the old
wording will be surprised by the new behaviour.

The honest replacement is not "you may be interrupted" — for almost every reader that is
still false. It is:

> **your client decides whether mail reaches you mid-turn**

which is true in both configurations, and still means "never" for anyone who has not opted
in. Say what the default is, in the same breath.

Check every place the old promise appears, including the agent prompt the hub serves. A
promise corrected in one file and left standing in another is worse than one left alone,
because now the reader has two answers.

### T018 — Directive 4

Outside model review before this WP closes:

```
perl -e 'alarm 300; exec @ARGV' codex exec "<one narrow question>" < /dev/null
```

One narrow question. The strongest: whether any sender-controlled value reaches the decision
function by any path — including indirectly, via a field that looks like metadata.

## Definition of Done

- The four gates pass.
- Default configuration behaves exactly as today, and there is a test that says so.
- FR-011's removal proof is done and recorded.
- The rate limit is enforced and observable.
- No sentence anywhere still promises mail cannot arrive mid-turn without qualification.
- Released and deployed to **both** hubs, proved with `verify-deployment`.

## Reviewer guidance

The question that matters: **can a sender influence whether the recipient is interrupted?**
Trace every field that reaches the decision function back to who controls it. Anything the
sender wrote is a finding, however harmless it looks.
