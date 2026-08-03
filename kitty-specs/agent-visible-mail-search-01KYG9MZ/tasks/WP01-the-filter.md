---
work_package_id: WP01
title: The filter
dependencies: []
requirement_refs:
- FR-001
- FR-003
- FR-005
- FR-006
- FR-008
- FR-009
- FR-010
- NFR-001
- NFR-002
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
agent: python-pedro
history:
- at: '2026-08-03T01:10:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/rules.py
create_intent:
- tests/test_search_rules.py
execution_mode: code_change
owned_files:
- src/agent_inbox/rules.py
- src/agent_inbox/mailbox.py
- tests/test_search_rules.py
role: implementer
tags: []
---

# WP01 — The filter

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

Given the objects, a caller and a query: return the matches that caller is allowed to
see — bounded, attributed, and pure.

## Context

Read `Mailbox.peek` first. It is this function with the wrong filter:

```python
me = (await self._require_actor(caller)).name
all_actors, memberships = await self._context()
objects = tuple(await self._store.objects())
read_ids = await self._read_by(me, objects)
return rules.unread(objects, me, read_ids, all_actors, memberships)
```

Then read `rules.visible_turns` and the docstring above it. It exists because of a
production leak: a bystander who received an opening broadcast could see every private
reply that followed, because the old code asked "am I party to *any* message in this
thread?" and unlocked all of them. That is the failure this work must not re-create
through a new door.

## Subtasks

### T001 — The filter: party-to, then match, then bound

Presumed home is `rules.py`, beside `unread` and `visible_turns` — pure, no I/O, and it
keeps every visibility decision in one file. Confirm or overturn that in code and say
which in a comment.

**Order is the requirement: visibility first, then text.** Matching before filtering would
leak through timing and through any count that escapes. Visibility is
`rules.is_party_to(obj, viewer, all_actors, memberships)` — **one call**. If your filter
is longer than that, you are reimplementing the rule.

Matching is case-insensitive substring over subject and body. Ordering is recency-first.
Bounds: 10 by default, 25 maximum (NFR-001). A caller asking for 500 gets 25, not an
error — the cap is the contract, not a validation failure.

### T002 — Snippets, attributed and capped

Roughly 200 characters, carrying the sender, framed as quoted data (FR-010, NFR-002).

**This is where a disclosure hides.** A snippet is text taken from a message; if it is
ever built from an object the caller is not party to — for context, for a thread summary,
for anything at all — that is the leak, and in review it will look like a formatting
detail. Write the test that proves a snippet never spans an invisible turn.

The plan leaves one thing open: whether the snippet is built here or at the API edge. It
is presentation, which argues for the edge; it is bounded disclosure, which argues for
keeping it beside the visibility decision. Decide it with that test and record which.

### T003 — Sender, time window, limit

`sender`, `since`, `until`, `limit` (FR-008). All narrowing, none widening — no filter may
return anything the unfiltered call would not.

### T004 — An empty query is refused

An empty or whitespace-only query returns an error, not the mailbox. A search that
silently means "everything" is a context dump with a polite name.

## Definition of done

- A caller party to one turn of a thread gets that turn and none of the private replies.
- Snippets are attributed, capped, and provably never built from an invisible turn.
- Bounds hold; an over-large `limit` is capped rather than refused.
- No I/O in the filter; tests are unit-level and fast.
- Four gates green: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pyright`.

## Directive 4 — done, 2026-08-03

Asked one question with four named failure modes: can a caller learn anything about a
message they are not party to — existence, count, text, or fragment — through `search` or
`snippet`?

All four came back clean, with reasons rather than assurances. `truncated` counts only
`visible`, which is built after `is_party_to`. `snippet` reads `obj.content`/`obj.summary`
and `_clip` slices that same string — it has no access to `objects` and cannot switch
messages. `sender`/`since`/`until` are `and` conditions after the visibility filter, so
they can only narrow. The empty query returns before anything is scanned.

**It found a fifth that the four questions missed**, which is the argument for asking
somebody else: `Match.record` is the whole `ObjectRecord`, and `ObjectRecord` carries
`in_reply_to` — so a caller party to a reply learns the id of a parent they cannot read.

Reproduced independently before acting, per the directive, and the reproduction changed
the conclusion: **`wire.note()` emits `inReplyTo` unconditionally (`wire.py:216`) and
`check_inbox` already renders through it (`api.py:917`).** The disclosure is pre-existing
and search neither introduces nor worsens it. Filed as **issue #45**; not fixed here,
because deciding what `inReplyTo` should say when the parent is invisible belongs to the
wire format, not to a search filter.

WP02's T005 must still not propagate it — thread context omitted, not nulled, where the
caller is not party to the opener.

## Reviewer guidance

Count the lines between "here are the objects" and "here are the visible ones". It should
be one call to `is_party_to`. Anything else is the rule being written twice.
