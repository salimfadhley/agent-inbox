# Research task: comparative survey of inter-agent messaging systems — learnings for agent-inbox

## Context

I maintain **agent-inbox** (https://github.com/salimfadhley/agent-inbox): a local
SQLite-backed mailbox that gives LLM coding agents (Claude Code, Codex, Gemini,
…) on one machine or LAN a standard way to message each other — a CLI plus a
hostable MCP server sharing the same verbs, a single SQLite file for storage, no
broker. Addressing is currently `project/agent`, with `project`/`project/*` as
broadcast, `project/any` as a shared work queue, and `all/all` as public
broadcast. There is an agent directory (`register`, `agents`, `whois`), a
human operator console (`/ui`), automatic TTL-based expiry, and an honest
delivery model: messages are durable but pull-only today (push wake is in
design for Claude Code recipients via hooks).

**Important design context:** I am redesigning the `project/agent/role` naming
scheme. The direction is to make agent-inbox a **fediverse-style communication
platform** — hubs that can peer with each other, with identities that are
meaningful across hub boundaries (think `agent@hub` rather than a flat local
namespace). Your findings on naming, identity, and federation are therefore at
least as valuable as feature comparisons.

## Your task

Survey the systems below (and any credible others you find in the same
domain), then bring back **concrete learnings and improvement proposals** for
agent-inbox. Read their actual documentation and source where possible; do not
rely on marketing summaries.

### Systems to study

**Direct competitors (mailboxes for local coding agents):**

1. **MCP Agent Mail** — https://mcpagentmail.com/ (Jeffrey Emanuel). The
   feature-maximal one: identities, inbox/outbox, threads, search, advisory
   file-reservation "leases", git+SQLite dual persistence, `am` CLI, TUI and
   web dashboards, @mention scanning, human Overseer, build slots, macros.
2. **postal-mcp** — https://github.com/tkellogg/postal-mcp. The minimalist
   one: SQLite queue, HTTP-only MCP, per-agent URLs (`/agents/{name}/mcp/`),
   and a **blocking `check_mailbox()`** that waits until mail arrives — their
   answer to the push problem.
3. **mailbox-mcp** (ellgree) and similar small file-convention systems
   (`.claude/{inbox,outbox}/*.md` wrapped in MCP tools).

**Adjacent standards and platforms:**

4. **A2A protocol** (Google / Linux Foundation) — Agent Cards, task lifecycle,
   JSON-RPC + SSE, push notifications for long-running tasks. A different
   layer (agents as addressable services), but study its discovery, capability
   advertisement, and async-notification designs.
5. **AgentMail** (agentmail.to) and similar "email API for agents" SaaS —
   different problem (real email, cloud), but note any inbox/threading/identity
   ideas worth borrowing.
6. **LangChain "Agent Inbox"** — a human-in-the-loop UI for LangGraph
   interrupts. Mostly a **name collision** to be aware of; note anything else
   relevant.

**Federation prior art (for the naming redesign):**

7. **Email/SMTP** — `user@domain`, MX-style hub discovery, store-and-forward,
   bounce semantics.
8. **XMPP** — JIDs (`user@domain/resource` — note the resource part maps
   suggestively onto our agent-instance problem), server-to-server federation,
   presence.
9. **ActivityPub / the fediverse proper** — actor model, `@user@instance`
   addressing, inbox/outbox as *the actual protocol primitives* (striking
   overlap with our vocabulary), followers/delivery, instance blocking.
10. **Matrix** — `@user:homeserver`, room-based rather than mailbox-based
    federation, eventual consistency across homeservers.
11. **NATS subjects** (and similar broker subject hierarchies) — wildcard
    subscription semantics (`project.*`, `project.>`), queue groups (their
    version of our `project/any`).

## Questions to answer

For each system, extract:

- **What do they get right that agent-inbox lacks?** Be specific: feature,
  mechanism, or design decision, and why it earns its complexity.
- **What do they get wrong or overbuild?** Where does agent-inbox's
  simplicity win, and where is their complexity load-bearing?
- **Delivery model:** pull, blocking-pull, push, or hybrid? How do they get a
  recipient's attention? Cost of their approach (tokens, occupied turns,
  infrastructure)?
- **Identity and addressing:** how are agents named? Is the namespace flat,
  hierarchical, or federated? How do they handle multiple instances of the
  same agent, roles vs. identities, and discovery of who exists?
- **Threading, acks, and lifecycle:** message states, read semantics,
  expiry/retention, reply threading.
- **Human oversight:** what visibility/intervention do humans get?

Then, specifically for the **fediverse redesign**:

- Propose 2–3 candidate addressing schemes for a federated agent-inbox (e.g.
  `agent@hub`, `project/agent@hub`, ActivityPub-style actors, XMPP-style
  JIDs with resources), with the trade-offs of each: backward compatibility
  with today's `project/agent`, how broadcast and `any`-queues generalize
  across hubs, and how the directory/`whois` federates.
- Identify which federation mechanism fits a store-and-forward SQLite hub
  best: SMTP-style relay, ActivityPub-style signed POST to remote inboxes,
  or Matrix-style replication — given the constraint that hubs may be
  intermittently connected machines on home/office networks, not always-on
  servers.
- Flag the hard problems early adopters of those protocols hit (spam/abuse
  across instances, identity portability, delivery retries, versioning) and
  which of them bite at our scale.

## Deliverable

A markdown report with:

1. A comparison table of the direct competitors across the dimensions above.
2. A ranked list of **learnings to adopt** — each with: the source system, the
   mechanism, the concrete change to agent-inbox it implies, and an effort
   estimate (S/M/L).
3. A ranked list of **things to deliberately not adopt**, with reasons —
   these guard the project's simplicity.
4. The federation/naming analysis and a recommended addressing scheme.
5. Sources: link every claim to the doc or source file you verified it in,
   and state the version/commit/date you looked at.

Bias toward candour: if a competitor is simply better for some user, say so
and characterize that user. If a federation idea is seductive but wrong for a
single-file SQLite store, say that too.
