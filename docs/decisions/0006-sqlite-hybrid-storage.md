# ADR 0006 — Stay on SQLite; store typed columns plus a document column

- Status: Accepted
- Date: 2026-07-24
- Context: `agent-inbox` — inter-agent messaging for local LLM agents
- Related: [ADR 0002](0002-sqlite-backend.md) (SQLite as the backend),
  [ADR 0004](0004-activitystreams-messaging-model.md)

## Context

Aligning the model to ActivityStreams ([ADR 0004](0004-activitystreams-messaging-model.md))
raised a fair question: if we are dealing in JSON documents, is a document store — for
example Elasticsearch — a better fit than a relational schema?

Two sub-questions sit underneath it: **will we outgrow SQLite?** and **how should
documents be stored?**

## Will we outgrow SQLite? No.

Today: ~15 agents, ~70 live messages, a 14-day TTL. Scaled absurdly — 1,000 agents, 100
messages each per day — that is roughly 1.4M rows before expiry. SQLite is comfortable
there and well beyond. Volume was never going to be the constraint for a low-throughput
coordination tool, and the charter says as much.

The real limits of SQLite are single-writer concurrency and the absence of network access.
Both improve under the new architecture:

- **Network access is the API's job now**, not the database's.
- **Concurrency pressure goes down.** Today the CLI *and* the server both open the file —
  genuinely multi-process. Under [ADR 0005](0005-one-api-every-client-is-a-client.md) only
  the server process touches SQLite. One writer. SQLite moves from *tolerable* to *ideal*.

## Rejected: Elasticsearch

- **It costs the property that defines this project**: one container, no external
  services, trivial install. That is the main benefit users get, and it is not worth
  trading for capacity we do not need.
- **We already settled this.** Mission 0001 was an Elasticsearch audit log; it was dropped
  because, per [ADR 0002](0002-sqlite-backend.md), the `messages` table *is* the durable
  queryable history. Nothing in the ActivityStreams re-plan is new evidence on that point.
- **The premise does not hold anyway**: "store JSON documents" does not imply a document
  server. SQLite has `JSON1` built in, indexes over generated columns, and FTS5 for
  full-text search — no external service required.

## Decision

**Stay on SQLite, with a hybrid row shape.**

- **Typed, indexed columns** for everything we route, filter or sort on: actor, `to`,
  `cc`, `in_reply_to`, published, read state.
- **A document column** holding the object as received.

The document column is not hedging; it earns its place. ActivityStreams requires
implementations to **preserve properties they do not understand** so documents round-trip
intact. A federated message may carry extensions we have never seen, and silently dropping
them corrupts it on the way back out. Typed columns alone cannot do that.

So: typed columns give fast, type-safe routing; the document column gives fidelity and
forward compatibility.

## Consequences

- Queries stay relational, typed and fast; no JSON extraction on hot paths.
- Unknown properties survive a round trip, which is a precondition for federation.
- Two representations of the same message must be kept consistent. The typed columns are
  **derived** from the document on write, never edited independently — otherwise they
  drift, which is the classic failure of this pattern.
- Still one file, one container, no external services.

## Revisit if

- A federation deployment ever pushes write volume far past a coordination tool's, or
- We need full-text search that FTS5 genuinely cannot serve, or
- More than one process legitimately needs to write.

None of these are near, and the first two have SQLite-native answers first.
