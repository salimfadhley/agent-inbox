---
work_package_id: WP01
title: 'The third state, and the regression it would otherwise cause'
dependencies: []
requirement_refs:
- FR-003
tracker_refs: []
planning_base_branch: kitty/mission-retry-delivery-to-a-sleeping-peer
merge_target_branch: kitty/mission-retry-delivery-to-a-sleeping-peer
branch_strategy: Planning artifacts for this mission were generated on kitty/mission-retry-delivery-to-a-sleeping-peer. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into kitty/mission-retry-delivery-to-a-sleeping-peer unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
phase: Phase 1 - Foundation
agent: python-pedro
history:
- at: 2026-07-31T16:40:00Z
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/delivery.py
create_intent:
- tests/test_receipt_states.py
execution_mode: code_change
owned_files:
- src/agent_inbox/delivery.py
- tests/test_receipt_states.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP01 – The third state, and the regression it would otherwise cause

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

Give `Receipt` a third state — `queued` — and **correct the one existing calculation that
would draw the wrong conclusion from it.**

The first half is trivial. The second half is the reason this is a work package rather than
a line, and it is the only change in this mission that can break something that currently
works.

## Context

Step 6 shipped federation that delivers once and never retries. Step 7 adds retries, so a
message can now be *waiting* — neither delivered nor failed. The existing code anticipated
this:

```python
@property
def state(self) -> str:
    """`delivered` or `failed`.

    **Step 7 adds `queued` here**, and that is why this is a word rather than a
    boolean on the wire. A client that learns to read three states today keeps
    working when a queue starts producing the third.
    """
```

That comment is now history rather than plan. You are Step 7.

## The regression, stated plainly

`Sent.reached_nobody` is currently correct and must stay correct:

```python
@property
def reached_nobody(self) -> bool:
    """True when nothing was delivered anywhere.

    The one case that must never look like success. ...
    """
    if self.reached_local_recipients:
        return False
    return bool(self.receipts) and not any(r.delivered for r in self.receipts)
```

`api.py` uses this to refuse a 201 for a send that reached nobody — its docstring calls
that "a silent success, which is the worst failure shape we have".

**A queued receipt has `delivered=False`.** So without a change, a message that is merely
waiting for a peer to wake up would be reported to the sender as having reached nobody: a
hard error, for a send that is very likely to succeed twenty seconds later.

Both directions are wrong and only one is obvious:

| State | `reached_nobody` must be | Because |
|---|---|---|
| all remote receipts queued | **False** | it has not failed; it is in progress |
| all remote receipts failed | **True** | unchanged — this is the guard's whole purpose |
| some queued, some failed | **False** | something may still arrive |
| some delivered | False | unchanged |

## Subtasks

### T001 — `Receipt.queued` and the third `state` word

Add a `queued: bool = False` field to `Receipt` and make `state` return `"queued"` when set.

Keep `delivered` as the existing boolean rather than replacing both with a single string
field. Two reasons: every existing reader of `.delivered` keeps working, and a queued
receipt genuinely is not delivered — the boolean stays *true to its name*.

Default `False` so every existing construction site is unchanged.

### T002 — Correct `Sent.reached_nobody`

Per the table above. A queued receipt is not a delivered one, but it is not nobody either.

Write the comment for the next reader: state that a queued receipt is *pending*, and that
reporting it as "reached nobody" would turn an ordinary suspended peer into an error the
sender cannot act on.

### T003 — Tests

New module `tests/test_receipt_states.py`. Cover:

- each of the three states renders the right word
- the `reached_nobody` table above, all four rows
- a receipt with no `queued` argument behaves exactly as before (the default is not a
  behaviour change for existing callers)

**The all-failed row is the one that matters.** It is the row that was already right, and
the one a careless fix breaks. If it passes trivially because your change made
`reached_nobody` always false, you have replaced a correct guard with a broken one — remove
your change and confirm that row still fails for the right reason.

### T004 — Retire the forward references

`delivery.py` contains at least two comments written in the future tense about Step 7
("Step 7 adds `queued` here", and `outbound.deliver`'s "When a queue arrives it must
re-read them"). Rewrite them in the present tense, describing what the code now does.

Leave the *reasoning* intact. "This is a word rather than a boolean so a third state does
not break clients" is still the explanation for the design; only the tense is wrong.

## Definition of Done

- [ ] `Receipt.state` returns `queued`, `delivered` or `failed`
- [ ] `reached_nobody` correct for all four rows, with the all-failed row proved by removal
- [ ] No existing call site needed changing
- [ ] Forward-tense Step 7 comments rewritten in the present tense
- [ ] `pytest`, `ruff`, `pyright`, `black` all green — capture each exit code, do not trust a
      scrolled-past summary

## Reviewer guidance

Read `reached_nobody` first and ask: *does a send whose only recipient was remote and
genuinely unreachable still report `True`?* That is the invariant this package is most
likely to have broken, and it is the one the API depends on.
