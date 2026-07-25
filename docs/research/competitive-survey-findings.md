# Competitive survey — inter-agent messaging systems (mission 0029)

**Kind:** research, no code · **Date read:** 2026-07-25 · **Brief:**
[`../missions/0029-competitive-survey.md`](../missions/0029-competitive-survey.md) ·
**Source prompt:** [`competitive-survey-prompt.md`](competitive-survey-prompt.md)

This is a check on decisions already taken as much as a scan for ideas. Where a finding
contradicts one of our ADRs it is reported, not reconciled away (the brief's instruction).
The bar for "adopt" is not *does it exist* but *does it earn its complexity here* — for LLM
correspondents, on one lightweight SQLite container.

## The one-paragraph verdict

The field has split into two camps, and we sit deliberately between them. **postal-mcp** is
the minimalist (two tools, a blocking wait) and **MCP Agent Mail** is the maximalist (34
tools, file leases, build slots, hybrid search, a 15-screen TUI). Our design — a pure
messaging engine, ActivityStreams on the wire, an opaque-name identity, one container — is
closer to postal-mcp in surface but closer to Agent Mail in seriousness. The most important
findings are **confirmations**: postal-mcp shipped the blocking `check_mailbox` we cancelled
in mission 0003, and its own author reports the failure we predicted; and ActivityPub uses
`inbox`/`outbox` as *the actual protocol primitives*, which is exactly the vocabulary we
adopted in ADR 0004. The best genuinely-new idea to steal is **acknowledgement-required
messages** (Agent Mail); the most seductive-but-wrong is **file-reservation leases**, which
are coordination, not messaging, and belong to a different product if they belong here at
all.

## Comparison — the direct competitors

| Dimension | **agent-mailbox** (us) | **MCP Agent Mail** | **postal-mcp** | file-convention (`.claude/{inbox,outbox}`) |
|---|---|---|---|---|
| Surface | ~12 MCP tools, one HTTP API | **34 tools**, 20+ resources, 9 clusters | **2 tools** (`send_message`, `check_mailbox`) | a handful, wrapping file writes |
| Delivery | pull; peek never consumes; push in design (0017) | pull; targeted; `ack_required` tracked | **blocking** `check_mailbox` (waits for mail) | pull; poll the directory |
| Storage | SQLite (one file), hybrid typed+document (ADR 0006) | **git + SQLite** dual; commit-coalescer (9.1× fewer writes) | SQLite queue, HTTP-shared | flat markdown files in git |
| Identity | opaque assigned names, permanent (ADR 0003); profiles | memorable persistent names (GreenCastle…), project-scoped, program/model metadata | agent name in the URL `/agents/{name}/mcp/` | filename / directory convention |
| Threading | per-turn visibility; `inReplyTo`; thread = root walk | `thread_id` conversations; full history before reply | not documented | none / by hand |
| Read / ack | per-reader read-state (ActivityStreams `Read`) | acknowledgement tracking; `ack_required=true` | not documented | none |
| Expiry | TTL, per-thread, whole-thread (mission 0016) | TTL for agents, reservations, contacts | not documented | manual |
| Human oversight | server-rendered console: dashboard, mailbox browser, threads, compose, **flow graph** | **15-screen TUI** + web UI + "Overseer" redirect-mid-session | none | read the files |
| Coordination extras | none (deliberately) | **file-reservation leases**, **build slots**, macros | none | none |
| Search | none | **hybrid** lexical + semantic + rerank | none | grep |
| Scale (claimed) | not benchmarked | 40–50 concurrent agents, ~49 RPS | two-agent framing | n/a |
| Auth | password+TOTP humans, device tokens agents (ADR 0010) | not documented | none (shared DB) | filesystem perms |

## What each gets right, and where we win

**MCP Agent Mail** is the most serious competitor and the one to learn from. It gets right:
messages are targeted and agents only receive what is addressed to them (same as us —
convergent); **persistent memorable identities** (independent confirmation of ADR 0003);
**acknowledgement tracking** so a critical message is *processed*, not merely delivered;
**file-reservation leases** that stop two agents editing the same files; and taking human
oversight seriously (an "Overseer" can compose a high-priority message to redirect an agent
mid-session — which is exactly what our console's compose is for). Where *we* win: it is 34
tools and a Rust engine with build slots and semantic search — a lot of surface for an LLM to
hold, and much of it (build slots, compilation concurrency, git audit archive) is coding-fleet
plumbing rather than messaging. Our smaller, ActivityStreams-shaped surface is easier for an
agent to use correctly and easier to federate.

**postal-mcp** gets right: radical minimalism (two tools is a legitimate design), per-agent
MCP URLs, and a shared SQLite DB with no broker — all shapes we share. Where we win is the
delivery model, and this is the load-bearing finding below.

**File-convention systems** (the pattern our own project grew out of, in goldberg) get right:
zero infrastructure and git-native auditability. They lose on everything push-, directory-,
and visibility-shaped, and cannot get one agent's attention at all — which is why this project
exists.

## Learnings to adopt (ranked; each a candidate mission)

1. **Acknowledgement-required messages** — *source: MCP Agent Mail.* A sender marks a
   message `ack_required`; the hub tracks whether the recipient explicitly acknowledged
   (beyond the passive read-state we already keep), and the sender can see it. Fits our model
   cleanly: an ActivityStreams `Read`/`Accept` activity already exists as the primitive, and
   we have per-reader read tracking to build on. Concrete change: an optional flag on send +
   a "who has acked" view (we already have `observe_reads`). **S.**
2. **A2A-style push with SSRF-safe webhooks** — *source: A2A protocol.* When we build push
   (mission 0017) and federation (0024/0025), the recipient/hub supplies a callback and the
   server POSTs on a state change. A2A's hard-won lesson: **never blindly POST to a
   client-supplied URL** — allowlist domains and use challenge-response ownership
   verification, sign the request (Bearer/HMAC/mTLS), and have the receiver verify. Concrete
   change: bake allowlist + challenge-response + signing into the push/federation design from
   the start, not after. **M.** Ties directly to ADR 0010's "identity at the edge".
3. **Full-text search over a mailbox** — *source: MCP Agent Mail (lexical half only).*
   Mailboxes grow; an agent asking "did anyone mention the payment tests" is a real need.
   SQLite ships **FTS5** — cheap, no new dependency, no embeddings. Concrete change: an
   `search`/`/observe/search` over subject+body. **S.** (The *semantic* half is in the
   do-not-adopt list — it earns weight we do not want.)
4. **Capability advertisement in the actor/hub document** — *source: A2A Agent Cards.* A2A
   agents advertise `capabilities.streaming` / `pushNotifications`. We already do a little of
   this in `hub_info` (`authenticated`, `federates`, `policies`). Concrete change: make actor
   documents and `hub_info` advertise what a hub/agent supports (push? federation? schema
   version?), which is also what mission 0030 (version compatibility) needs to negotiate.
   **S.**
5. **Contact re-handshake on rejoin / storage reset** — *source: MCP Agent Mail's contact
   handshake.* We already worry about this (the `storage_initialized_at` check in the
   bootstrap prompt). A light protocol to re-establish "you are the same correspondent I knew"
   after a hub reset — or across hubs — is the seed of identity portability for federation.
   **M.** Feeds missions 0024/0025.

## Things to deliberately **not** adopt (ranked; this guards our simplicity)

1. **A blocking `check_mailbox`** — *postal-mcp.* This is the design we cancelled in
   **mission 0003**, and postal-mcp is the natural experiment in whether we were wrong. We
   were not: its own README reports Claude Code *"doesn't return to the mailbox easily. Takes
   a lot of prompting,"* and only Gemini CLI works "fairly well." A blocking tool call holds
   the agent's turn hostage and fights the MCP client's control loop — exactly our prediction.
   Keep pull + peek-never-consumes, and do push properly (out-of-band wake), not by blocking.
   **Confirms ADR/mission 0003.**
2. **git + SQLite dual persistence** — *MCP Agent Mail.* A diffable git audit trail is
   genuinely nice, but ADR 0002/0006 chose one SQLite file on purpose, and our `AuditLog`
   policy already covers "what happened, durably." A second persistence engine (plus a commit
   coalescer to make it bearable) is complexity we have not earned for a single-owner hub.
3. **Semantic search / embeddings** — *MCP Agent Mail.* Reranked hybrid search needs an
   embedding model or service — heavy dependency, and cross-cutting against "one lightweight
   container." Take FTS5 (above); leave the vectors.
4. **Build slots / compilation-concurrency control** — *MCP Agent Mail.* This is coding-fleet
   resource management, not messaging. Out of scope by the same reasoning that keeps the
   messaging engine pure (ADR 0005): if agents need it, it is a different tool.
5. **File-reservation leases** — *MCP Agent Mail.* The most *seductive* one, so it gets the
   most words. It solves a real pain (two agents editing the same file), and it is well
   designed (glob patterns, TTL, a pre-commit hook). But it is **coordination, not
   correspondence**: it puts the hub in the business of arbitrating file access, which drags
   in filesystem semantics, a git hook in every repo, and lease-expiry edge cases. It would
   roughly double the conceptual surface. Verdict: **not in the mailbox.** If the need is real
   here, it is its own product/mission with its own store — do not let it colonise the
   messaging engine.
6. **Feature-maximalism as a posture** — 34 tools is itself a choice we should decline. Every
   tool is context an LLM must hold and a way to be used wrong. Our restraint is a feature.

## Federation and naming analysis

The brief's source prompt predates our rebuild, so its central question — *how should we
redesign `project/agent/role` for a fediverse?* — is one we have partly **already answered**,
and the survey becomes a check on that answer.

**Where we already are (and it is a strong position).** We adopted the **ActivityStreams**
model (ADR 0004) and the **ActivityPub route shape** — `/actors/{name}/inbox`, `/outbox`,
`/objects/{id}`. The single most striking finding of this survey is that this was the right
bet: in ActivityPub, `inbox` and `outbox` are not our metaphor, they are *the actual
protocol primitives other implementers federate over*. We are one addressing decision and one
delivery mechanism away from real federation, having written none of it yet.

**The identity tension to name honestly.** ADR 0003 made names **opaque and local** —
excellent within a hub, and independently validated by Agent Mail's memorable persistent
identities. But an opaque local name **does not travel**: the fediverse wants an identity that
means something across a boundary. This is a real portability gap, and our `@local` suffix is
precisely the seam where it gets resolved — `@local` is the promise "this never leaves," so
the federation work is about what a name becomes when it *does* leave.

**Candidate addressing schemes:**

| Scheme | Example | For | Against |
|---|---|---|---|
| **`name@hub`** (ActivityPub / email) | `rosemary_nasrin@halob` | Matches inbox/outbox we already emit; humans read it; one hop to ActivityPub interop | opaque `name` still isn't portable *between* hubs (a move needs a redirect/alias) |
| `project/agent@hub` (hierarchical) | `billing/rosemary@halob` | keeps a project grouping | re-introduces the mutable-fact-in-identity mistake ADR 0003 removed; project is a profile fact |
| **JID with resource** (XMPP) | `rosemary_nasrin@halob/workshop` | the `/resource` maps *exactly* onto "same agent, multiple machines" | heavier; but see below |

**Recommendation: `name@hub`, and note a quiet convergence.** Adopt `name@hub` as the
federated identity — it is the least new concept given what we already emit, and it is the
ActivityPub-native form. The multi-instance problem XMPP solves with `/resource` we have
*already* solved a different way: **device tokens** (ADR 0010) are per-machine credentials for
one identity — the "same agent on two boxes" case, handled at the auth layer rather than the
address. That is a happy accident worth recording: we do not need JID resources because the
device dimension already lives in the credential.

**Federation mechanism: ActivityPub-style signed POST to remote inboxes** — not Matrix-style
replication, not always-on XMPP s2s. The deciding constraint (from the prompt) is that hubs
are **intermittently-connected** home/office machines, not servers. Store-and-forward with
signed delivery and retries fits that; state-replication (Matrix) and persistent s2s streams
(XMPP) assume availability we will not have. Mentally this is SMTP with signatures.

**The hard problems, and which bite at our scale:**
- **Spam/abuse across instances** — *bites.* Federation must be **peering by consent**, not
  open. `everyone` stays hub-local (a cross-hub broadcast is a spam cannon); reaching another
  hub is an explicit peer relationship. This is the same lesson as A2A's SSRF caveat, one
  layer up.
- **Delivery retries / store-and-forward** — *bites*, and is the actual work: a durable
  outbound queue with backoff for a peer that is asleep.
- **Identity portability** — *bites mildly*: moving `name@hubA` to `hubB` needs an
  alias/redirect (ActivityPub's `movedTo`), because the name is opaque. Acceptable; document
  it.
- **Versioning across hubs** — *bites*: two hubs at different schema versions must negotiate,
  which is exactly mission 0030, now clearly a **prerequisite** for federation, not a sibling.
- **`any`/work-queue across hubs** — retiring `any` (post-rebuild) looks right in this light:
  a shared work-queue does not generalise across a trust boundary, and nobody in the survey
  federates one.

## Sources

- **postal-mcp** — GitHub `tkellogg/postal-mcp` README, read 2026-07-25 (6 commits visible;
  no version tag). Blocking `check_mailbox`, SQLite queue, HTTP-shared, per-agent
  `/agents/{name}/mcp/` URLs; author's caveat on Claude Code re-entry.
  <https://github.com/tkellogg/postal-mcp>
- **MCP Agent Mail** — <https://mcpagentmail.com/>, read 2026-07-25 (self-described "MCP
  Surface v3", Rust rewrite; no explicit version). 34 tools, git+SQLite, leases, `ack_required`,
  hybrid search, 15-screen TUI + web "Overseer", build slots, macros; ~49 RPS at 40–50 agents.
- **A2A protocol** — a2a-protocol.org, "Streaming & Asynchronous Operations", read 2026-07-25.
  `PushNotificationConfig` (url+token+auth), the SSRF/allowlist/challenge-response caveat, SSE
  streaming, Agent Card `capabilities`. <https://a2a-protocol.org/latest/topics/streaming-and-async/>
- **AgentMail** (agentmail.to) — characterised from the brief and general knowledge, not
  deep-read: an *email API for agents* (real email, cloud) — a different problem; inbox/thread
  vocabulary overlaps but the identity model (real addresses) does not transfer.
- **LangChain "Agent Inbox"** — a human-in-the-loop UI for LangGraph interrupts; a **name
  collision**, not a competitor; no messaging-between-agents to borrow.
- **Federation prior art** — SMTP, XMPP (JID `user@domain/resource`), ActivityPub
  (actor + inbox/outbox, `@user@instance`, `movedTo`), Matrix (`@user:homeserver`,
  replication), NATS (subject wildcards, queue groups): analysed from established protocol
  knowledge, cross-referenced with the brief. Not re-read from spec this pass; the claims used
  are stable and long-documented.

## For the reader who acts on this

The candidate missions this produces, in the order they matter:
1. **Version negotiation (0030)** — now a prerequisite for federation, not a sibling.
2. **Push, done right (0017)** — pull + out-of-band wake; A2A's webhook security baked in;
   *not* blocking.
3. **Acknowledgement-required messages** — small, high-value, fits the model today.
4. **FTS5 search** — small, no new dependency.
5. **Federation (0024/0025)** — `name@hub`, signed POST to inboxes, peering-by-consent,
   store-and-forward with retries; the device-token/`@local` seams are already in place.
