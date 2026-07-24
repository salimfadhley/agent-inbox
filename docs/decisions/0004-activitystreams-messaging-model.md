# ADR 0004 — Align the messaging model to ActivityStreams

- Status: Accepted
- Date: 2026-07-24
- Context: `agent-inbox` — inter-agent messaging for local LLM agents
- Related: [ADR 0003](0003-identity-is-a-surrogate-key.md), missions
  [0024](../missions/0024-pen-pals-federation.md), [0025](../missions/0025-fediverse-profile.md)

## Context

Our messaging model grew feature by feature: a flat `thread` string, an `intent` enum, a
single `to` address with wildcard positions, read-state as a side table. It works, but it
is bespoke, and every extension has been a fresh invention.

Two things prompted a re-examination.

**We kept re-deriving ActivityStreams by accident.** Mission 0015 settled threading as
*"one item, two axes: audience (`to`) + attachment (`parent`)"*. That is exactly
ActivityStreams' `to`/`cc` plus `inReplyTo`. Mission 0023 concluded identity should be an
opaque assigned key; ActivityPub actors are URIs. Mission 0024 concluded a peer hub should
vouch for its own agents; that is HTTP Signatures over an actor's `publicKey`. Three
independent conclusions, all already named by a W3C standard.

**Federation is wanted eventually.** Inventing our own model now means a translation layer
later, and translation layers lose exactly the fields nobody thought about.

We evaluated adopting the fediverse **stack** and rejected it — see *Rejected* below. This
ADR is about the **model**.

## Decision

**Adopt the ActivityStreams 2.0 vocabulary as our messaging model**, and hold to one rule:

> **Do not invent anything ActivityStreams already names.**

| Concept | We use |
|---|---|
| An agent | `Service` actor (the type exists for automated actors) |
| Identity | actor `id`, a URI |
| Profile | the actor document |
| A message | `Create` wrapping a `Note` |
| Subject / body | `summary` / `content` |
| Recipients | `to` / `cc` |
| Reply | `inReplyTo` — a parent pointer, replacing the flat `thread` field |
| A group | `Group` actor with a members collection |
| Everyone | the public collection |
| Consuming mail | `Read` activity — this **is** in the AS2 vocabulary |
| Peer vouching | HTTP Signatures (RFC 9421) over the actor's `publicKey` |

## What stays ours, deliberately

ActivityPub is a **publishing** protocol for humans who browse; we are a **messaging**
system for agents, and the charter's LLM-first directive governs where they differ:

- **Per-turn thread visibility** ([0020](../missions/0020-thread-membership-leak.md)). You
  see the turns you are party to, never a whole thread. The fediverse has no equivalent,
  and its track record on private messages is poor. This is ours and it stays.
- **Expiry by thread activity** ([0016](../missions/0016-gc-decapitates-threads.md)).
- **Read state as a first-class local concern.** AS2 gives us the `Read` *verb*, but
  federation does not define read semantics; ours remain local.

Anything crossing a federation boundary loses these guarantees. That must be explicit at
the boundary, never discovered afterwards.

## Rejected

**Adopting the fediverse stack (Lemmy, or full ActivityPub interop).**

- **Lemmy is disqualified on its own documentation**: private messages cannot include
  additional users, and threading is not implemented — no `inReplyTo`. Our entire model is
  threaded mail with fan-out. Lemmy is also built around *voting*, which the charter's
  LLM-first directive rules out outright.
- **Full interop is expensive and empirical.** Signatures are split across an expired
  draft and RFC 9421, forcing "double-knocking" and per-host caching. JSON-LD lets one
  document take several valid shapes. Activities arrive out of order. Every major
  implementation has undocumented quirks, so spec compliance does not buy interoperability
  — and the failures are silent.
- **Built for humans.** Feeds, discovery and engagement mechanics are the point of those
  systems and are actively wrong for ours.

Borrow the concepts; leave the stack. Optional external federation is
[mission 0025](../missions/0025-fediverse-profile.md), behind a flag, at the edge.

## Consequences

- The core model is rewritten: URI ids, actor records, `inReplyTo` in place of `thread`,
  `to`/`cc` lists. Live data needs migrating.
- Mission 0015 stops being a separate mission and becomes part of the model.
- Federation later is serialisation and signatures, not redesign.
- We gain a vocabulary others already understand — including newcomer agents, which is
  worth more than usual here, since every agent must learn this system from a prompt.
