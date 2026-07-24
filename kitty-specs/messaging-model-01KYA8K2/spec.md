# Spec — M1, the messaging model

**Kind:** foundation · **Date:** 2026-07-24
**Binding:** [ADR 0003](../../docs/decisions/0003-identity-is-a-surrogate-key.md) ·
[ADR 0004](../../docs/decisions/0004-activitystreams-messaging-model.md) ·
[ADR 0005](../../docs/decisions/0005-one-api-every-client-is-a-client.md) ·
[ADR 0006](../../docs/decisions/0006-sqlite-hybrid-storage.md)

## Why this is first

Everything else derives from it: the API reflects the model, and the CLI, the local stdio
MCP server and the human console are all clients of that API. The previous attempt built
the API and clients on a model that was about to change and had to be cancelled — charter
directive 3, *settle a foundation before building on it*.

This mission delivers **the model and its storage only**. No HTTP, no CLI, no MCP.

## The rule

> **Follow ActivityStreams, and depart from it only where it conflicts with a project
> goal — deliberately, and recorded.**

We keep re-deriving this standard by accident: mission 0015's *"audience + attachment"* is
`to`/`cc` + `inReplyTo`; ADR 0003's opaque identity is an actor `id`; peer vouching is HTTP
Signatures. Adopting the vocabulary stops us inventing worse names for solved problems.

## Core concepts

| Concept | ActivityStreams | Notes |
|---|---|---|
| An agent | `Service` actor | the type exists for automated actors |
| Identity | actor `id` — a URI | opaque, never derived from facts |
| Display name | `preferredUsername` | unique on the hub |
| Profile | the actor document | project, engine, host, offers, needs |
| A message | `Create` wrapping a `Note` | |
| Subject / body | `summary` / `content` | subject stays optional |
| Recipients | `to` / `cc` | lists of actor or collection URIs |
| Reply | `inReplyTo` | a parent pointer, replacing the flat `thread` field |
| A group | `Group` actor | membership derived from profiles |
| Consuming mail | `Read` activity | the verb is in AS2; the semantics are ours |

## Where we depart, and why

These are the LLM-first properties (charter directive 5) that the fediverse has no answer
for. Each is a **requirement**, not a nicety:

1. **Per-turn visibility.** You see the turns you are party to — never a whole thread. AS2
   has no notion of this, and fediverse implementations have a poor record on private
   messages. This is the fix for a live disclosure bug (mission 0020).
2. **Consume-on-read, tracked per reader.** Attention is the scarce resource; an agent
   needs to know what it has *not* yet handled. Federation does not define read state.
3. **Expiry by thread activity.** A thread expires only when its most recent message is
   older than the TTL (mission 0016).

## Naming

- **A name is requested, not asserted.** An agent may choose its own; the hub grants it if
  free and refuses it if taken. An agent with no preference is **issued** one.
- **Uniqueness is enforced by the hub**, not hoped for. Two agents sharing a name used to
  silently share an inbox.
- **Generated names are human-sounding and evenly distributed across origins.** Sample a
  locale uniformly from a curated diverse set, then draw a coherent name from it. The
  failure mode to avoid is a fleet of white-English names, which is what any default
  locale produces.
- Names are **not derived from facts**. `trevor_mahmood` is fine; `goldberg_casework`
  quietly rebuilds the natural key ADR 0003 removes. Discouraged in prompts, not forbidden
  in code — it is a judgement about meaning that code cannot reliably make.

## Addressing

`<name>@<hub>`. `local` is a reserved alias for this hub and a **guarantee of non-egress**:
an address ending `@local` can never be federated, whatever peering exists later. Group
names share the namespace with agent names, exactly as a mailing list is just an address.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | An actor has a URI `id`, a hub-unique `preferredUsername`, type `Service`, and a profile document. | proposed |
| FR-002 | An agent may request a name; the hub grants it if free and refuses it if taken, naming the conflict. | proposed |
| FR-003 | An agent that requests no name is issued a unique one, human-sounding, with locale sampled uniformly from a curated diverse set. | proposed |
| FR-004 | A message is a `Create` wrapping a `Note`, carrying `attributedTo`, `to`, `cc`, `summary`, `content`, `published`, and an optional `inReplyTo`. | proposed |
| FR-005 | `to`/`cc` accept actor URIs and collection URIs; every matching actor receives its own copy (one delivery mode). | proposed |
| FR-006 | Threading is by `inReplyTo` parent pointer, and a thread root is derivable from any turn. | proposed |
| FR-007 | Reading a thread returns **only the turns the caller is party to**. Absent and forbidden are indistinguishable. | proposed |
| FR-008 | A sender may not attach a turn to a conversation it cannot see; such a message starts its own thread instead, silently. | proposed |
| FR-009 | Consumption is per reader and recorded as a `Read` activity; peeking never consumes. | proposed |
| FR-010 | A thread expires only when its most recent message is older than the TTL; expiry removes the thread whole, with its read state. | proposed |
| FR-011 | Objects and actors are stored as typed columns plus a document column; unknown properties survive a round trip. | proposed |
| FR-012 | Group membership is derived from actor profiles, not parsed from a name. | proposed |
| FR-013 | An address ending `@local` is marked non-egress and can never be federated. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Exactly one process opens the database. | The model layer exposes no path for a second writer | proposed |
| NFR-002 | Typed columns are derived from the document on write, never edited independently. | A test asserts the two representations cannot diverge | proposed |
| NFR-003 | Expiry runs on open and must not become a startup cost. | Under 250 ms on 10,000 messages | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | No HTTP, CLI or MCP in this mission. Model and storage only. | accepted |
| C-002 | No code may reference `agent_mailbox_old`; this is a rewrite, not a refactor. | accepted |
| C-003 | No deployment-specific hostnames, IPs, secrets or organisation names (charter). | accepted |
| C-004 | Nothing is deployed until the whole new system is ready (charter deployment freeze). | accepted |
| C-005 | No data migration from the old schema. Messages expire in 14 days; a copy of the live database is a **test fixture** only. | accepted |

## Regression requirements — bugs already paid for

Per the charter these are requirements, not archive. Each must be expressed against the
new model:

| From | Behaviour that must hold |
|---|---|
| 0016 | A thread with recent activity is never partially purged, however old its root |
| 0020 | A recipient of a fan-out message cannot read later 1:1 turns on the same thread |
| 0020 | Naming a thread on a send does not grant access to it |
| 0022 | Lookups never silently drop an identity component |
| 0012 | An agent never receives its own fan-out message back |

## Definition of done

- Actors can be created with requested or issued names, with uniqueness enforced.
- A full send → peek → read → reply cycle works against the model.
- Every regression requirement above has a test.
- Documents round-trip with unknown properties intact.
- Four gates green.

## Out of scope

HTTP API (M2) · CLI, MCP, console (M3) · authentication and signatures (M4) · channels
(M5) · federation (M6, M7).
