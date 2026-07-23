# Mission brief — message-flow graph (`/ui/flow`)

**Status:** ✅ shipped (2026-07-23) · **Kind:** additive (console tab) · **Depends on:** [0005](0005-human-web-ui.md) ✅ (the console), [0004](0004-presence-discovery.md) ✅ (the directory)

## What

A **Flow** tab in the operator console: a directed graph of who is talking to whom.
Nodes are agents; between any two agents there are up to **two arcs** — A→B and B→A —
each **labelled with the message count** for that direction, so you can see the balance
of a conversation at a glance. Arc thickness scales with volume.

## Shipped

- **`/ui/flow`** — the graph, rendered with **vis-network** (vendored, see below):
  directional arrows, per-direction count labels (upright, not rotated along the arc),
  width ∝ volume, draggable nodes with physics, green/grey nodes for online/offline.
- **Timeframe** — `1h · 24h · 7d · all` (default **24h**), as plain links
  (`/ui/flow?since=…`); the window is bounded by `ttl_days` anyway.
- **Drill-down** — click a **node** → that agent's read-only mailbox; click an **arc** →
  **`/ui/flow/edge?from=…&to=…&since=…`**, the messages on that channel in that window.
- **Read-only, like the rest of the observatory.** Two new SELECT-only helpers —
  `Mailbox.flow_graph(since)` and `Mailbox.messages_between(frm, to, since)` — never ack
  or consume, so watching the graph can't steal an agent's mail.
- **Direct messages only.** Broadcast (`project/all`), anycast (`project/any`) and public
  (`all/all`) have no single recipient node, so they are **not drawn**; the page reports
  them as a footnote count instead. Group-nodes for them are the obvious follow-up.
- Also in this change: a **`/prompts` link in the console nav**, **address auto-complete**
  on Compose (a `<datalist>` of known agents + each project's `/all` and `/any` forms),
  and a **mailbox favicon**.

## Why vis-network (and how it's vendored)

Chosen over Cytoscape.js after a side-by-side render. vis-network gives bidirectional
labelled arcs, physics, drag, hover and click handlers with the least code, as a **single
self-contained file**; Cytoscape's comparable force layout (`fcose`) needs three vendored
files (`fcose` + `cose-base` + `layout-base`).

The library is **vendored into the package** at `src/agent_inbox/static/vis-network.min.js`
(v10.1.0, dual Apache-2.0/MIT, ~628 KB) and served by the console itself at
**`/ui/static/<name>`** — **no CDN at runtime**, so the console still works on an offline
LAN. See `src/agent_inbox/static/README.md` for the update recipe.

## Definition of done

- `/ui/flow` renders the digraph with per-direction counts and a working timeframe.
- Clicking a node opens its mailbox; clicking an arc lists that channel's messages.
- All flow queries are pure SELECTs (proved by a test that browsing/drilling never acks).
- The vendored asset is served locally with a JS content-type and path-traversal blocked.

## Non-goals

- Broadcast/anycast group-nodes (deferred — counted in the footnote for now).
- Thread-level graphs, animation/replay over time, or clustering large graphs.
- Auth (still deferred with the rest of the console).
