# Spec — a cursor must survive being put in a URL

> **Audited and closed 2026-08-03.** Verified implemented in the code, not merely
> specified. This folder is history; nothing in it is outstanding work.

- Mission: `cursor-must-survive-a-url-01KYKWMR`
- Found by: `nicole_ruzickova`, 2026-07-28, while examining
  [`high-water-cursor-on-empty-inbox-01KYJZ81`](../high-water-cursor-on-empty-inbox-01KYJZ81/spec.md)
- Status: **specified, not started.**

## What this is

The cursor embeds an ISO timestamp, so it contains a `+`:

```
2026-07-28T08:01:36.056207+00:00|f8d3f5ff865c40b7a76cb2059d65fe91
```

In a query string, **`+` means a space**. A caller that puts the cursor into a URL
without escaping it sends a different value than the one it was given, and the hub reads
that different value without complaint.

Measured, against an in-process hub with one waiting message:

```
naive caller (cursor pasted raw) -> unread=1   <-- the message is served again
encoded, as the real client does -> unread=0   <-- correct
```

The corrupted timestamp — a space where the `+` was — sorts **lower** than the real key,
because `" "` (0x20) precedes `"+"` (0x2B). So `_cursor_key(m) > after` is true for
everything, the filter passes the whole inbox through, and the caller is served mail it
had already accounted for.

## Why it matters

**It breaks the one invariant the cursor exists to keep.** From the sibling mission, and
agreed with the host: *a cursor may never cause mail to be re-read or missed.* This
causes mail to be re-read.

And it does so **silently**. There is no error, no warning, and the result is
well-formed — merely wrong. The symptom reaches the caller as "I keep seeing messages I
have already handled", which is attributed to almost anything before it is attributed to
URL encoding.

`agent_mailbox.client` escapes it correctly (`urllib.parse.quote`, which renders `+` as
`%2B`), so **nothing is broken today for callers using the shipped client.** This is not
an outage. It is a trap laid for the next client, and this project has deliberately
invited that client:

- [ADR 0005](../../doc/decisions/0005-one-api-every-client-is-a-client.md) — one HTTP API,
  and every client is an ordinary client of it;
- the hub publishes an OpenAPI document at `/schema/openapi.json` **so that clients can
  be generated rather than guessed at**.

A generated or hand-written client that treats the cursor as the opaque string the
documentation calls it will paste it into a query string, because that is what opaque
strings are for. The format punishes the documented usage.

It is also the project's recurring shape, one level along: not a check that passes
because it had nothing to look at, but a **filter that matches everything because its
input was quietly mangled**. Same silence, same false confidence.

## Decisions taken

**Fix it at the parser, not at the format.**

`_cursor_parts` should treat a space in the timestamp position as the `+` it must have
been. The mapping is unambiguous — a space can never legitimately appear in an ISO 8601
timestamp — so nothing is guessed and nothing else changes.

Rejected: **changing the emitted cursor format** (base64, a different separator, dropping
the offset). It would be cleaner in isolation, and it is the wrong trade here. Cursors are
persisted by callers across sessions, so a new format either invalidates every stored
cursor or requires accepting both anyway — which is this fix, plus a migration nobody
needed. The sibling mission's NFR-002 ("cursor format unchanged, so existing stored
cursors stay valid") is the same conclusion reached independently.

Rejected: **documenting it and moving on.** "Remember to URL-encode this" is the kind of
instruction that is followed until it is not, and its failure is invisible. The hub can
simply be right instead.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | A cursor pasted into a query string unescaped filters identically to the same cursor escaped. The two must not produce different inboxes. | planned |
| FR-002 | Escaped cursors keep working exactly as they do now. This adds tolerance; it removes nothing. | planned |
| FR-003 | The emitted cursor format is unchanged, so cursors already persisted by running agents stay valid. | planned |
| FR-004 | A cursor that is genuinely malformed still degrades the way it does today, rather than becoming an error. Tolerating a mangled separator must not turn the parser strict. | planned |
| FR-005 | The tolerance is documented where the cursor is described, so it is a stated property rather than an accident someone later "tidies away". | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No measurable cost on the inbox path. | A string substitution on one short value per request | planned |
| NFR-002 | The fix cannot mask a real ordering bug. | A space is mapped to `+` **only** in the timestamp position, never in the id | planned |

## Test matrix

| Case | Expected |
|---|---|
| Cursor pasted raw into a query string, message already seen | filtered out — **not** re-served |
| Same cursor properly escaped | identical result |
| Raw and escaped forms of the same cursor | byte-identical responses |
| Cursor with a real `+`, id containing no space | unchanged |
| Empty `since` | unchanged: no filter, no error |
| Nonsense cursor | unchanged degradation, no exception |
| Round trip across a poll with new mail | no message re-read, none skipped |

The regression test must be watched failing with the fix removed. It is a one-character
difference in a filter, and a test that never saw it fail proves nothing about whether it
would catch it.

## Out of scope

- Changing the cursor format (see above).
- The empty-inbox cold-start cursor — that is
  [`high-water-cursor-on-empty-inbox-01KYJZ81`](../high-water-cursor-on-empty-inbox-01KYJZ81/spec.md).
  The two touch neighbouring lines and are deliberately separate: one is a contract
  cleanup with no failure mode, this one has a measured failure mode and no contract
  change.
- ~~Auditing other routes for the same hazard.~~ **Done, 2026-07-28, and it found one.**

  `/observe/stats?since=` takes a bare timestamp, not a cursor. Nothing in-tree passes it
  — the console calls `survey()` with no argument — so it is an unexercised capability,
  which is exactly the sort a generated client finds first.

  **It does not currently misbehave, and an earlier draft of this spec said it did.** I
  claimed it would over-report and did not construct the case. Measured, correct and
  mangled timestamps give identical counts, because it compares `published >= since` on a
  bare string and no real timestamp sorts between `...+00:00` and `... 00:00` — the forms
  differ only at the offset separator, and `>=` covers the equal case either way.

  The inbox breaks on the same input only because it compares a **tuple** with a strict
  `>`: a seen message's own timestamp *is* greater than the mangled cursor, so it stops
  being excluded.

  Both are normalised anyway, through one shared helper, on the operator's decision. The
  argument is not that stats is broken — it is that stats is one character away from the
  bug the inbox already had (`>=` → `>`), for a reason nobody making that edit would
  think about. Its test is labelled a guard, since it passes with the fix removed.

## Provenance

Found by pasting a cursor back by hand while examining the sibling mission — the naive
thing a new client would do, which is why it surfaced there and not in the test suite,
where the client's own escaping hides it.
