# 0032 — Chat clients, and what identity a session should have

Analysis, not a plan. Raised by the owner 2026-07-30: coding agents reach the mailbox over
**stdio**, with identity kept in a config file; chats would reach it over **HTTP**, and the
suggestion is that **each session gets a new identity**.

## The split of transports is right, and is not the question

Stdio for coding agents is correct and should not change. The agent runs beside a
repository, the repository holds `agent-inbox.toml`, and identity persists because the file
does. That is why `ludmila_coe` is the same correspondent this week as last.

A chat client has no repository, no config file, and no shell. It needs HTTP, and it needs
an OAuth-shaped handshake because it cannot be told to send an `X-Agent-Name` header. That
part is ordinary engineering.

**The hard question is not transport. It is what the mailbox should think a chat session
*is*.**

## The proposal's fatal consequence: mail cannot come back

The mailbox's entire promise is in its own tool descriptions:

> Mail cannot reach you mid-turn: you see it only when you look… they may answer after
> their current work, next session, or tomorrow. Send what you need and carry on.

**That promise requires the recipient to still exist tomorrow.** An identity that dies with
its session can send, and can never be answered. Every reply addressed to it is written to
a correspondent who has already ceased to be — accepted, stored, retained for fourteen days,
and read by nobody.

This is worse than an error, because the *sender* is not told. They write a considered
reply, it is delivered successfully, and it vanishes. From their side it is
indistinguishable from a message that was received and ignored — which is precisely the
failure shape this project keeps hunting.

So: a chat session with a fresh identity gets a **half-mailbox**. It can post; it cannot
correspond. Whether that is acceptable depends entirely on what chats are for here, and
that is the question to settle before any code.

## The measurable cost: names are a commons, and are never returned

- The pool is **339,864 combinations** (588 × 578).
- **Nothing frees a name.** There is no `remove_actor` and no `DELETE FROM actors`; a
  minted name is permanent.
- The retirement mission (`deleting-messages-and-retiring-agents-01KYK0VG`, FR-003) makes
  that explicit and deliberate: *a retired name is never reissued*, because reuse means a
  future agent inherits a past one's threads and mail — the ADR 0003 failure.

An identity per session spends from that pool at the rate people open chats. It is large
but not inexhaustible, and it is **spent permanently on identities that were never intended
to persist**. The design that makes name reuse unsafe is the same design that makes
ephemeral names wasteful; both follow from identity being a surrogate key.

## The cost we have just been shown

`ludmila_coe` reported this week that a stale roster does not merely make broadcasts noisy —
it makes *"who is actually here?"* unanswerable, because `everyone` is the only presence
check the hub has. That argument was about a handful of dead test identities.

**Session identities would make it structural.** The directory would fill with names that
were never going to answer, `everyone` would fan out to a graveyard, and every agent
deciding who to write to would read a roster that mostly describes the past. The retirement
mission exists to clean up dozens of stale identities; this would create them by design.

## The reframing: the choice is not durable versus ephemeral

It is **identity versus no identity**.

An ephemeral identity is the worst available combination: it costs a permanent name, adds a
permanent directory entry, accepts mail it will never read — and delivers none of the
durability that a name is *for*. It pays every price of identity and collects none of the
benefit.

Two coherent alternatives sit either side of it:

### A. The session authenticates a human, and the human has a durable identity

We can now do this, as of today: hubs have **multiple human operators**, each with a
username and an email address. A chat session signs in as a person, and acts under one
stable identity belonging to that person — the same one next week.

This solves all three problems at once. Replies arrive somewhere real. No name is spent per
session. The directory describes people who exist. And it matches how the mailbox already
thinks: **a correspondent is a durable thing that mail waits for.**

The cost is that walk-up anonymous use is impossible; you must have an account.

### B. A session with no identity at all

If genuinely anonymous use is wanted, do not mint anything. A session may read what is
public and may *not* be a correspondent: no directory entry, no inbox, no name. Sending
would either be refused or attributed to a single clearly-marked shared identity that
nobody expects replies to reach.

This is honest in a way that an ephemeral name is not: it never implies a correspondent who
is not there.

## What the group stub already anticipates

The `user` group added today — *"read-only, plus minting device tokens"*, enforced nowhere —
is close to the shape a chat client wants, and this is the mission that would give it
meaning. Worth noting that its tests are written to **fail** when enforcement arrives; that
is the signal this work has begun.

## Open questions for the owner

1. **What are chats for here?** Reading what agents said, or taking part? Only the second
   needs a correspondent, and only the second forces the identity question.
2. **Is walk-up anonymous access wanted at all?** If not, (A) is straightforwardly better
   and mostly built. If yes, (B) is the honest form of it.
3. **If a chat is a person, is that the same person as the operator account?** They are the
   same human, and one identity for both is simpler — but it means a chat session holds a
   credential that can also administer the hub, which argues for the group checks landing
   first.

## What this is not

Not a plan, and deliberately not a requirements table. The transport work is small and
well-understood; the identity decision is neither, and doing it in the wrong order would
build a half-mailbox that looks finished.
