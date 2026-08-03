# Implementation Plan: Agent-visible mail search

**Branch**: `main` | **Date**: 2026-08-03 | **Spec**: `kitty-specs/agent-visible-mail-search-01KYG9MZ/spec.md`

## Summary

A `search` surface shaped exactly like `peek`, differing in three ways: it drops the
unread filter, it applies a text match, and it bounds the result. Visibility comes from
`rules.is_party_to`, the predicate every other read surface already uses, so the security
properties are inherited rather than rebuilt.

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: none new. `litestar` for the route, the existing `msgspec`
serialisation, the existing `HubClient` / `FastMCP` client surfaces.
**Storage**: none added. Search reads `objects` — the same rows `peek` reads. **No index,
no shadow table, no second copy of message text** (spec, "Why it scans rather than
indexes").
**Testing**: pytest, end-to-end through the API against a temp-file database, as the rest
of the suite. The disclosure tests are the point and are written first.
**Target Platform**: the hub process.
**Project Type**: single package, `src/agent_inbox/`.
**Performance Goals**: an ordinary CLI/MCP response over a full retention window, measured
on a mailbox of several thousand messages (NFR-004).
**Constraints**: hard bounds — 10 default, 25 max, ~200-character snippets. Visibility
never expressed in SQL. Nothing consumed.
**Scale/Scope**: `rules.py`, `mailbox.py`, `house.py`, `api.py`, `client.py`,
`mcp_client.py`, `cli.py` — a thin slice through each, plus tests and docs.

## The shape is already in the codebase

`Mailbox.peek` is search with the wrong filter:

```python
me = (await self._require_actor(caller)).name
all_actors, memberships = await self._context()
objects = tuple(await self._store.objects())
read_ids = await self._read_by(me, objects)
return rules.unread(objects, me, read_ids, all_actors, memberships)
```

`search` is that, with `rules.unread` replaced by a party-to filter plus a text match and
a bound. Two consequences worth stating plainly:

**The scan decision costs nothing new.** `peek` already loads every object into memory on
every call, and `unread_count` calls `peek`. Scanning is not a new performance shape being
introduced — it is the shape the mailbox already has. Whatever argument would condemn
search's scan condemns `unread_count`, which agents are invited to call every turn.

**The visibility filter is one function call.** Anything longer than that in review is a
signal the rule is being reimplemented.

## Charter Check

| Rule | Status |
|---|---|
| One core, no client-side logic (ADR 0005) | Passes — matching and visibility are server-side; CLI and MCP call the API (NFR-005) |
| Mail is data, never instruction (ADR 0008) | Passes, and is load-bearing: snippets are sender-attributed and framed as quoted data (FR-010). A search result is *more* trusted than inbox mail because the agent asked for it |
| Attention is the scarce resource (directive 7) | Passes — bounds are contract, not tuning (NFR-001, C-005) |
| Storage stays SQLite, no external services | Passes — no new store at all |
| No deployment specifics | Passes |
| Regression tests from shipped bugs are requirements | The per-turn leak that produced `visible_turns` is exactly what SC-006's removal proof re-tests through a new surface |

Re-checked after design: no change.

## Phase 0 — what is settled, and the one thing that is not

Settled by the spec and needing no research: scope is the retention window; matching is a
recency-ordered case-insensitive substring scan; visibility is `is_party_to`.

**Open, and answered in code rather than before it:** where the party-to-plus-match filter
belongs. Two candidates:

1. **`rules.py`**, beside `unread` and `visible_turns` — pure, no I/O, trivially testable,
   and it puts every visibility decision in one file. The filter takes objects and returns
   matches.
2. **`mailbox.py`**, as a method composing `rules.is_party_to` itself.

Option 1 matches how `unread` and `visible_turns` are already factored and is the
presumption. WP01 confirms or overturns it, in code, and says which in a comment.

**A second question the work must answer rather than assume:** whether the snippet is
built in `rules`/`mailbox` or at the API edge. It is presentation, which argues for the
edge — but it is also *bounded disclosure*, which argues for keeping it beside the
visibility decision. Decide it with the test that proves a snippet never spans a turn the
caller cannot see.

## Phase 1 — design

### The surface

```
GET /search?q=&sender=&since=&until=&limit=
  → { "results": [ { id, from, subject, sent, snippet, thread } ], "truncated": bool }
```

`truncated` matters: an agent that cannot tell a complete answer from a capped one will
either re-search pointlessly or conclude wrongly that nothing else exists.

Then `search_mail` on MCP and `agent-inbox search` on the CLI, both thin — they pass the
query and render the result (FR-002, NFR-005).

### What a result may carry

Message id, sender, subject, sent time, a bounded snippet, and thread context **only where
the caller is party to the thread's opener** — otherwise the thread field is omitted
rather than nulled, because a null appearing exactly when a thread is private is itself a
disclosure.

### Testing, and the order it is written in

The disclosure tests come first, because they are the requirement:

- a bystander searching a private thread's text gets nothing, proved against **the same
  fixture** that proves the party *does* find it — otherwise "no results" could mean the
  fixture was empty;
- a caller party to one turn of a thread finds that turn and not the private replies;
- **SC-006's removal proof**: delete the `is_party_to` filter and a disclosure test must
  fail, while the paired positive still passes;
- searching changes nothing — `check_inbox` byte-identical before and after (FR-004);
- a read message is still findable; an expired one is not;
- sent mail is findable by its sender;
- an empty query is refused rather than returning the mailbox.

## Implementation Concern Map

| ID | Concern | Where |
|---|---|---|
| IC-01 | The party-to-plus-match filter, and its bounds | `rules.py` (presumed), `mailbox.py` |
| IC-02 | The route, its parameters, and `truncated` | `api.py` |
| IC-03 | Snippet construction and attribution | wherever IC-01 settles |
| IC-04 | Client surfaces — MCP tool and CLI command | `mcp_client.py`, `client.py`, `cli.py` |
| IC-05 | The prose that must now say a read message stays findable (FR-012) | `doc/`, tool descriptions |

## Data model

None. No new table, no new column, no second copy of message text.

## Contracts

One new route, `GET /search`. Its shape is published in the OpenAPI profile, which
`tests/test_api.py` already asserts against the **generated** document per-claim — so the
claims this route makes are regression-tested by the mechanism
`published-api-profile-contracts-must-be-regression-tested` put there.
