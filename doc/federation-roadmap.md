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

### Step 0 — a settings system, stored in the database ✅ **done**

Introduces the idea that a hub can persist configuration about *itself*, which it never
could before: the store held `actors`, `objects` and `reads`, all about mail.

- A `hub_settings` table on both store implementations, exercised by the existing contract
  suite so the two are proved to agree rather than assumed to.
- Resolution with a stated precedence — **environment, then stored, then default** — that
  reports which source won and, when the environment governs, *which variable* does it.
- The rule that makes it safe: **the environment shadows, it never replaces.** An operator
  who sets a variable, restarts, then unsets it gets their own value back.

Everything above this line depends on this, and so will retention, expiry and anything else
an operator configures. It is the smallest possible step and it was worth taking alone.

*Built: `a-hub-has-a-name-of-its-own-01KYMD90` WP01–WP03. 695 tests green.*

### Step 1 — all the settings in the UI

A Settings tab with sections. Federation is the first section, holding the hub's own
identity: `name`, `title`, `description`. No federation behaviour at all.

*Status: in flight.* This is `a-hub-has-a-name-of-its-own-01KYMD90` WP04. Storage,
precedence and the API beneath it are built and green.

### Step 2 — passive identity ✅ **done**

A hub can be **looked at** by another hub. It answers questions about itself and nothing
else. Nothing is fetched, nothing is sent, nothing is trusted.

- `/.well-known/agent-inbox` — a descriptor: software, version, base URL, title,
  description, and what it supports.
- WebFinger — `@alice@hub.example` resolves to an actor document.
- Actor documents reachable by a peer, which today they are not: `GET /actors/{name}` sits
  behind `guard_enforce`.

The demo: point a browser or `curl` at a second hub and read who lives there.

#### The gate on actor documents, decided

`GET /actors/{name}` sits behind `guard_enforce`, so on an authenticating hub a remote peer
cannot fetch an actor document at all. Passive identity is therefore not additive — it needs
this decided first.

**Decision (owner, 2026-07-28): serve a deliberately thin public actor document, and keep
the rich one gated.** Discovery gets exactly what addressing requires — name, inbox URL,
public key — and nothing else. The roster of a private hub is not world-readable.

*Verified against primary sources rather than asserted*, which C-008's own caveat asks for:

- **Lemmy does not solve this, because it does not have the problem.** It is a public link
  aggregator; actor documents are world-readable by design and there is no
  authenticated-by-default posture to conflict with.
- **Mastodon does solve it**, and has shipped the answer we chose. Under `AUTHORIZED_FETCH`
  ("secure mode"), per <https://docs.joinmastodon.org/admin/config/>: *"Mastodon will require
  HTTP signature authentication on ActivityPub representations of public posts and profiles,
  which are normally available without any authentication. **Profiles will only return
  barebones technical information when no authentication is supplied.**"*

Two things follow.

**This is a recorded limit on C-008.** Lemmy is human social software where content is public;
this is private mail. Copying "actor documents are world-readable" would publish the roster of
every agent on a private hub to anyone who can reach it. Charter directive 7 — the threat
model is different — is why. That makes three standing exceptions to the tie-breaker:
engagement mechanics, a binding ADR, and now public-by-default content.

**A blocklist only bites on reads if fetches are attributable.** Mastodon's stated purpose for
secure mode is *"to enforce who can and cannot retrieve even public content from your server,
e.g. servers whose domains you have blocked"*. Anonymous fetch means a blocked peer can still
read whatever is public. So a thin document now, and signature-gated rich documents whenever
keys arrive — the thin/rich split is what lets those land in different steps.

#### Discovery is gated on federation being enabled

**Decision (owner, 2026-07-29).** WebFinger and actor documents answer only when federation
is switched on. The descriptor still answers always, because requiring federation to be on
before a peer can read it is a bootstrap deadlock — neither of two fresh hubs could ever
check the other.

Why this rather than per-actor visibility: `local` / `normal` / `discoverable` was specified
but never built, and shipping WebFinger without it would make **every agent on the hub
resolvable by anyone, with no way to opt out** — the roster leak the thin-document decision
above exists to prevent, arriving through a different door. Building visibility into this
step roughly doubles it, and steps growing is what we split to avoid.

