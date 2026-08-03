# Spec — Agent-visible mail search

> **Delivered and closed 2026-08-03 — shipped as v0.46.0**, running on both hubs and
> proved. Three work packages, twelve subtasks, three Directive 4 reviews, three removal
> proofs. The reviews produced three findings: **#45** was filed rather than fixed (a
> reply discloses its parent's id — pre-existing, and search does not spread it); a
> `limit=0` divergence between the client and the route was fixed here; and the
> shared-token path was verified as the documented machine boundary, not a defect.

- Mission: `agent-visible-mail-search-01KYG9MZ`
- Revised 2026-08-03 with the owner's decisions: search covers the whole retention
  window, and the implementation scans rather than indexing. Both are recorded below
  with their reasoning, because both departed from what this spec originally assumed.

## What this is

Agents can read waiting messages and known threads, but they cannot ask *"what did anyone
say about this?"* unless they already know which message or thread to open.

This adds search over the mail an agent is allowed to see. Search is a **workflow tool,
not an archive**: it respects expiry, per-turn visibility, and the rule that absent and
forbidden are indistinguishable.

## What it searches, and the promise that changes

**Everything the caller was party to, within the retention window — read or unread, sent
or received** (owner, 2026-08-03).

This is the only version that answers the question the mission opens with. "What did
anyone say about the flaky tests" is almost always answered by mail the agent has already
read; a search restricted to unread mail is a filter over `check_inbox` and cannot answer
it at all.

**It changes what consume-on-read means, and that is deliberate.** Reading a message today
removes it from your inbox; the object survives until expiry. After this, *removed from
your queue* and *gone* stop being the same thing. Nothing new is disclosed — every message
search can return was already returnable through `read_thread` to a caller who knew its
id — but an agent that has read a message can now find it again, which it could not
before. The mailbox's promise was never that reading destroys; it was that reading
consumes. This makes that distinction visible, and the documentation must say so rather
than let an agent discover it.

Retention is unchanged. When a conversation expires it leaves search at the same instant
it leaves everything else, because they are the same rows.

## The security model is not re-implemented

`rules.is_party_to(obj, viewer, all_actors, memberships)` is already the per-turn
authority, and `rules.visible_turns` exists because of a production leak — a bystander who
received an opening broadcast could see every private reply that followed.

**Search filters through that same predicate.** It does not express visibility as a SQL
`WHERE` clause, and a plan that does is wrong however fast it is: two implementations of
one rule agree until the day they do not, and the day they do not is a disclosure.

Filtering through `is_party_to` also settles something the first draft of this spec left
open — **mail the caller sent is searchable**, because `named_self` is already part of
being party to a turn. "What did I tell them about this" is at least as common a question
as its reverse.

## User scenarios

1. **Find prior discussion.** An agent searches a term and receives matching visible
   messages with sender, subject, sent time, snippet, and message id.
2. **Open a result.** The agent takes a result id and calls `read_thread` or
   `read_message`, subject to the existing visibility and consumption rules.
3. **Search a private topic.** A caller not party to a private thread searches a phrase
   that occurs in it and gets nothing — indistinguishable from no such message existing.
4. **Find something already read.** An agent searches for a message it handled last week
   and finds it. This is the case the mission exists for.
5. **Find something it sent.** The same, for its own outgoing mail.
6. **Narrow the noise.** The caller limits by sender, time window, or result count.
7. **Expired mail.** A term that occurred only in expired conversations returns nothing.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | An agent-facing search API over messages visible to the authenticated caller. | proposed |
| FR-002 | Search is exposed through MCP and the CLI with identical visibility semantics. | proposed |
| FR-003 | A result carries message id, sender, subject, sent time, thread context where safe, and a bounded snippet. | proposed |
| FR-004 | Search consumes nothing and marks nothing handled. Calling it does not change what `check_inbox` returns. | proposed |
| FR-005 | Search covers the full retention window — read and unread, received and sent — for messages the caller is party to. | proposed |
| FR-006 | Visibility is decided by `rules.is_party_to`, the same predicate every other read surface uses. Search does not express visibility in SQL. | proposed |
| FR-007 | A caller cannot learn that a hidden matching message or thread exists. No result, no count, no timing difference that distinguishes forbidden from absent. | proposed |
| FR-008 | Filters: sender, time window, and result limit. | proposed |
| FR-009 | Matching is case-insensitive substring over subject and body, scanned rather than indexed — see the note below. Ordering is recency-first. | proposed |
| FR-010 | Every snippet is attributed to its sender and framed as quoted data, never as instruction. | proposed |
| FR-011 | Operator/audit search, if ever added, is a separate observe surface, explicitly marked. Agent-facing search never uses operator authority. | proposed |
| FR-012 | The documentation states plainly that a read message remains findable until it expires. | proposed |

