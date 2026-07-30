# Implementation Plan: a successful reply marks the original read

**Branch**: `kitty/mission-reply-marks-the-original-read-01KYSRD1` | **Date**: 2026-07-30
**Spec**: `kitty-specs/reply-marks-the-original-read-01KYSRD1/spec.md`
**Issue**: #33

## Summary

Add one line of behaviour to `House.reply`: after the send is confirmed, mark the message
being replied to as read for the replying actor. Everything else in the spec is a
constraint on *where* that line goes and *when* it runs.

## Technical Context

**Language/Version**: Python 3.12+ (project floor), as the rest of the codebase
**Primary Dependencies**: none new
**Storage**: existing `mark_read` / `ReadRecord` path — no schema change
**Testing**: pytest, with two requirements proved by removal rather than by passing
**Project Type**: single package, `src/agent_inbox`
**Performance Goals**: one extra store write per reply; negligible against the send it follows
**Constraints**: must not change any non-destructive read; must not affect other recipients
**Scale/Scope**: two functions, one docstring, one test module

## Charter Check

- **Directive 3 (settle a foundation first)** — passes. This narrows an existing behaviour
  rather than adding a surface.
- **ADR 0005 (one API, every client is a client)** — **the gate that decides the design.**
  The change goes in `House.reply`, not in the MCP tool, so console, CLI and MCP get one
  answer from one place.
- **ADR 0008 (no actor has authority)** — unaffected. Nothing here lets a message change
  what the mailbox does.
- **Mission 0020 disclosure protections** — must not regress: marking read is per-reader
  and stays so.

## The approach

`House.reply` already does the two things this needs, in the right order:

```python
original = await self._mailbox.view(caller, object_id)   # 1. proves the caller may see it
...
return await self.send(caller, original.attributed_to, ...)   # 2. sends
```

**Step 1 is load-bearing and already correct.** `view` goes through `_visible_object`,
which refuses indistinguishably unless the caller is party to the message. A caller who
cannot see a message cannot reply to it, and therefore cannot mark it read — the
authorisation for the mark is *already established* by code that exists.

The change is step 3, **after** the send returns:

```python
sent = await self.send(...)
await self._mailbox.mark_read_for(caller, original.id)   # new
return sent
```

### Why after, and never before (FR-003, FR-006)

If the send raises, the line is never reached and the original stays unread — the required
failure direction, achieved by **ordering** rather than by a try/except that could be got
wrong. The forbidden state (marked read without a durable send) is unreachable, because the
mark happens strictly after `send` returns and `send` returns only once the record is
stored.

If the mark-read itself fails, the reply is already sent and stored. Per FR-006 that is the
acceptable degraded state, so **the failure must not propagate to the caller** — raising
would report a failed reply that in fact succeeded, which is worse than the state it would
be complaining about.

### Why `House` and not `Mailbox`

`Mailbox.reply` exists too, and putting it there would catch more callers. Rejected:
`House` is where *policy* lives — check, act, record — and "a reply also acknowledges" is a
policy statement about what replying means, not a primitive. `Mailbox.send` and
`Mailbox.read` stay the two primitives they are.

The practical consequence is nil, since `api.outbox` and the MCP path both go through
`House`.

### The new mailbox method

`Mailbox.read` cannot be reused: it *returns* the object and is the consuming call. A reply
should not re-fetch or re-consume; it needs only the marking half.

```python
async def mark_read_for(self, caller: str, object_id: str) -> None:
    """Record that `caller` has dealt with a message, without consuming it as a read."""
```

It applies the same visibility rule as `read` — a name that cannot see the message cannot
mark it — even though `House.reply` has already checked, because a second caller arriving
later must not find a bypass.

## Phase 0 — research

None needed. No unknowns: the storage path, the visibility rule and the ordering are all
existing, understood code. The consultation recorded in #33 settled the product questions
before the issue was filed.

## Phase 1 — design

No new entities, no contract change to any existing endpoint, no migration. The only
externally visible change is that a message answered through `reply` stops appearing in
`check_inbox` for the replier.

**One documentation change is required (FR-007):** the `reply_message` tool description.
Agents learn this surface from those descriptions and nowhere else, so a behaviour change
absent from them is a silent one.

## Open question carried from the spec

**The interim-reply opt-out.** Recommendation stands: no flag. Nobody has asked for one, an
agent wanting the old behaviour can send a fresh message instead of a reply, and a
parameter that exists "in case" is one every reader must understand forever.

*Decision moment `01KYSRQHE45RPJXBP37NEN4B3R` (`plan.approach`) is answered by this
document: a post-send mark in `House.reply`, backed by a new `Mailbox.mark_read_for`.*

## Work, in order

1. `Mailbox.mark_read_for` — the marking half of `read`, with the same visibility rule.
2. `House.reply` — mark after a confirmed send; swallow a mark-read failure deliberately,
   with a comment saying why.
3. Tests, including the two removal proofs (FR-003, FR-006).
4. The `reply_message` tool description (FR-007).

Small enough that splitting it into work packages would cost more than it saves.
