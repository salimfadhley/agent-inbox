# Mission brief — comparative survey of inter-agent messaging systems

**Status:** planned · **Kind:** research, no code · **Raised:** 2026-07-24 by the owner
**Dependencies:** none. **Sequencing:** after the client work (M3).
**Source prompt:** kept verbatim at [`research/competitive-survey-prompt.md`](../research/competitive-survey-prompt.md)

## What this is

A survey of the competitive landscape, to find **ideas worth stealing**. Research only —
the output is a report and a ranked list of candidate missions, not a change to the code.

## Systems to study

**Direct competitors** — mailboxes for local coding agents:

| System | Character |
|---|---|
| [MCP Agent Mail](https://mcpagentmail.com/) | Feature-maximal: threads, search, file-reservation leases, git+SQLite dual persistence, TUI and web dashboards, @mention scanning, build slots, macros |
| [postal-mcp](https://github.com/tkellogg/postal-mcp) | Minimalist: SQLite queue, per-agent URLs, and a **blocking `check_mailbox()`** — their answer to the push problem |
| mailbox-mcp and file-convention systems | `.claude/{inbox,outbox}/*.md` wrapped in MCP tools |

**Adjacent standards:** A2A (Agent Cards, task lifecycle, push notifications) ·
AgentMail (email API for agents) · LangChain "Agent Inbox" (mostly a name collision).

**Federation prior art:** SMTP · XMPP (JIDs, and note the *resource* part maps
suggestively onto our agent-instance problem) · ActivityPub · Matrix · NATS subjects.

## What makes this worth doing now

Two of these are directly load-bearing for decisions we have already taken, and the
survey is a chance to find out whether we took them well:

- **postal-mcp's blocking `check_mailbox()`** is precisely the design we *cancelled* in
  mission 0003, on the grounds that blocking breaks real MCP clients. Someone shipped it
  anyway. Either they know something we do not, or they will hit what we predicted —
  worth finding out which, because we are about to build push properly in M5.
- **ActivityPub** we have already adopted the model of (ADR 0004) without adopting the
  stack. A close reading of what fediverse implementers actually hit — spam across
  instances, identity portability, delivery retries, versioning — is exactly the input
  missions 0024 and 0025 need.

## Deliverable

1. A comparison table across delivery model, identity and addressing, threading and
   lifecycle, and human oversight.
2. A **ranked list of learnings to adopt** — each naming the source system, the
   mechanism, the concrete change it implies here, and an S/M/L estimate. These become
   candidate missions.
3. A ranked list of **things to deliberately not adopt**, with reasons. This half
   matters as much: it is what guards the project's simplicity, and it is the half a
   survey usually skips.
4. The federation and naming analysis, with a recommended addressing scheme.
5. Sources, with the version, commit or date actually read.

## How to run it

**Read the source, not the marketing.** A feature list tells you what a system claims;
the code tells you what it does, and the issue tracker tells you what it costs.

**Bias toward candour.** If a competitor is simply better for some user, say so and
describe that user. If a federation idea is seductive and wrong for a single-file SQLite
store, say that too. A survey that concludes we are best at everything has not been done.

## A caveat on the prompt

The source prompt describes the system as it was in July 2026 — `project/agent/role`
addressing, `project/any` queues, the `/ui` console. Since it was written the model has
been rebuilt: identity is now an opaque assigned name ([ADR 0003](../decisions/0003-identity-is-a-surrogate-key.md)),
`any` is retired, and the messaging model follows ActivityStreams
([ADR 0004](../decisions/0004-activitystreams-messaging-model.md)).

The research questions still hold — the naming redesign it anticipates is the one we
have now done, so the findings become a **check on decisions already taken** rather than
input to an open one. Where a finding contradicts an ADR, that is the most valuable
thing the survey can produce, and it should be reported rather than reconciled away.

## Non-goals

- Building anything. Ideas that survive become their own missions.
- Adopting a competitor's feature because it exists. The bar is whether it earns its
  complexity *here*, for LLM correspondents, on one lightweight container.
