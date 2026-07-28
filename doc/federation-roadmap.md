# Federation, in baby steps

Owner's direction, 2026-07-28, after a 53-requirement specification failed to converge
across two review rounds. This file supersedes those specs **as the plan**; they remain on
their branches as reference for individual steps, and should be read one section at a time
rather than as a whole.

## The rule

**One function pair per step.** Each step adds one thing a hub emits and one thing a hub
consumes, so every step is demonstrable on its own and can be shown working before the next
begins. A step that cannot be demonstrated is too big.

## The steps

### Step 1 — all the settings in the UI

A Settings tab with sections. Federation is the first section, holding the hub's own
identity: `name`, `title`, `description`. No federation behaviour at all.

*Status: in flight.* This is `a-hub-has-a-name-of-its-own-01KYMD90` WP04. Storage,
precedence and the API beneath it are built and green.

### Step 2 — passive identity

A hub can be **looked at** by another hub. It answers questions about itself and nothing
else. Nothing is fetched, nothing is sent, nothing is trusted.

- `/.well-known/agent-inbox` — a descriptor: software, version, base URL, title,
  description, and what it supports.
- WebFinger — `@alice@hub.example` resolves to an actor document.
- Actor documents reachable by a peer, which today they are not: `GET /actors/{name}` sits
  behind `guard_enforce`.

The demo: point a browser or `curl` at a second hub and read who lives there.

### Step 3 — active identity

The same functions, in the other direction: this hub can **ask another hub** who it is.

- Fetch a peer's descriptor and show it to the operator.
- Resolve a handle on a remote hub.
- Report `Ready` / `Warning` / `Failed`, with the reason.

The demo: type another hub's URL into the Settings tab and see it identified.

### Steps 4, 5, 6 … — one function pair at a time

Candidates, roughly in dependency order. Each is a step, not a phase:

- **Keys.** Publish a public key; verify a signature on something already arriving.
- **A single inbound message.** Accept one `Create`/`Note` from one configured peer.
- **A single outbound message.** Send one, to one peer, synchronously.
- **The queue.** Make sending asynchronous, with retry.
- **Policy.** Modes and a blocklist, once there is traffic for them to govern.
- **Visibility.** `local` / `normal` / `discoverable`, once there is discovery to limit.

## What this replaces, and why

`manual-activitypub-federation-v1-01KYJY10` reached 53 functional requirements and 14 work
packages. Two independent review rounds each found requirements mapped to a work package but
not deliverable from its subtasks. The failure was size: a coverage metric counted mapped
rows and called it delivery, and at that scale nobody noticed.

The specs are not wrong and not wasted — they are the best available description of the
destination, and each step above can lift its requirements from them. What they could not do
is be *implemented*, because nothing that large converges.

Two findings from those rounds are worth carrying into whichever step reaches them:

- **Outbound authorization must be re-derived at send time**, never carried from queue time.
  A peer that can stall a retry can otherwise make a hub send after federation is disabled,
  or send as an actor that has since gone `local`. This lands with the queue.
- **An effective value from the environment must never be written back as a stored value.**
  Already fixed in hub identity as FR-011; the same shape will recur wherever a client
  renders a resolved value and submits it.
