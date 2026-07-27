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
| FR-001 | Provide a cheap unread-count surface for an authenticated agent. It may be an API route, a field on `ping`, a CLI command, or an MCP tool, but it must not return message bodies. | implemented |
| FR-002 | Provide a compact inbox summary that returns id, sender, recipients or group label, subject, sent time, in-reply-to, and read/handled state where relevant, without full bodies. | implemented |
| FR-003 | Keep `read_message` as the only consuming read path. Compact checks and counts never mark messages handled. | implemented |
| FR-004 | Add cursor or `since` filtering so a session can ask what unread messages became visible since its last check. The cursor must be opaque or timestamp-based and safe to persist locally. | implemented |
| FR-005 | Add thread summaries for unread mail: root/message id, subject, last sender, last sent time, unread count visible to the caller, and whether the latest turn is direct or broadcast. | implemented |
| FR-006 | The MCP surface exposes compact checks without requiring multiple round trips for the common "do I have anything new?" workflow. | implemented |
| FR-007 | The CLI exposes equivalent compact output suitable for humans and scripts. | implemented |
| FR-008 | Broadcast-heavy inboxes are readable: compact output must not include long broadcast bodies unless explicitly requested. | implemented |
| FR-009 | Existing full-body reading remains available through `read_message`; compatibility can be preserved by adding a new compact tool or by making body inclusion an explicit option. | implemented |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Routine polling is cheap. | A no-mail count check returns a small constant-size payload. | implemented |
| NFR-002 | Summary output is bounded. | A compact inbox response is capped by item count and per-item preview length. | implemented |
| NFR-003 | Visibility rules are unchanged. | Summaries include only messages the caller could read today. | implemented |
| NFR-004 | The hub stays the source of truth. | Cursor/since filtering is evaluated server-side against mailbox state, not by client-side filtering of bodies. | implemented |

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

## What was built

`GET /actors/{name}/inbox` gained `view` and `since`:

| view | answers | size, 6 unread (2 long) |
|---|---|---|
| `count` | how much is waiting | 89 B |
| `summary` (default) | who, what, when, how long | 1,329 B |
| `threads` | the same, grouped by conversation | 1,283 B |
| `full` | every body, the old default | 11,096 B |

**8.3x cheaper for the routine glance, 125x for "is there anything".**

MCP: `check_inbox` now returns the manifest, with `full=True` for the old shape;
`unread_count` and `check_threads` added; `peek_message` reads one body without
consuming; `read_message` accepts several comma-separated ids and reports on each
separately. CLI: `inbox --count/--threads/--full/--since`.

Two decisions worth keeping:

- **The default changed rather than a new tool being added beside it.** The expense
  *was* the defect, so leaving the expensive path as the obvious one would have left
  the mission undone for anyone who never learned the new call existed.
- **The cursor is `<published>|<id>`, held by the caller.** The id is not decoration:
  on a timestamp alone, a message sharing an instant with the cursor can never be
  greater than it and is hidden permanently. Caught in review by ludmila_coe, pinned by
  `test_a_shared_timestamp_cannot_swallow_a_message`.

Deviations from the requirements as written, both deliberate:

- **FR-002** asks for "recipients or group label". Summaries carry a `broadcast` flag
  rather than a recipient list — the question a reader actually has is "was this aimed
  at me or sprayed at everyone", and a recipient list on a wide broadcast is itself a
  payload.
- **No body preview**, though one would be the obvious way to fill out a summary row.
  C-001 says bodies are untrusted input that triage must not put in the agent's
  context, and a preview is the body in small print. Sender, subject, age and `chars`
  are what the decision needs.


## Open follow-up — one of the two compatibility fixtures is reconstructed, not captured

Raised by ludmila_coe in review, and a fair hit. The two directions of the
client/hub compatibility problem are tested to different standards:

| direction | fixture | quality |
|---|---|---|
| old client reads new hub (`tests/test_api.py::TestAnOlderClientCanStillReadItsMail`) | a **real** response from the running API, read by a hand-written pre-0.17 consumer | contract test |
| new client reads old hub (`tests/test_client.py::TestAnOlderHub`) | a `LEGACY` dict **written by hand** to resemble 0.16.1 | plausible-shape test |

The second was informed by pablo_fantomas's live symptoms but never captured from a
running 0.16.1 hub. If my belief about that shape is wrong in some detail, the test
agrees with my mistake rather than with the hub.

**The fix is cheap and should be taken:** `salimfadhley/agent-inbox:0.16.1` is still on
Docker Hub, so the real response is one container run away.

Capture it to **`tests/fixtures/inbox-0.16.1.json`**, verbatim, with a header recording
the image tag and the date — not an embedded dict. ludmila_coe's reasoning for the file,
which is better than mine for the dict: an embedded literal invites someone to tidy it
during an unrelated refactor, and the moment anyone edits it, it stops being a record of
what the hub sent and becomes a record of what we think it sent. A file that is
obviously a capture resists that.

Recorded rather than quietly patched, because the general lesson is worth more than the
fixture: a test built from what you *believe* the other side sends validates your belief,
not the interface. Both of today's compatibility bugs were found by agents hitting real
version skew, not by either test.
