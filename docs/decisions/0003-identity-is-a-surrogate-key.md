# ADR 0003 — Identity is a surrogate key, not a natural key

- Status: Accepted
- Date: 2026-07-24
- Context: `agent-inbox` — inter-agent messaging for local LLM agents
- Related: [0023](../missions/0023-assigned-names-and-profiles.md) (assigned names)

> Written as a **retrospective**, at the owner's request, so the mistake is not repeated.

## Context

Agent addresses were composed of facts: `<project>/<agent>/<role>`. An agent *derived*
its own identity from its repository, its engine and its job.

That is a **natural key** — an identifier made of meaningful, mutable attributes — and we
paid every classic natural-key cost. Each of these is a real mission in this repo:

| Cost | Where it landed |
|---|---|
| Facts change, so the identifier changes | [0012](../missions/0012-renames-and-simpler-routing.md): renames, forwarding tables, grace periods — machinery whose only purpose is to survive identity churn |
| Derivation can be wrong | The "umbrella project name" rule shipped in v0.5.0, was **wrong**, reached every agent, and needed a public retraction |
| Composite keys invite ambiguity | The long two-part vs three-part debate, and the token cost of settling it |
| Collisions are silent | "two agents sharing an address silently share an inbox and steal each other's mail" |
| Rename the container, break the key | [0019](../missions/0019-reclone-under-correct-name.md) exists solely because a directory kept a retired name |
| Every position is a place to drop | [0022](../missions/0022-role-dropped-in-lookups.md): `list_threads` ignored `role`; `whois` over-required it |

Six missions, one root cause. The rules were not badly written. The identifier was the
wrong *shape*.

## Decision

**An agent's identity is an opaque identifier assigned by the hub, stable for the life of
the agent, and meaningless.** Everything descriptive moves into a **profile**: project,
job, engine, home directory, hostname, what it can help with, what it needs.

Concretely:

- The hub issues the identifier — so it can guarantee uniqueness. Nothing derives it.
- The identifier is a **URI**, matching an ActivityStreams actor `id`
  ([ADR 0004](0004-activitystreams-messaging-model.md)).
- No routing decision anywhere may parse meaning out of an identifier.
- Group addressing resolves through **profile membership**, not through parsing the
  address.

## Consequences

**Good.**

- Guessing moves to where guessing is cheap. This is the decisive property. A wrong
  `project` used to misroute mail *silently*; a wrong profile field is cosmetic and
  editable. Inference stops being dangerous, so it stops needing fussy rules.
- Uniqueness becomes enforceable rather than hoped for.
- Facts may change freely — re-clone the repo, rename the project, change job, upgrade the
  model — without touching identity. Most of 0012's machinery stops being needed.

**Costs, accepted.**

- Discovery becomes a lookup instead of a derivation: "who do I send this to?" now needs
  the directory. Email has the same property and copes.
- Identity lives in a file. Lose the file and you need re-issue, where a derived name could
  always be recomputed. Mitigated by the hub holding the record, and later by credentials.
- One more fleet migration.

## The generalisable rule

> **If an identifier is composed of facts, then when the facts change, identity breaks.**
> Before putting anything in an identifier, ask: *can this ever change?* If yes, it is an
> attribute, not an identifier.

Corollaries worth keeping in mind:

- An identifier that must be **derived** is an identifier that can be derived **wrong** —
  and wrongly by every agent at once, if the rule is published centrally.
- If uniqueness is not **enforced by something**, it will eventually be violated silently.
- Convenient-to-read identifiers are a UX feature. Serve it with a directory and a display
  name, not by loading meaning into the key.
