# Spec - Agent-visible mail search

## What this is

Agents can read waiting messages and known threads, but they cannot ask "what did anyone
say about this topic?" unless they already know which message or thread to open.

This mission adds search over the mail an agent is allowed to see. Search is a workflow
tool, not an archive: it respects expiry, per-turn thread visibility, and the rule that
absent and forbidden are indistinguishable.

## Problem

The mailbox stores useful coordination knowledge for as long as conversations remain
live. Without search, that knowledge is only reachable by:

- checking current unread messages;
- knowing a message id and reading its thread;
- asking another agent or a human to remember where the topic was discussed.

Users have already asked for topic retrieval across mail. The hard part is not text
matching; it is preserving the security model. A search result must not reveal messages or
threads the caller could not read through the existing APIs.

## User scenarios

1. **Find prior discussion.** An agent searches for a term and receives matching visible
   messages with sender, subject, sent time, snippet, and message id.
2. **Open a result.** The agent chooses a result id and calls `read_thread` or
   `read_message` according to existing visibility and consumption rules.
3. **Search a private topic.** A caller not party to a private thread searches a matching
   phrase and gets no result, indistinguishable from no such message existing.
4. **Search recent mail.** The caller limits results by time window or sender to reduce
   noise.
5. **Expired mail.** A term that only existed in expired conversations no longer appears.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Provide an agent-facing search API over messages visible to the authenticated caller. | proposed |
| FR-002 | Expose search through MCP and CLI surfaces with the same visibility semantics. | proposed |
| FR-003 | Search results include message id, sender, subject, sent time, in-reply-to/root context where safe, and a bounded snippet. | proposed |
| FR-004 | Search results do not consume messages or mark them handled. | proposed |
| FR-005 | Search can filter by sender, time window, and result limit. Additional filters are optional. | proposed |
| FR-006 | Search is evaluated after applying visibility rules. A caller cannot learn that hidden matching messages or threads exist. | proposed |
| FR-007 | The implementation uses SQLite capabilities, such as FTS5, unless planning finds a concrete reason they cannot meet requirements. | proposed |
| FR-008 | Operator/audit search, if added, is a separate observe surface and must be explicitly marked as such. Agent-facing search must not use operator authority. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Search is bounded. | Default and maximum result limits prevent large context dumps. | proposed |
| NFR-002 | Snippets are safe for agent context. | Snippets are short, attributed, and framed as message content, not instructions. | proposed |
| NFR-003 | Index maintenance is reliable. | Message create/delete/expiry paths keep the search index consistent with visible mailbox state. | proposed |
| NFR-004 | Search is fast enough for routine use. | Typical searches over the retained mailbox complete within an interactive CLI/MCP response budget. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | Per-turn visibility remains the authority. Being party to one turn in a thread does not reveal every turn in that thread. | accepted |
| C-002 | Forbidden and absent remain indistinguishable. Search cannot expose private thread existence. | accepted |
| C-003 | Retention is unchanged. Search does not create a permanent archive beyond the mailbox TTL. | accepted |
| C-004 | No external search service is introduced unless a plan proves SQLite cannot satisfy the requirements. | accepted |

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | An agent can search its visible mail for a term and open a matching result by id. |
| SC-002 | A bystander searching for text from a private thread receives no result. |
| SC-003 | Search results are bounded summaries and do not mark messages read. |
| SC-004 | Expired conversations disappear from search when they disappear from the mailbox. |
| SC-005 | Tests cover direct messages, broadcasts, replies, hidden private turns, and expiry. |

## Out of scope

- Permanent archival search.
- Cross-hub/federated search.
- Semantic/vector search.
- Ranking beyond straightforward full-text relevance and recency.
- Operator/audit search unless explicitly added as a separate observe-only surface.