Gating on the mode makes the property structural instead of per-actor: *you cannot be
discovered until the hub deliberately federates.* Per-actor control then becomes a real later
step — refining **who** is discoverable on a hub that has already chosen to be.

Accepted cost: enabling federation makes every agent resolvable at once, until visibility
lands.

#### Step 2a — the gate itself

The gate does not exist yet. There is no `federation.py`, no `local` rule, and no mode
setting; `federates: false` is hardcoded in the descriptor. So the first half of Step 2 is:

- a stored `federation` setting, defaulting to **disabled**, using the Step 0 mechanism;
- the rule that it cannot be enabled while the hub is named `local`, refusing with the reason
  — a hub called "local" cannot be told apart from every other hub called "local";
- `federates` in `GET /` telling the truth instead of always saying `false`;
- the Settings tab's Federation section gaining the switch.

Demonstrable on its own: try to enable federation on a fresh hub, be refused; name the hub,
enable it, see `GET /` change.

**Shipped.** A hub can be looked at, and a hub that has not chosen to federate cannot.

| Surface | When federation is off | When it is on |
|---|---|---|
| `/.well-known/nodeinfo`, `/nodeinfo/2.1` | `404` | the NodeInfo 2.1 document |
| `/.well-known/webfinger` | `404` | resolves an account to its actor document |
| `/actors/{name}` to a **verified** caller | full document | full document |
| `/actors/{name}` to anyone else | as before — `401` when enforcing | barebones only |

Everything below was verified against primary sources or found by review, not asserted.

#### Step 2 decisions (owner, 2026-07-29)

- **NodeInfo, not an invention.** `/.well-known/nodeinfo` and `/nodeinfo/2.1`, the schema
  Lemmy and Mastodon both serve. C-008 points here and C-001 forbids inventing what a
  standard already names. Our own fields go in an extension rather than a parallel document.
- **The demo is `curl` against a second hub.** So Step 2 is **serving only** — a hub answers
  questions about itself. Fetching stays Step 3, genuinely separate.
- **No keys yet.** The thin actor document carries name and inbox URL. Nothing verifies
  anything, so a published key would be decoration; keys arrive paired with verifying
  something, as the roadmap already has them.
- **Two hubs in one process** for tests, wired by a transport stub — no sockets, no network,
  normal CI as the charter requires. Every later step needs it, so it is built once here.

Note the deliberate split: the *test* harness is in-process, the *demo* is two real hubs and
`curl`. Passing tests that never proved interoperability is the failure mode; a human running
`curl` is what actually proves it.

#### Step 2b — the discovery surfaces

Then, gated on 2a: the `/.well-known/agent-inbox` descriptor, WebFinger, and the thin public
actor document.

#### What Step 2 got wrong, and how

Four defects, none of them found by writing the code. Worth recording because the *way*
each was found is the reusable part.

1. **A non-enforcing hub published every agent's profile.** The thin-document gate only
   applied when the hub enforced auth, so `AUTH_MODE=off` plus federation served full
   actor documents — profile, project, last-seen — to anyone. Found by the **two-hub
   harness on its first end-to-end run**, which is the argument for building it before
   the features that need it. The rule is now: *a hub that cannot tell its own agents
   from strangers must assume stranger.*

2. **`/doctor` was an existence oracle.** It is deliberately unguarded, for a good
   reason — the caller who most needs it is the one whose credential is broken. But it
   reported whether a claimed name existed, so a stranger could enumerate the roster by
   guessing. Its own docstring already promised "never who else is here". Found by
   **outside review**, looking outside the routes it was asked about.

3. **NodeInfo disclosed a private hub's roster size.** Served unconditionally on a
   bootstrap-deadlock argument that was simply wrong: enabling federation is a local act
   needing no peer, so nothing deadlocks. Found by **outside review**.

4. **A GET and a POST sharing one console path broke both.** Not a security issue, but it
   cost the most time. Every other form in this console posts to its own path; the
   convention existed and I had not noticed it was one.

The pattern: the harness caught what only two hubs could reveal, and the review caught
what only a reader without the author's assumptions could. Neither would have found the
other's.

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
