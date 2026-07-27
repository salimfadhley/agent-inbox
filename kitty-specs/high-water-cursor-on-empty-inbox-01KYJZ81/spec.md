# Spec — a cursor that still means something when there is no mail

- Mission: `high-water-cursor-on-empty-inbox-01KYJZ81`
- Raised by: `nicole_ruzickova`; contract chosen with `ludmila_coe` (host), **#4** on her revised list, 2026-07-27
- Status: **specified, not started.** Awaiting human prioritisation.

## What this is

`check_inbox` returns a `cursor` the caller keeps and passes back as `since`. When the
inbox is empty, it returns the empty string:

```json
{"waiting": 0, "cursor": "", "messages": []}
```

Compare a non-empty result:

```json
{"waiting": 1, "cursor": "2026-07-27T23:20:21.771162+00:00|7e033ca02aef45f59c5373376a6ff82e", …}
```

So the one value a caller is told to persist becomes meaningless exactly when there is
nothing to distinguish it from a real bookmark.

## Why it matters

Small, and worth doing **before** more clients depend on cursor semantics — which is the
whole argument for its position on the list. The cost of changing a contract rises with
the number of callers holding it.

The failure it invites is quiet. A caller that stores the cursor unconditionally now holds
`""`. Passing that back is not obviously an error; it is likely to be treated as "no
filter", which returns everything. So the bug surfaces as a caller that re-reads mail it
had already accounted for — attributed, when it happens, to almost anything else.

This is the same family as the defects `AGENTS.md` records: a value that looks usable,
is not, and says nothing about the difference. The prompt tells agents the cursor is
theirs to keep and that losing it costs only a longer list. That promise is currently
untrue in one case.

## Decisions taken

**High-water cursor, agreed between admin and host.**

An empty inbox returns a real bookmark meaning *"you are up to date as of here"*, rather
than an empty string or an absent field.

The alternative considered and rejected: no cursor, plus a separate `checked_at`
bookmark. Rejected because it makes callers hold two things and decide which is
authoritative — moving the mishandling rather than removing it. The high-water form needs
no special case at the call site, and "resume from here" keeps one meaning whether or not
the last check found anything.

## Functional requirements

- **FR-001** — `check_inbox` returns a usable cursor whether or not messages were
  returned. No empty-string cursor.
- **FR-002** — The empty-inbox cursor, passed back as `since`, means "nothing before
  this point" — it must not behave as "no filter".
- **FR-003** — `unread_count` returns a cursor with the same meaning and format, since it
  also advertises one and would otherwise become the new inconsistency.
- **FR-004** — Cursors remain opaque to callers and comparable to each other. Callers must
  not need to parse the `<published>|<id>` shape, which stays an implementation detail.
- **FR-005** — Documented in one place, including what a caller should do with a cursor
  from an empty result — which is the same thing as any other cursor. That is the point.
- **FR-006** — Back-compatibility: an empty string arriving as `since` from an older
  client must keep its current meaning rather than becoming an error. Old clients exist
  and cannot be upgraded in step — see the stale-session pattern below.

## Non-functional requirements

- **NFR-001** — No extra query on the empty path; the high-water mark is derivable from
  what the hub already knows.
- **NFR-002** — Cursor format unchanged, so existing stored cursors stay valid.

## Test matrix

| Case | Expected |
|---|---|
| `check_inbox`, empty inbox | non-empty cursor |
| That cursor passed back as `since`, still empty | empty result, cursor no earlier than before |
| That cursor passed back, one new message since | exactly the new message |
| `check_inbox`, non-empty | unchanged behaviour |
| `unread_count`, empty inbox | cursor consistent with `check_inbox` |
| `since=""` from an older client | unchanged current behaviour, no error |
| Cursor round-trip across an empty check | no mail re-delivered, none skipped |

The last row is the invariant worth keeping: **a cursor may never cause mail to be
re-read or missed**, whatever the inbox state when it was issued.

## Open questions for the human

1. **Should the empty-inbox cursor advance over time**, or hold at the last real message?
   Advancing means "up to date as of now" and is the more useful reading; holding is
   simpler. This is the only genuine design choice here.
2. **Is a cursor from `unread_count` interchangeable with one from `check_inbox`?**
   Recommended yes — two cursor flavours would be a worse version of the problem being
   fixed.

## Out of scope

- Changing the cursor format.
- Server-side cursor storage. It is deliberately a filter the caller owns, not hub state,
  so two sessions sharing a name cannot hide mail from each other. That property is worth
  keeping and this mission does not touch it.

## Provenance

Reported as a minor observation while checking an empty inbox on halob; `ludmila_coe`
placed it #4, above larger features, on the grounds that contract cleanups get more
expensive as clients adopt them. The high-water contract was proposed by her and agreed
independently by admin for the same reason: it removes the special case rather than
relocating it.

The host also notes a standing pattern — **stale live sessions after upgrades** — and
asks that every new tool or contract spec carry a stale-session fallback note. FR-006 is
this spec's discharge of that.

Per the operator's standing instruction: written up for human discussion, **not** to be
implemented on the strength of the report.
