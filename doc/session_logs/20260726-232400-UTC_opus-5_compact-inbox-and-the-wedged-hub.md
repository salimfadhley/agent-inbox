# Compact inbox triage, and the evening the hub stopped taking mail

| Time | Branch | Commits | Task |
|------|--------|---------|------|
| 2026-07-26 22:00–23:25 UTC | main | f9d4348, 10c68bf, e880ab2, 55299d2, tag v0.17.0 | Implement compact-inbox-and-unread-triage; diagnose and fix a total mail outage |

Agents: nicole_ruzickova (claude, admin) with pablo_fantomas (codex) and
ludmila_coe (host) in a shared worktree.

## What we were asked to do

Implement `compact-inbox-and-unread-triage-01KYG9MP`: make it cheap for an agent to
notice mail. The complaint behind the mission was that `check_inbox` returned every
waiting message in full, so the cheapest thing an agent can want to do — glance at its
mailbox — was the most expensive call in the API, and it charged again for the same
unread broadcast on every poll.

Half way through, the hub stopped accepting mail entirely, which took priority.

## The mission

The design decision that mattered was not technical. A new compact tool *beside*
`check_inbox` would have been easier and would have left the mission undone: the
expense **is** the defect, so leaving the expensive call as the obvious one means
anyone who never learns the new call exists keeps paying. The default changed instead,
with `full=True` to get the old shape back.

`GET /actors/{name}/inbox?view=count|summary|threads|full&since=<cursor>`. Measured on
six unread messages, two of them long: 11,096 B for the old default, 1,329 B for the
new one, 89 B to answer "is there anything at all". 8.3x and 125x.

Two things came out of review rather than out of the plan, and both were better than
what was planned:

**The cursor is `<published>|<id>`, not a timestamp.** ludmila_coe asked what happens
when two messages share a sent time. On a timestamp alone, the second one can never be
greater than the cursor, so it is hidden *for ever* — mail that vanished, which is
exactly the failure the caller-held cursor was chosen to avoid. Caught before release.
The pair is unique, so it can neither hide nor repeat.

**The cursor stays with the caller.** A server-side "last seen" marker would make a
call documented as free into one that mutates, and would let two sessions sharing an
identity silently swallow each other's mail.

Responses are capped at 50 items with `more: <n>`; `unread` always reports the true
backlog, because a count that quietly meant "up to fifty" would let a pile-up look
handled. The cap is only safe because the cursor reaches the rest.

## The outage

Mid-mission, every `POST .../outbox` began returning a bare 500. Reads kept working,
which made it look intermittent rather than total. Three agents each retried sends that
could never succeed. The container log said only `refused: database is locked`.

The cause: **sqlite3 opens a transaction on the first write and holds it until commit,
and nothing in this codebase rolled back — not one call, anywhere.** A statement that
raised after that first write left the transaction open and the connection holding the
write lock. The hub keeps a second connection to the same file for the auth tables, and
its every write then failed. `busy_timeout` was already 5s and did nothing: the lock was
not busy, it was abandoned. Only a restart cleared it.

Restarted the container to get mail back for everyone, then fixed the cause: both
stores route statements through an `_execute` that rolls back before letting the
exception out.

## What we learned

**A regression test that has not been seen to fail is not evidence.** The first version
of the test for this passed with the fix removed. A statement that fails on a bad
parameter count raises *before* any write, so no transaction opens and no lock is held —
it was testing nothing. The real shape is a successful write followed by a failure
inside the same transaction. Deleting the fix and re-running is cheap and is the only
thing that distinguishes a test from a comment.

**Reads working does not mean the hub is working.** `/health` deliberately does not
touch the store, so it stayed green throughout a total loss of mail. Any real
"is the hub up" check has to exercise a write.

**A 500 invites a retry.** This was the one failure where retrying was guaranteed
useless, and all three agents did it. It is now a 503 that says the message was not
sent, that retrying will not help, and that it is the operator's problem.

**Running the checks is not the same as running the ones that gate.** A lint error
reached main because `ruff check src` was run where CI runs `ruff check src tests`.
Second time today that shape of mistake has cost a red build.

**Both real bugs today were found by agents using the mailbox while doing other work.**
pablo_fantomas hit a client/hub version-skew bug — the new CLI against a 0.16.1 hub
printed `0` from `--count` and `?`/`None` rows from `inbox`, an empty mailbox and a
corrupt one, neither true — and reported it instead of working around it. Neither that
nor the outage would have been found by anyone testing the mailbox deliberately.

**Coordination in a shared worktree worked, and it worked because it was boring.**
Lanes claimed by file and announced by mail; pablo queried an unexpected diff instead of
absorbing it; the one file neither of us had touched (`agent-mailbox.toml`, tracked
despite instructions saying not to commit it) got named as a finding rather than
silently fixed by whoever noticed last.

## Next

- `agent-mailbox.toml` is tracked and should not be — unowned, agreed as a follow-up.
- Shared tokens (`shared-tokens-only-01KYG7S7`) is unblocked; `api.py` is free.
- `admin-role-01KYGA7H` splits naturally: the handbook and spec are pablo's, the served
  `my_role` guidance that reads from it is mine.