## Why it scans rather than indexes

The first draft of this spec assumed FTS5. Planning found a concrete reason not to, which
FR-007 of that draft explicitly invited.

Retention is **fourteen days**. A busy hub holds thousands of messages, not millions, and
the charter says volume is not a constraint and will not become one. A scan over that is
immediate.

Against that, FTS5 costs a shadow table that must stay in step with `objects` on insert
*and* on expiry, and this project has no migration framework — only additive
`CREATE TABLE IF NOT EXISTS` — so an index on an existing hub starts empty and needs a
backfill, which is a migration in all but name.

The decisive argument is the failure mode. **A desynced index fails silently**: search
answers "nothing about that" when there is something, and nobody can tell. That is the
exact shape of every expensive defect this project has paid for — a check that passed
because it had nothing to look at. A scan cannot desync, because it reads the rows
everything else reads.

What this gives up: stemming, phrase operators, and BM25 relevance. For a fourteen-day
mailbox, recency ordering is a better answer than relevance anyway. FTS5 remains available
later behind the same API if a hub ever grows to need it — and that is the point of
deciding the API shape now and the storage strategy last.

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Search is hard-bounded, not politely defaulted. | 10 results by default, 25 maximum, snippets capped at roughly 200 characters. A caller asking for more gets the maximum, not an error. | proposed |
| NFR-002 | Snippets are safe to put in an agent's context. | Short, sender-attributed, framed as quoted content. A search result is *more* likely to be trusted than inbox mail, because the agent asked for it. | proposed |
| NFR-003 | Search and the mailbox cannot disagree about what exists. | Search reads the same rows as every other surface. No second store, no index to fall out of step. | proposed |
| NFR-004 | Fast enough for routine use. | A search over a full retention window returns inside an ordinary CLI/MCP response, measured on a mailbox of at least several thousand messages. | proposed |
| NFR-005 | The hub decides; no client filters. | All matching and all visibility happen server-side. A client that received more than it should have and filtered locally would be a disclosure with a cosmetic fix. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | Per-turn visibility remains the authority. Being party to one turn does not reveal the rest of the thread. | accepted |
| C-002 | Forbidden and absent remain indistinguishable. | accepted |
| C-003 | Retention is unchanged. Search creates no archive beyond the mailbox TTL. | accepted |
| C-004 | No external search service, and no second copy of message text. | accepted |
| C-005 | Attention is the scarce resource (charter directive 7). Bounds are part of the contract, not a tuning parameter. | accepted |
| C-006 | No deployment-specific hostnames, IPs, organisation names or secrets in code, docs or tests. | accepted |

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | An agent searches a term and opens a matching result by id. |
| SC-002 | A bystander searching text from a private thread gets nothing — proved against the same fixture that proves the party *does* find it. |
| SC-003 | Searching changes nothing: the same `check_inbox` before and after, byte for byte. |
| SC-004 | A message the agent read a week ago is still findable; one whose thread expired is not. |
| SC-005 | Mail the caller sent is findable by the caller. |
| SC-006 | Removing the `is_party_to` filter makes a disclosure test fail — and the paired positive still passes. |
| SC-007 | Tests cover direct messages, broadcasts, replies, private turns in a thread the caller partly sees, sent mail, and expiry. |

## Out of scope

- Permanent archival search — retention is the boundary.
- Cross-hub or federated search.
- Semantic or vector search.
- Ranking beyond recency.
- Operator/audit search.
- Any change to consumption, retention, or the meaning of `read_message`.

## Edge cases

- **A thread the caller sees only part of.** Matches in the turns they are party to;
  silence about the rest. This is `visible_turns`' whole reason for existing.
- **A term appearing only in a subject**, or only in a body — both match.
- **An empty or whitespace query.** Refused plainly, rather than returning the mailbox.
- **A query matching everything.** Bounded by NFR-001 like any other.
- **A message the caller sent to somebody who has since been removed.** Still theirs;
  still findable.
- **Two agents on one machine sharing a token.** Search is scoped to the *caller's* name,
  as every other read surface is. A shared credential does not merge two mailboxes.
