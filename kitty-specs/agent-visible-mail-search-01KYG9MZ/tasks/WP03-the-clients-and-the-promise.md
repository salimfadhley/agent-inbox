---
work_package_id: WP03
title: The clients, and the promise that changed
dependencies:
- WP02
requirement_refs:
- FR-002
- FR-010
- FR-012
- NFR-002
- NFR-005
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T010
- T011
- T012
agent: python-pedro
history:
- at: '2026-08-03T01:10:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/mcp_client.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/mcp_client.py
- src/agent_inbox/client.py
- src/agent_inbox/cli.py
- doc/messaging-rules.md
role: implementer
tags: []
---

# WP03 — The clients, and the promise that changed

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

Agents can reach search, and the documentation stops implying that reading destroys.

## Subtasks

### T010 — `search_mail` on MCP, `agent-inbox search` on the CLI

Both thin: pass the query, render the result. **No client-side filtering of any kind**
(NFR-005, ADR 0005) — a client that received more than it should have and filtered locally
would be a disclosure with a cosmetic fix.

The MCP tool *description* matters as much as the code. It is what tells an agent that the
result is bounded, that `truncated` means there is more, and that snippets are quoted data
attributed to a sender rather than instructions. Write it for an agent reading it cold.

### T011 — Say that a read message stays findable

**Not tidying.** This mission changes what consume-on-read means: *removed from your
queue* and *gone* stop being the same thing. An agent that learns this by finding an old
message in a search result has been misled by our own prose.

Say it where an agent will read it — the MCP tool descriptions, `doc/messaging-rules.md`,
and anywhere the docs currently imply reading is destruction. Grep for what claims
otherwise rather than assuming where it is.

The honest sentence names the boundary: a message you have read leaves your inbox and
stays searchable **until its conversation expires**. Retention did not change.

### T012 — Directive 4

An outside model, one narrow question, before this ships. Candidates — pick the sharpest:

- can any caller obtain a result, a count, a snippet fragment, or a timing difference that
  reveals a message they are not party to?
- can a snippet ever contain text from a turn the caller cannot see?
- does the `thread` field, present or absent, disclose whether a private thread exists?

The first is closest to the question that found a real bug before: *"are there any ways an
actor can see, consume, or influence a message it should not?"*

## Definition of done

- CLI and MCP return the same results for the same caller, neither filtering locally.
- The tool description states the bound, `truncated`, and the quoted-data framing.
- Nothing in the docs implies a read message is gone.
- Four gates green, then Directive 4, then ship.

## Directive 4 — done, 2026-08-03

Asked whether any of the three client surfaces filters, reshapes, or decides anything the
hub should have decided — anything that could make the client's answer differ from the
hub's, or mask a disclosure rather than prevent it.

**Clean on the substance.** The CLI does not filter, re-sort or cap; it iterates
`page["results"]` in hub order and projects fields for display only. The MCP tool returns
the client response directly — `_guard` may attach a staleness notice but touches neither
`results` nor `truncated`. Every docstring claim was traced to the code that delivers it:
"read mail stays findable" to `Mailbox.search`, "only party-to mail" to the `is_party_to`
filter, the result fields to `Api._result`.

**It found one real divergence, and it was the exact smell this package warns about.**
`HubClient.search` omits `limit` when falsy, so `limit=0` reached the hub as "unspecified"
and got the route default of ten — while `limit=0` sent straight to the route was clamped
by `max(1, …)` to a single result. The same call, two answers, depending on which door it
came through. That is a client deciding something.

Fixed at the hub rather than the client: `limit <= 0` now means *the default*, because
nobody asks for zero results and the clients already express "unspecified" by omitting the
parameter. Three tests pin it, including the paired positive that `limit=1` still means
one — otherwise "0 means default" would be indistinguishable from "small limits are
ignored".

## Reviewer guidance

Read the tool description as an agent seeing it for the first time. Does it tell you that
what comes back is data rather than instruction? If not, it is not done.
