---
work_package_id: WP02
title: The route, and the proofs
dependencies:
- WP01
requirement_refs:
- FR-001
- FR-003
- FR-004
- FR-005
- FR-007
- FR-011
- NFR-001
- NFR-004
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T005
- T006
- T007
- T008
- T009
agent: python-pedro
history:
- at: '2026-08-03T01:10:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent:
- tests/test_search_api.py
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- src/agent_inbox/house.py
- tests/test_search_api.py
role: implementer
tags: []
---

# WP02 — The route, and the proofs

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

`GET /search`, and the tests that make the security claim real rather than asserted.

## Context

WP01 built the filter. This exposes it and proves it. The proving is the larger half of
this package and is not optional: a search route without T006 and T007 is an unproven
disclosure surface.

## Subtasks

### T005 — `GET /search`

```
GET /search?q=&sender=&since=&until=&limit=
  → { "results": [ { id, from, subject, sent, snippet, thread } ], "truncated": bool }
```

`truncated` earns its place: an agent that cannot tell a complete answer from a capped one
will either re-search pointlessly or conclude that nothing else exists.

**Thread context is omitted, not nulled**, where the caller is not party to the thread's
opener. A null that appears exactly when a thread is private is itself a disclosure.

The route authenticates as the caller, exactly as every other agent-facing read does. It
must not reach for operator authority — FR-011 says agent search never does, and this is
where that would silently creep in.

### T006 — The disclosure tests

- A bystander searching a private thread's text gets nothing.
- A caller party to one turn finds that turn and none of the private replies.

**Both must be proved against the same fixture that proves the party does find it.** A
disclosure test that builds its own world passes because there was nothing to find, and
this project has paid for that shape more than once — see AGENTS.md, "Establish the
premise before asserting on it". One fixture, two callers, opposite expectations.

### T007 — Removal proof for SC-006

Delete the `is_party_to` filter. A disclosure test must fail. Restore it; it must pass.
**Check the paired positive still passes**, so you have not merely proved that breaking
things breaks things.

Run it. Do not assert it.

### T008 — Searching consumes nothing

`check_inbox` returns byte-identical results before and after a search that matched
unread mail (FR-004). Nothing is marked handled, no read row is written, no cursor moves.

### T009 — Read, expired, sent

- A message the caller read a week ago is still findable — the case the mission exists for.
- A message whose thread expired is not.
- Mail the caller sent is findable by them (`named_self`, free from `is_party_to`).

Also the NFR-004 measurement: a search over a mailbox of several thousand messages returns
inside an ordinary response. Record the number.

## Definition of done

- The route returns bounded, attributed results and `truncated` is honest.
- One fixture proves both the bystander's silence and the party's result.
- The removal proof has been run, both halves.
- `check_inbox` is unchanged by searching.
- Four gates green.

## Directive 4 — done, 2026-08-03

Asked whether any caller can obtain a result, count, field, fragment or error difference
revealing a message they are not party to, naming three routes in: the `owns` guard, the
fields `_result` inherits from `_summary`, and error differences from invalid parameters.

**(b) and (c) clean, with reasons.** `_summary` emits `id`, `attributedTo`, `summary`,
`published`, `broadcast` and `chars` — never the actual `to`/`cc` — and every one of them
describes the *matched visible* message rather than anything hidden. Search never looks up
a caller-supplied object id, so there is no "no such message" versus "not yours" oracle to
have; an invalid `limit` is a framework 400 decided by the type annotation, independent of
any message.

**(a) is the shared-token boundary, and it is not new.** A shared token resolves to
`SHARED_ACTOR`, after which `provide_caller` takes `X-Agent-Name` at face value — so a
token holder can search as any actor on that machine. Verified against the existing route
before accepting it: `/actors/{name}/inbox` (api.py:1848) and `/actors/{name}/search`
(api.py:1857) declare the *same* dependency and pass through the same `owns`. Search is
neither weaker nor stronger than reading the inbox.

This is the boundary `shared-tokens-only-01KYG7S7` established and
`doc/interrupting-an-agent.md:90` states plainly: a token proves the caller is on an
admitted machine, and it cannot tell two agents on that machine apart, because they share
a config file and a credential by design. Nothing to fix here; a fix would be a different
mission about binding identity to something other than a machine.

## Reviewer guidance

Check that T006's two assertions genuinely share a fixture. That is the difference between
a security test and a test-shaped comment.
