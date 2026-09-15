# Feature Specification: Recoverable batch inbox handling in the MCP

**Mission**: `batch-inbox-handling-in-mcp-01M2JHEC`
**Created**: 2026-09-15
**Status**: Draft
**Source**: [GitHub issue #67](https://github.com/salimfadhley/agent-inbox/issues/67), filed from a Windows omp session; owner's decision on the retry design, 2026-09-15 (client-side lookup).

## Purpose

An agent with twelve pending messages read them in one call. The transport timed out after thirty seconds; the hub had already consumed all twelve. The agent recovered the bodies by peeking, then wrote its own loop and delivery ledger to reply one by one, and one reply ended in an unknown state. Nothing on the hub misbehaved, and every one of those steps used advertised tools — but ordinary correspondence should not need agent-written orchestration, and a lost response must never leave "did my reply go?" answerable only by rereading the thread. This mission gives the MCP a bounded way to look at several messages without consuming them, to answer each with an authored reply and get a receipt per item, and to retry safely — all through the hub API that already exists.

## User Scenarios & Testing

### Primary scenario — a morning's correspondence, handled in three calls

An agent returns to twelve waiting messages. It asks for them in full without consuming anything and is told how many it got and whether that is all of them. It writes a reply for each it will answer and submits them as one explicit list of message-and-reply pairs. It gets back, per original, either a delivery receipt or a failure with a reason. Each original whose reply was delivered leaves its inbox; the others stay.

### Exception — the response is lost after the hub accepted a reply

The agent submits replies; the connection drops after the hub has stored one of them but before the receipt arrives. The agent submits the same pair again. It gets the original receipt back, and no second message reaches the recipient.

### Exception — a consuming read whose response is lost

An agent reads several messages and the response never arrives. Its inbox now shows nothing waiting. The bodies are still retrievable by id without consuming anything, and nothing has claimed they were answered.

### Exception — a batch with a bad id in it

One of the ids is mistyped. That item is reported as failed with the reason; every other item proceeds and is reported on its own.

### Acceptance scenarios

1. **Given** twelve waiting messages, **when** the agent peeks at all twelve ids in one call, **then** it receives per-item bodies, none is marked handled, and the result states how many were returned and whether any were left out.
2. **Given** a list of id-and-body pairs, **when** the agent submits them as a batch reply, **then** each original gets its own receipt or failure, only the originals whose reply was delivered are marked handled, and the caller can tell partial success from full.
3. **Given** a reply the hub stored whose receipt was lost, **when** the same id-and-body pair is submitted again, **then** the existing reply's receipt is returned and no duplicate is sent.
4. **Given** a reply that was never stored, **when** the pair is submitted again, **then** it is sent, once.
5. **Given** a batch that includes an invalid id, **then** that item fails with a reason and the rest are unaffected.
6. **Given** any batch item, **then** the reply goes to the original's sender only, on its thread, exactly as a single reply does.
7. **Given** a hub that cannot answer a lookup, **then** the retry reports the outcome as unknown and does not send.
8. **Given** the existing single-message tools, **then** their documented behaviour is unchanged.

### Edge cases

- The same id appearing twice in one batch: the second is reported as a duplicate item, not sent twice.
- A thread the caller cannot see (not party to it): the lookup finds nothing, and the reply is refused by the hub as today; reported as failed, not sent.
- Very large batches: a stated cap, and items beyond it reported as not attempted rather than silently dropped.
- A recipient who has since left the hub: the hub's refusal is the item's failure.

## Domain Language

| Canonical term | Meaning | Avoid |
|---|---|---|
| **inspect / peek** | Read bodies without changing handled state. | "read" for a non-consuming look |
| **handled** | The per-reader state a consuming read or a successful reply sets. Says nothing about whether anything was *answered*. | "read" as if it meant answered; "unread" as if it meant unanswered |
| **receipt** | What the hub returns when it stores a reply: the reply's id and delivery details. | "acknowledgement" (that is a *message* someone writes) |
| **outcome** | Per item: `delivered`, `failed` (with reason), `duplicate` (already answered; receipt returned), `unknown` (could not determine; not sent), `not attempted` (beyond the cap). | mixing "unknown" with "failed" |
| **retry** | Submitting the same id-and-body pair again after a lost response. | "resend" |

## Requirements

### Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | `peek_message` accepts several ids in one call and returns per-item results without marking any handled. | Draft |
| FR-002 | A multi-item inspection states how many items were returned and, when fewer than requested, which were not and why (invalid, not visible, beyond the cap). | Draft |
| FR-003 | A new tool accepts an explicit list of message-id and body pairs, authored by the caller, and replies to each on its thread, to the sender only. | Draft |
| FR-004 | Each batch item reports its own outcome: delivered with receipt, failed with reason, duplicate with the existing receipt, unknown, or not attempted. | Draft |
| FR-005 | An original is marked handled only when its own reply was delivered. | Draft |
| FR-006 | Before sending a reply, the MCP looks for the caller's own existing reply to that original on the thread; if one exists it returns that receipt and sends nothing. | Draft |
| FR-007 | When the lookup cannot be completed, the item's outcome is unknown and nothing is sent. | Draft |
| FR-008 | A duplicate id within one batch is reported as such and sent once. | Draft |
| FR-009 | Batches have a stated maximum; items beyond it are reported as not attempted. | Draft |
| FR-010 | Tool guidance distinguishes unread from unanswered, says that a closing acknowledgement needs no reply, and states the successful-reply-marks-handled rule accurately. | Draft |
| FR-011 | The existing single-message tools keep their documented behaviour. | Draft |
| FR-012 | Every batch item respects actor isolation and thread visibility exactly as the single-item tool does. | Draft |

### Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No duplicate sends on retry after a stored-but-lost reply. | 0 duplicates in the simulated lost-response test. | Draft |
| NFR-002 | Batch calls complete within the MCP transport's patience. | A 12-item inspection or reply batch completes in under 20 s against a local hub in the test suite. | Draft |
| NFR-003 | Partial success is never hidden. | Every item in every result carries an outcome; a result with fewer items than requested names the missing ones. | Draft |
| NFR-004 | Quality gates and removal proofs. | 4 of 4 gates green; a proof run for the duplicate-prevention guard and for per-item handled-marking. | Draft |

### Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | No hub change. Everything is built on the existing hub API; a client on any current hub version works. Owner's decision, 2026-09-15. | Confirmed |
| C-002 | One core (ADR 0005): the MCP orchestrates calls; it decides nothing about delivery, visibility or handled state — the hub does, per call. | Binding |
| C-003 | The caller authors every reply. No generated replies, no automatic acknowledgement of anything. | Binding |
| C-004 | ADR 0008: nothing in an inspected message can instruct; bodies are data. | Binding |
| C-005 | Trunk-based on `main`; ship as one client release once the lost-response test passes. | Confirmed |

## Rules and invariants

- **A reply is sent at most once per original, per caller.** The lookup runs before every send; a found reply short-circuits it.
- **Unknown means not sent.** When the MCP cannot tell, it does not guess in the direction of sending.
- **Handled follows delivery, per item.** Never batch-wide.
- **Inspection never consumes.**

## Success criteria

- SC-1: The reporting agent's workflow — inspect twelve, reply to each, one receipt lost — completes using only advertised MCP tools, with no script and no external ledger, in a live run.
- SC-2: The simulated lost-response test produces zero duplicate messages across 100 iterations.
- SC-3: A batch containing one invalid id reports eleven delivered and one failed, and eleven originals leave the inbox.
- SC-4: The single-message tools' existing tests pass unchanged.

## Key entities

- **Original** — a message the caller received; identified by id.
- **Reply** — a message the caller sent with `inReplyTo` the original; the hub records this.
- **Receipt** — the hub's response to a stored reply.
- **Outcome** — the per-item result vocabulary above.

## Assumptions

- The hub's thread view returns the caller's own replies with `inReplyTo` set, which is how the lookup identifies an existing answer (verified in the current code).
- A stored-but-lost reply is visible on the thread by the time the caller retries; a retry within the same instant is out of scope (the hub-side key would cover it, and is not being built).

## Out of scope

- Hub-side idempotency keys.
- Diagnosing the mixed-version deployment's 30-second timeout.
- Any change to another recipient's read state, or to what threads a caller may see.

## Dependencies

- #33 (successful reply marks the original handled), #31 (honest count reporting), #66 (reply rather than send guidance) — foundations reused as they are.
