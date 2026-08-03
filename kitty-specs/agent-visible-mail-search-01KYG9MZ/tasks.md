# Tasks — Agent-visible mail search

Mission: `agent-visible-mail-search-01KYG9MZ` · Branch: `main` ·
Spec: `spec.md` · Plan: `plan.md`

## What the plan settled

`search` is `peek` with the unread filter swapped for a party-to filter plus a text match
and a bound. Visibility is `rules.is_party_to` — **one function call**, never a SQL
`WHERE` clause. Anything longer than that is the rule being reimplemented, and two
implementations of one rule agree until the day they do not.

The scan introduces no new performance shape: `peek` already loads every object on every
call, and `unread_count` calls `peek`.

## Subtask index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | The filter: party-to, then match, then bound | WP01 | |
| T002 | Snippets — attributed, capped, never spanning an invisible turn | WP01 | |
| T003 | Sender, time-window and limit filters | WP01 | [P] |
| T004 | An empty query is refused, not answered with the mailbox | WP01 | [P] |
| T005 | `GET /search`, and `truncated` so a cap is not mistaken for an answer | WP02 | |
| T006 | Disclosure tests: bystander, partial thread, and the same fixture proving both | WP02 | |
| T007 | Removal proof for SC-006 — delete the filter, a disclosure test must fail | WP02 | |
| T008 | Searching consumes nothing: `check_inbox` byte-identical before and after | WP02 | |
| T009 | Read mail is findable, expired mail is not, sent mail is findable | WP02 | |
| T010 | `search_mail` on MCP and `agent-inbox search` on the CLI | WP03 | |
| T011 | The prose says a read message stays findable until it expires (FR-012) | WP03 | [P] |
| T012 | Directive 4 — outside model review before this ships | WP03 | |

---

## WP01 — The filter

**Goal**: given the objects, a caller and a query, return the matches that caller is
allowed to see — bounded, attributed, and pure.

**Independent test**: unit-level, no I/O. A caller party to one turn of a thread gets that
turn and not the private replies.

- [x] T001 The filter: party-to, then match, then bound (WP01)
- [x] T002 Snippets — attributed, capped, never spanning an invisible turn (WP01)
- [x] T003 Sender, time-window and limit filters (WP01)
- [x] T004 An empty query is refused, not answered with the mailbox (WP01)

**Sketch**: presumed to live in `rules.py` beside `unread` and `visible_turns`, which is
how those are already factored. Confirm or overturn that in code and say which in a
comment. Order matters and is the requirement: **party-to first, then match** — filtering
by text before visibility would make timing and result counts leak.

**Risks**: T002 is where a disclosure hides. A snippet is bounded text taken from a
message; if it is ever built from an object the caller is not party to — for context, for
a thread summary, for anything — that is the leak, and it will look like a formatting
detail in review.

**Dependencies**: none.

---

## WP02 — The route, and the proofs

**Goal**: `GET /search`, and the tests that make the security claim real rather than
asserted.

**Independent test**: a bystander searching a private thread's text gets nothing, proved
against the same fixture that proves the party finds it.

- [x] T005 `GET /search`, and `truncated` so a cap is not mistaken for an answer (WP02)
- [x] T006 Disclosure tests: bystander, partial thread, and the same fixture proving both (WP02)
- [x] T007 Removal proof for SC-006 — delete the filter, a disclosure test must fail (WP02)
- [x] T008 Searching consumes nothing: `check_inbox` byte-identical before and after (WP02)
- [x] T009 Read mail is findable, expired mail is not, sent mail is findable (WP02)

**Sketch**: the route reads query parameters, calls through `House` to the WP01 filter, and
renders. Thread context is **omitted** where the caller is not party to the opener — not
nulled, because a null appearing exactly when a thread is private is itself a disclosure.

**Risks**: T006's "same fixture" clause is the whole test. A disclosure test that builds
its own empty world passes because there was nothing to find, and this project has already
paid for that shape more than once. One fixture, two callers, opposite expectations.

T007 must be **run**, not asserted: delete the filter, watch a disclosure test fail,
restore it, watch it pass, and check the paired positive still passes.

**Dependencies**: WP01.

---

## WP03 — The clients, and the promise that changed

**Goal**: agents can reach it, and the documentation stops implying that reading destroys.

**Independent test**: `agent-inbox search` and the MCP tool return the same results for the
same caller, and neither filters anything locally.

- [x] T010 `search_mail` on MCP and `agent-inbox search` on the CLI (WP03)
- [x] T011 The prose says a read message stays findable until it expires (FR-012) (WP03)
- [x] T012 Directive 4 — outside model review before this ships (WP03)

**Sketch**: both clients are thin — pass the query, render the result (NFR-005). The tool
description matters as much as the code: it is what tells an agent the bound exists and
that results are quoted data, not instructions.

**Risks**: T011 is not tidying. This mission changes what consume-on-read means —
*removed from your queue* and *gone* stop being the same thing — and an agent that learns
this by discovering an old message in a search result has been misled by our own prose.
Say it where an agent will read it, not only in the spec.

**Dependencies**: WP02.

---

## MVP scope

**WP01 + WP02 are the feature and ship together.** A filter no route calls is dead code; a
route without T006 and T007 is an unproven disclosure surface. WP03 follows immediately —
the mission is not usable by an agent until the MCP tool exists, and FR-012's prose
becomes owed the moment the route lands.

## Parallelisation

Little worth having. Three packages, one lane, each depending on the last. `[P]` inside
WP01 marks subtasks that touch different concerns and could be split if two agents were
free.

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 | T001, T005 |
| FR-002 | T010 |
| FR-003 | T002, T005 |
| FR-004 | T008 |
| FR-005 | T001, T009 |
| FR-006 | T001, T007 |
| FR-007 | T005, T006 |
| FR-008 | T003 |
| FR-009 | T001 |
| FR-010 | T002, T010 |
| FR-011 | *nothing to build — operator search is out of scope; the constraint is that this route never uses operator authority, checked in T005* |
| FR-012 | T011 |
| NFR-001 | T001, T005 |
| NFR-002 | T002, T010 |
| NFR-003 | *satisfied by construction — there is no second store to fall out of step* |
| NFR-004 | T009 |
| NFR-005 | T010 |
