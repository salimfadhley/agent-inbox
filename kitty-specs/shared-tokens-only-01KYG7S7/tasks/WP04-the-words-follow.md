---
work_package_id: WP04
title: The words follow the code
dependencies:
- WP03
requirement_refs:
- FR-007
- FR-012
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T019
- T020
- T021
- T022
- T023
- T024
phase: Phase 4 - the prose
agent: python-pedro
history:
- at: '2026-08-02T12:00:00Z'
  actor: system
  action: Prompt generated via /spec.kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/prompts.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/prompts.py
- src/agent_inbox/cli.py
- src/agent_inbox/mcp_client.py
- README.md
- doc/interrupting-an-agent.md
- tests/test_prompts.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP04 — The words follow the code

## ⚡ Do This First: Load Agent Profile

Load `python-pedro` via `/ad-hoc-profile-load` before reading further.

---

## Objective

Nothing anywhere still describes a token bound to one agent. And the interrupt
documentation stops claiming more than a shared token can give.

**This package must not lead.** It runs last because prose describing behaviour that has
not shipped is a failure this project keeps finding, and a promise corrected in one file
while another still carries the old version leaves the reader with two answers — which is
worse than leaving both alone.

## Subtasks

### T019 — The served prompt

`prompts.py`, the device-token paragraph. Today it says a token meant for you alone goes in
the project instead — drop the `--global`. There is no such token any more.

What survives is simpler and shorter: an operator gives you a token, it admits this
machine, `agent-inbox config set --global token <token>`, and every agent here is admitted.
Say that once, without hedging between two shapes.

Mind the 2KB instruction budget if you touch anything the MCP server serves at session
start — it truncates at the tail.

### T020 — The doctor paragraph, which is in `prompts.py` and not where you think

**Corrected by analysis (A2).** The obvious suspect is `cli.py`'s `_token_help`, and it is
already right — it says "Tokens -> Mint a shared token". The stale instruction is in
**`prompts.py:215`**, in the step-2 paragraph about what `doctor` prints: *"sign in to the
console, **Agents → you → Tokens → Mint**, then `join` again with `--token`"*. Two of those
steps are pages WP03 deletes.

An instruction to visit a page that no longer exists is worse than no instruction: it reads
as a broken hub rather than as stale text. The new path is Tokens → Mint, and the token
admits the machine rather than the agent.

Re-read `_token_help` anyway to confirm it still matches after WP03.

### T021 — The MCP tool and the README

The `join` tool's `token` parameter documentation, and `README.md` where it describes
tokens. Both currently hedge between the two shapes; neither needs to any more.

### T022 — FR-012, and it is the one with teeth

`doc/interrupting-an-agent.md` carries a table of what `from` proves under each kind of
hub, with a row for **per-agent device tokens** that will no longer exist. Removing that
row is not enough — the row underneath it becomes the whole truth, and the page's central
claim has to shrink to match.

What is true after this mission: a token proves the sender is **on a machine an operator
admitted**. That is real and useful — it stops a stranger on the network, another machine,
and (with signatures) another hub. What it cannot do is tell two agents on the *same*
machine apart, and it never could: they share a config file and a credential by design.

So `wake_from` means *interrupt me for mail from these names, as asserted by an admitted
machine* — not *as proved to be that agent*. The `identity-unverified` reason code keeps
its meaning; the check in `interrupt.py` stays, because it still separates "anyone who can
reach this hub" from "a machine the operator admitted".

Do not quietly weaken the page. Say what changed and why, because a reader who configured
`wake_from` under the old wording made a decision on a promise that has moved.

### T023 — Tests

`tests/test_prompts.py` and wherever the prompt's content is asserted. The property to pin
is negative and simple: no served text describes a token bound to one agent. A negative
assertion is weak on its own, so pair it with a positive one — the shared-token instruction
is present and complete.

### T024 — Directive 4

One narrow question. The strongest: whether any surviving sentence in the repository tells
an agent or an operator to do something that no longer works.

## Definition of Done

- The four gates pass.
- No served text, CLI help or documentation describes a per-agent token.
- `doc/interrupting-an-agent.md` states what a shared token proves, and says the claim
  changed.
- Released and deployed to **both** hubs, proved with `verify-deployment`.

## Reviewer guidance

Read the prompt as a new agent would, cold, with no memory of the old model. Anything that
makes you ask "which kind of token do I have?" is a leftover.
