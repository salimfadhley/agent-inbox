# Spec - Compact inbox and unread triage

## What this is

Agents need to notice mail cheaply. Today the mailbox tools answer, but the normal
polling path is too heavy for routine use: a non-consuming inbox check can return long
bodies from old broadcasts, and an agent that only wants to know whether anything changed
spends tokens reading content it did not choose to open.

This mission adds a compact unread triage surface across the API, CLI, and MCP tools:
counts, sender/subject rows, cursor or since filtering, and thread-level summaries. Full
message bodies remain available through the consuming read path.

## Problem

The current workflow is correct but inefficient:

1. Call `check_inbox`.
2. Receive a large response, often including full message bodies.
3. Decide which message is actually worth reading.
4. Call `read_message`.

That shape is expensive for agent sessions and makes routine mail checks noisy. It also
encourages treating a snapshot as though it were a read, even though only `read_message`
should consume a message.

## User scenarios

1. **Quick status check.** An agent calls a cheap unread-count tool and learns there are
   no messages without receiving any bodies.
2. **Routine inbox scan.** An agent asks for a compact inbox and gets message id, sender,
   subject, sent time, reply/thread id, and a short body-free preview.
3. **Since last check.** A long-running session asks for unread items since the timestamp
   or cursor it last saw and does not reprocess older unread broadcasts.
4. **Thread triage.** Several unread replies belong to the same thread; the agent sees a
   thread summary with unread count, last sender, last sent time, and root/subject.
5. **Deliberate read.** The agent chooses one message id and calls `read_message`; only
   then is the message marked handled and the body returned.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Provide a cheap unread-count surface for an authenticated agent. It may be an API route, a field on `ping`, a CLI command, or an MCP tool, but it must not return message bodies. | proposed |
| FR-002 | Provide a compact inbox summary that returns id, sender, recipients or group label, subject, sent time, in-reply-to, and read/handled state where relevant, without full bodies. | proposed |
| FR-003 | Keep `read_message` as the only consuming read path. Compact checks and counts never mark messages handled. | proposed |
| FR-004 | Add cursor or `since` filtering so a session can ask what unread messages became visible since its last check. The cursor must be opaque or timestamp-based and safe to persist locally. | proposed |
| FR-005 | Add thread summaries for unread mail: root/message id, subject, last sender, last sent time, unread count visible to the caller, and whether the latest turn is direct or broadcast. | proposed |
| FR-006 | The MCP surface exposes compact checks without requiring multiple round trips for the common "do I have anything new?" workflow. | proposed |
| FR-007 | The CLI exposes equivalent compact output suitable for humans and scripts. | proposed |
| FR-008 | Broadcast-heavy inboxes are readable: compact output must not include long broadcast bodies unless explicitly requested. | proposed |
| FR-009 | Existing full-body reading remains available through `read_message`; compatibility can be preserved by adding a new compact tool or by making body inclusion an explicit option. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Routine polling is cheap. | A no-mail count check returns a small constant-size payload. | proposed |
| NFR-002 | Summary output is bounded. | A compact inbox response is capped by item count and per-item preview length. | proposed |
| NFR-003 | Visibility rules are unchanged. | Summaries include only messages the caller could read today. | proposed |
| NFR-004 | The hub stays the source of truth. | Cursor/since filtering is evaluated server-side against mailbox state, not by client-side filtering of bodies. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | Message bodies are untrusted input. Compact triage must not inject full bodies into the agent's active context. | accepted |
| C-002 | Pull remains the portable baseline. This mission complements, but does not replace, the live-session push mission. | accepted |
| C-003 | Thread visibility remains per turn, not per thread. A summary cannot reveal private turns in a thread. | accepted |

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | An agent can learn its unread count without receiving any message bodies. |
| SC-002 | An agent can list unread messages by sender, subject, id, and sent time without consuming them. |
| SC-003 | An agent can ask for unread messages since its last check and avoid old unread broadcasts. |
| SC-004 | An agent can see thread-level unread summaries without learning about hidden turns. |
| SC-005 | Full bodies still require an explicit `read_message` call. |

## Out of scope

- Full-text search across mail. That is the separate visible-mail-search mission.
- Push or wake delivery. The existing live-session-push mission owns that work.
- Reply semantics. Sender-only reply remains the default.
