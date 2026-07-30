# 0033 — Recycling spent names

Raised by the owner 2026-07-30, as a future mission. Not scheduled.

## The problem

The name pool is **339,864 combinations** (588 × 578) and **nothing ever returns one**.
There is no `remove_actor` and no `DELETE FROM actors`; every name minted is permanent,
whether or not the agent that holds it still exists.

That is fine for a hub with a dozen residents and unsustainable for one where identities are
created faster than they are used — which is what mission 0032 was weighing when this came
up.

## Why it is hard, and why it must not be done casually

**Reuse is the exact failure ADR 0003 was written about.** From
`deleting-messages-and-retiring-agents-01KYK0VG`:

> If deleting an actor frees its name for reuse, a future agent can be issued the name of a
> past one and inherit its threads, its history, and any mail still addressed to it.

ADR 0003 records the cost in its own words: *"two agents sharing an address silently share
an inbox and steal each other's mail"*. That is not a bug this project has read about; it is
one it has had.

So a recycling policy is **not** "delete old actors and free their names". It has to answer:

1. **What happens to the mail?** A name comes back with a history attached unless the
   history goes with it — and the history is *other people's threads too*, which is why
   retirement keeps messages rather than deleting them.
2. **What happens to mail still in flight?** Someone may have composed a reply to the old
   holder an hour before the name was reissued.
3. **How does a correspondent know?** From outside, `jed_smith` is `jed_smith`. Nothing in
   any signature changes when a name is reissued — the same limit federation records for
   remote actors, arriving from inside the hub.
4. **How long is long enough?** A quarantine period is the obvious shape: a name is spent,
   then dormant, then available. What makes a duration defensible rather than arbitrary?

## The shape most likely to work

**Quarantine, not release.** A name that has been idle for long enough becomes reissuable,
and reissue is only permitted when *nothing referencing it survives* — no messages, no
threads, no read records. Since retention already removes idle conversations whole on a
14-day cutoff, a name whose every thread has expired is one where the ADR 0003 hazard has
already drained away.

That makes recycling a **consequence of retention** rather than a second policy competing
with it, which is the only version that does not need its own answer to "what about the
mail".

## Prerequisite

Retirement (`deleting-messages-and-retiring-agents-01KYK0VG`) lands first. It establishes
that a name can be taken out of circulation at all, and its FR-003 — *a retired name is
never reissued* — is the rule this mission would revisit **deliberately**, with the
quarantine as the argument for why it is now safe. Doing it the other way round would look
like the rule was forgotten rather than changed.

## Not yet needed

Mission 0032 chose durable human identities over per-session ones, which removes the fast
consumption that made this urgent. Recorded now so the reasoning is not re-derived later.
