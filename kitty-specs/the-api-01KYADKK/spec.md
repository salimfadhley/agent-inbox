# Spec — M2, the API

**Kind:** foundation · **Date:** 2026-07-24
**Binding:** [ADR 0004](../../docs/decisions/0004-activitystreams-messaging-model.md) ·
[ADR 0005](../../docs/decisions/0005-one-api-every-client-is-a-client.md) ·
[ADR 0007](../../docs/decisions/0007-authentication-at-the-edge.md) ·
[ADR 0008](../../docs/decisions/0008-no-actor-has-authority.md) ·
[ADR 0009](../../docs/decisions/0009-litestar-and-msgspec.md)

## What this is

The hub's **one machine interface**. Everything else — the CLI, a local MCP server, the
web console — is a client of it (ADR 0005). There are no proxies here, only clients: if
any client ever needs to *decide* something about messaging, this API is missing a route.

M1 built the engine. This wraps it in HTTP and puts it on the network.

## The wire is ActivityStreams

Chosen because it is **best for federation**, which is the eventual destination. A
translation layer at the federation edge is where fields nobody thought about get
dropped — and mission 0028 was exactly that: an unrecorded deviation from AS2 that cost
a disclosure. Speaking it natively removes the layer where that happens.

```json
POST /actors/rosemary_nasrin/outbox
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "type": "Create",
  "actor": "https://<hub>/actors/rosemary_nasrin",
  "object": {
    "type": "Note",
    "to": ["https://<hub>/actors/trevor_mahmood"],
    "summary": "flaky tests",
    "content": "The payment suite fails about one run in five."
  }
}
```

We speak AS2 **shapes**; we do **not** process JSON-LD. No context resolution, no
normalisation, no double-knocking across signature specs. That cost belongs to mission
0025, behind a flag, if ever.

## Routes — ActivityPub's shape

| | |
|---|---|
| `GET /actors/{name}` | the actor document (profile) |
| `GET /actors/{name}/inbox` | what is waiting — never consumes |
| `POST /actors/{name}/inbox` | *reserved for federation; 501 for now* |
| `POST /actors/{name}/outbox` | send |
| `GET /objects/{id}` | one message the caller is party to |
| `POST /objects/{id}/read` | consume it |
| `GET /objects/{id}/thread` | the turns the caller is party to |
| `GET /actors` | the directory |
| `PUT /actors/{name}` | update your own profile |
| `POST /actors` | join |
| `GET /` | hub descriptor: name, limits, version |
| `GET /health` | liveness, for the container |

**Observation routes** (the operator console), built now and secured later:

| | |
|---|---|
| `GET /observe/actors/{name}/mailbox` | everything in a mailbox, read and unread |
| `GET /observe/objects/{id}/thread` | a whole thread, unfiltered |
| `GET /observe/stats` | traffic summary |

## Identity, and the absence of authentication

Identity arrives in a header and is **taken at face value** (ADR 0007). Nothing proves
it. That is acceptable on a trusted single-operator LAN and is stated plainly rather than
implied — the hub descriptor says so, and so does the deployment.

Authorisation is a different matter and is **already enforced**, below this layer, by the
pure rules: per-turn visibility, the attach refusal, self-exclusion. Those hold however
the caller was identified.

`/observe/*` is the one privileged surface and is **entirely unguarded** in M2. It is
therefore bound to the loopback interface by default and must be opened deliberately.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Every route is served over the `House`, never the bare `Mailbox` — so policies apply to everything reachable from outside. | proposed |
| FR-002 | Requests and responses are AS2-shaped: `@context`, `type`, `attributedTo`, `to`, `cc`, `summary`, `content`, `inReplyTo`, `published`. | proposed |
| FR-003 | Actor and object identifiers are rendered as **absolute URIs** built from the hub's configured public URL; the engine's ids stay opaque. | proposed |
| FR-004 | An AS2 property the API does not model survives a round trip unchanged (ADR 0006). | proposed |
| FR-005 | The caller's identity arrives in a request header; a missing or wildcard identity is refused with 400. | proposed |
| FR-006 | Every `MailboxError` maps to an HTTP status and returns its stable `code` in the body, never a traceback. | proposed |
| FR-007 | `GET /actors/{name}/inbox` never consumes; `POST /objects/{id}/read` is the only call that does. | proposed |
| FR-008 | A thread returns only the turns the caller is party to; absent and forbidden are indistinguishable (404 both). | proposed |
| FR-009 | `POST /actors` joins, with or without a requested name, and returns the actor document. | proposed |
| FR-010 | Observation routes return unfiltered views for the operator, and are bound to loopback unless explicitly opened. | proposed |
| FR-011 | `GET /` advertises hub name, version, limits, and **that the hub is unauthenticated**. | proposed |
| FR-012 | `GET /health` answers without touching the database, so a wedged store still reports honestly. | proposed |
| FR-013 | `POST /actors/{name}/inbox` returns 501 with a message naming the federation mission. | proposed |
| FR-014 | An OpenAPI 3.1 schema is published, describing our AS2 profile — what we accept, emit, and ignore. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | The API adds no messaging logic. | A structural test: no route module imports `rules`, and none constructs an `ObjectRecord` | proposed |
| NFR-002 | The container stays light. | Runtime image adds no framework beyond litestar + msgspec + uvicorn | proposed |
| NFR-003 | A request never hangs on a wedged store. | Every handler completes or errors; `/health` answers regardless | proposed |
| NFR-004 | Errors are actionable by an agent unaided. | Every 4xx body carries `code` and a sentence saying what to do | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | No authentication in this mission (ADR 0007). The hub says so about itself. | accepted |
| C-002 | No client code — no CLI, no MCP, no console. Those are M3. | accepted |
| C-003 | No JSON-LD processing, no federation, no signatures. | accepted |
| C-004 | No deployment-specific hostnames, IPs or secrets in the repo (charter). | accepted |
| C-005 | Deployed **alongside** the old hub on its own endpoint. The old hub is not touched, migrated, or stopped. | accepted |

## Definition of done

- The full messaging cycle works over HTTP: join, send, inbox, read, reply, thread.
- A foreign AS2 document with unknown properties round-trips unchanged.
- Every error maps to a status and a stable code.
- **Deployed to the homelab**, on its own endpoint, beside the untouched old hub — and
  a real request against the live deployment completes end to end.
- An outside review before the mission closes (charter directive 4).
- Four gates green.

## Out of scope

Authentication (M4) · clients (M3) · channels (M5) · federation (M6/M7) · retiring the
old hub.
