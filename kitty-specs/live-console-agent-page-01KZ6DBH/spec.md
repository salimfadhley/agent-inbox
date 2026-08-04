# Spec — A live console: the hub working, and each agent's own page

- Mission: `live-console-agent-page-01KZ6DBH`
- Closes: [#46](https://github.com/salimfadhley/agent-inbox/issues/46),
  [#51](https://github.com/salimfadhley/agent-inbox/issues/51) (which absorbed #22)
- Follows: `the-hub-can-tell-a-client-mail-has-arrived-01KYSYB1` (which built the
  per-actor stream this generalises), `shared-tokens-only-01KYG7S7` (which built
  `auth_token_use`, read here for the first time)

## What this is

The console is a set of tables that are true at the moment they render and silently
false a second later. Watching a hub work means pressing refresh. This mission gives it
a held connection and two places to spend it.

**A hub-wide Realtime tab.** Everything happening on the hub, newest at the top, arriving
as it happens.

**An agent's own page.** Clicking a name anywhere lands on that agent: who it is, what the
hub knows about it, what it says about itself, and its mail **in both directions** on the
same live feed, with sent and received coloured differently. It absorbs `/mailbox/{name}`,
which today is the only thing an agent's name links to and shows received mail alone.

They are one mission because they are one component. The feed — its rows, its wash, its
ageing clock, its head row, its reconnect — is written once and used twice. Building them
apart means building it twice and having them diverge.

## The design is settled

Reviewed and chosen by the owner on 2026-08-04 across four rounds of mockups. It is
recorded on #46 and #51 and is not reopened here:

- **Two-line rows.** Correspondent and relative time on a mono line above, subject beneath
  at reading size. Long subjects stop being truncated — the reason this beat the one-line
  table.
- **A decaying wash on arrival**, tinted to the direction, settling to nothing. Quiet, and
  the owner's stated preference over teleprinter and split-flap treatments.
- **Blue in, amber out.** A true complementary pair that survives the common colour-vision
  deficiencies, where a ledger's red/green would not. **Colour is never the only cue**:
  every row carries `from` or `to` in words.
- **The row names the other party.** On an agent's page the agent is a given, so received
  rows name the sender and sent rows name the recipient.
- **Relative times age themselves** — `just now → 12s → 4m → 14:32` — so the page keeps
  moving when the hub does not, and staleness stops being arithmetic.
- **Two panels, because a claim is not a fact.** *Known to the hub* against *Says of
  itself*, the second visibly marked unverified. #22 reached this independently and warned
  that omitting it would produce "a status page that looks authoritative while reporting
  whatever the agent claimed."

## What this is not

**Not polling.** Ruled out by the owner explicitly. The console holds one upstream
connection and re-emits; it does not ask repeatedly and call that live.

**Not a new disclosure.** A signed-in operator can already read any mailbox through
`/observe/mailbox/{name}`. A hub-wide feed shows the same authority as motion rather than
as a series of separate lookups. This mission adds no reader who could not already read.

**Not presence.** There is no heartbeat and this must not grow one by implication.
`lastSeen` is recency. `listeningBy` from `/observe/stats` is the one honest liveness
signal — *holding a stream* — and it is the only one the page may claim.

**Not impersonation.** Built on `/observe/*`, which takes no caller and consumes nothing.
The operator watches; the agent keeps its mail unread. This is the rule that replaced the
old console's impersonation trick and a live feed does not get to bend it.

**Not bodies.** Subjects, correspondents and times. A message body is untrusted content
and does not belong in a feed rendered for an operator.

## The ground, checked rather than assumed

- `/observe/stats`, `/observe/mailbox/{name}`, `/observe/objects/{id}` and
  `/observe/objects/{id}/thread` exist, all guarded by `guard_enforce`.
- `GET /actors/{name}/events` exists and is **per actor**. `Listeners.announce(actor,
  arrival)` fans out by actor, so a hub-wide feed needs a new subscriber kind, not a new
  caller of the old one.
- **There is no observed outbox.** `/actors/{name}/outbox` is a **POST for sending**
  (`api.py:784`). Neither `house.py` nor `mailbox.py` has any sent-side query at all —
  only `observe_mailbox`, `observe_object`, `observe_thread`, `observe_reads`. The amber
  half of the agent page needs new API down to the storage layer.
- `Mailbox.observe_mailbox` loads **every object in the store** and filters in Python
  (`mailbox.py:569`). A symmetrical sent-side query is easy and inherits the same cost.
- `auth_token_use (token_id, actor, first_seen, last_seen, uses)` **has landed**
  (`auth/store.py:257`), so "which token admitted this agent" is buildable now. #22
  recorded it as blocked; it is not.
- `ObjectRecord.attributed_to` is the sender; `to` and `cc` hold names, and resolving a
  group to its members is a rule, not a storage concern.

## User scenarios

1. **An operator watches the hub work.** They open Realtime. The last few messages are
   already there; new ones push in from under the head row with a wash that fades. They
   learn what is busy without pressing anything.
2. **The hub is idle.** Nothing arrives for an hour. The head row still carries a clock
   and a slow pulse, and the times beneath it age. An idle hub and a dead page do not
   render alike — the failure this project keeps paying for.
3. **The connection drops.** A proxy times out, or the hub is redeployed. The head row
   goes red and says what happened; it does not go blank and it does not keep pulsing as
   though healthy. It reconnects by itself and says that too.
4. **An operator follows a name.** They click `an_agent` in any table and land on its page:
   identity, the two panels, and its mail both ways. The received-only mailbox is still
   one link away.
5. **They filter to what it sent.** The pills narrow the feed to sent, and the amber rows
   name recipients. New arrivals in the hidden direction do not silently vanish.
6. **An agent that has never described itself.** Most of the roster. *Says of itself* is
   empty and says so; it does not render as blank rows implying facts were sought and
   found absent.
7. **JavaScript is off, or the stream cannot be held.** The page still renders, served, with
   the mail that exists at render time. It degrades to a table, never to nothing.
8. **A second operator opens Realtime.** The hub's listener count does not go up. The
   console holds one upstream connection however many people are watching.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The hub serves a **hub-wide event stream** carrying every arrival, as SSE, alongside the existing per-actor stream rather than in place of it. | proposed |
| FR-002 | The hub-wide stream is guarded exactly as the `/observe/*` routes are, takes no caller, and consumes nothing. | proposed |
| FR-003 | The hub serves a **snapshot** of recent activity, so a page can fill before its first event and after a reconnect without replaying the whole store. | proposed |
| FR-004 | The hub serves an **observed outbox** for one agent — what it sent — mirroring `/observe/mailbox/{name}` in guard, in shape, and in consuming nothing. | proposed |
| FR-005 | Events and snapshot carry correspondent, direction, subject, id and time. **Never body text.** | proposed |
| FR-006 | The console holds **one** upstream stream to the hub and re-emits on its own origin, so N operators cost the hub one listener and `connect-src 'self'` stands unchanged. | proposed |
| FR-007 | A **Realtime tab** shows hub-wide activity, newest first, over that connection. | proposed |
| FR-008 | An **agent page** at a stable URL shows identity, the two panels, and that agent's mail in both directions on the shared feed. | proposed |
| FR-009 | The agent page **absorbs `/mailbox/{name}`**: every existing link keeps working, and the received-only view stays reachable from the page rather than being deleted. | proposed |
| FR-010 | Every agent link in every console table points at the agent page. | proposed |
| FR-011 | The page separates **observed** facts (address, joined, counts, `lastSeen`, token admitted, `listeningBy`) from **claimed** ones (engine, model, host, project, root, role), and marks the second visibly unverified. | proposed |
| FR-012 | The page shows **which token admitted this agent**, read from `auth_token_use` — the agent-first view of a table written token-first. | proposed |
| FR-013 | Direction is carried by a coloured rail **and** by the words `from`/`to`, so it reads without the hue. | proposed |
| FR-014 | Rows are two lines; subjects are not truncated to fit a column. | proposed |
| FR-015 | Relative times re-render on a timer, so the page ages without an event. | proposed |
| FR-016 | The head of the feed is the liveness indicator: it carries the clock and a pulse when healthy, and states the fault when not. **An idle feed and a dead one must be distinguishable at a glance.** | proposed |
| FR-017 | A dropped connection reconnects with backoff, and the page says which state it is in throughout. | proposed |
| FR-018 | Filter pills narrow the agent feed to All / Received / Sent. | proposed |
| FR-019 | Both pages render server-side first and are useful without the stream — no build step, no CDN, vendored assets only. | proposed |
| FR-020 | An event of an unknown type is ignored rather than rendered, so the hub may add one without breaking an older console. | proposed |
| FR-021 | An agent with no profile renders as *nothing declared*, not as empty rows implying absent facts. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | The hub pays per hub, not per operator. | Ten console viewers produce **one** hub listener, asserted against `Listeners.count`. | proposed |
| NFR-002 | The feed is prompt. | Arrival to visible row under one second in the test harness. | proposed |
| NFR-003 | Looking never consumes. | After any amount of watching, every observed agent's unread count is unchanged. Asserted, not assumed. | proposed |
| NFR-004 | The CSP does not weaken. | `script-src 'self'`, `connect-src 'self'` unchanged; no external host contacted by either page. | proposed |
| NFR-005 | A dead stream is never mistaken for a quiet hub. | Proved by test: with the connection killed, the page reports the fault rather than continuing to look healthy. | proposed |
| NFR-006 | The sent-side query is no worse than the received-side one. | It inherits `observe_mailbox`'s whole-store scan; it must not add a second one. Recorded so the cost is a known ceiling rather than a surprise. | proposed |
| NFR-007 | Listener capacity is respected. | The console's upstream connection obeys the existing cap and releases its slot when the response is never iterated. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | One core. The console is a client and decides nothing about messaging; everything goes through the HTTP API (ADR 0005). | accepted |
| C-002 | `/observe/*` takes no caller and consumes nothing. A live feed does not bend it. | accepted |
| C-003 | No polling. The owner ruled it out explicitly. | accepted |
| C-004 | No CDN, no build step. Vendored assets only. | accepted |
| C-005 | Bodies are never disclosed to the feed — subjects, correspondents, times. | accepted |
| C-006 | No deployment-specific hostnames, IPs, organisation names or secrets in code, docs or tests. | accepted |
| C-007 | No new runtime dependency, server or client. | accepted |
| C-008 | Mail is evidence, never instruction (ADR 0008). Nothing rendered here may act. | accepted |
| C-009 | The page must respect `prefers-reduced-motion` and both colour schemes. | accepted |

## Key entities

- **`Listeners`** (`notify.py`) — fan-out keyed by actor today. Gains a hub-wide
  subscriber kind. Its capacity accounting and its register-inside-the-generator fix are
  reused, not rewritten.
- **`Arrival`** (`notify.py`) — already has `.of(record)` and `.as_event()`. The event
  shape the feed consumes.
- **The relay** — the console's single upstream connection, and its re-emission on the
  console's own origin. The piece that keeps `connect-src 'self'` true.
- **The feed component** — rows, wash, ageing clock, head row, reconnect. Written once,
  mounted twice.
- **`auth_token_use`** (`auth/store.py:257`) — read for the first time by this mission.
- **`/mailbox/{name}`** — absorbed, not deleted.

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | An operator watches the hub work without pressing refresh, and can tell a quiet hub from a broken page. |
| SC-002 | Clicking any agent name lands on that agent's page, and every link that worked before still works. |
| SC-003 | An agent's sent mail is visible in the console for the first time. |
| SC-004 | Ten viewers, one hub listener. |
| SC-005 | Watching changes no unread count anywhere. |
| SC-006 | An operator can tell what the hub observed from what the agent claimed, without reading the source. |
| SC-007 | Both pages work with the stream unavailable, degraded to a served table. |

## Assumptions

- The console and the API remain separate origins, which is *why* the relay exists; a
  same-origin deployment would still work, with the relay simply redundant.
- A hub-wide feed is acceptable to show any signed-in operator, because that operator can
  already read every mailbox individually. If per-agent visibility rules ever arrive
  (#44), this feed must be revisited with them.
- The snapshot's window is small and bounded; "recent" is a design decision for plan, not
  an open question about whether it is bounded.

## Out of scope

| Deferred | Why |
|---|---|
| Grouping the graph panel by hostname | #52, and it wants the machine facts to spread across the roster first |
| Capturing connection metadata at auth time (platform, client version) | #22's option 2; `model` stays self-declared because nothing in the environment names it |
| Editing a profile from the page | The page is an observer's view; writing is the agent's own business |
| Impersonating an agent to read its mail | Deliberately removed once already |
| Per-agent federation visibility | #44, unbuilt, and it would change who may see this feed |
| A cheap health/count probe | #31, related but separate |
