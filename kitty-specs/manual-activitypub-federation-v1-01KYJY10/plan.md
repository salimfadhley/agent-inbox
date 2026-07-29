# Implementation Plan: Manual ActivityPub Federation V1

**Branch**: `kitty/mission-manual-activitypub-federation-v1-01KYJY10` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `kitty-specs/manual-activitypub-federation-v1-01KYJY10/spec.md`

## Summary

Let two `agent-inbox` hubs exchange addressed mail over a narrow ActivityPub profile,
manually and opt-in, without turning the mailbox into a social network.

The work divides along one seam that matters more than any other: **policy is decided in
one place, and every path asks it.** Inbound and outbound are otherwise independent, and
almost everything else is a leaf.

## Technical Context

**Language/Version**: Python 3.12+ (CI matrix covers 3.12 and 3.13)

**Primary Dependencies**: `litestar` for the routes, `aiosqlite` for storage, `cryptography`
(already a dependency, used by auth) for signing keys and RFC 9421 signatures, `msgspec` for
the wire shapes.

**New dependency required — an async HTTP client.** The project has none. `client.py` and
`release_gate.py` use stdlib `urllib.request`, which is synchronous and has no connection
pooling, no per-host concurrency control, and no timeout granularity worth the name.
Outbound federation needs all three: per-peer concurrency of 1 (spec table), a 9s inbound
processing budget, bounded fetches, and retries that do not block the sender.

`httpx` is the candidate. It is already present in the environment transitively, it is
mature and widely deployed, and it is what a Python project would reach for. **This is the
first new runtime dependency in some time and the owner should nod at it before work
starts** — the charter asks for "mature pinned dependencies" and treats tooling changes as
needing permission. The alternative — driving `urllib.request` on a thread pool — avoids the
dependency and costs a hand-rolled concurrency limiter, which is the kind of thing C-008
says to stop doing.

**Storage**: the existing SQLite file. Federation adds tables for peers, blocklist entries,
the outbound delivery queue, seen inbound activity ids, and audit entries. No new mount;
the volume the mail lives on is already there. This follows
`a-hub-has-a-name-of-its-own-01KYMD90`, which established that hub-level state lives beside
the mail.

**Testing**: pytest against both stores via the existing contract suite; Litestar
`TestClient` for routes. Federation is two hubs talking, so the interesting tests are **two
apps in one process**, wired to each other by a transport stub — no network, no external
services, in normal CI, exactly as the charter requires. That harness is worth building
first, because every delivery requirement depends on it.

**Target Platform**: the hub container; the console section reads through the API.

**Project Type**: single

**Performance Goals**: no latency targets. The spec's limits are *bounds*, not budgets: 1
concurrent send per peer, 9s inbound processing, 100 fetches per resolution, 50-item pages.
They exist to stop a remote server costing us unbounded work.

**Constraints**: federation is off by default and cannot be enabled while the hub is named
`local`; `@local` never egresses; mail is data and never instruction; all messaging logic
stays server-side in one core (ADR 0005); administration is out of band (ADR 0008);
environment wins over stored configuration for scalars, and lists are stored-only (FR-049).

**Scale/Scope**: 52 functional requirements, 7 non-functional, 8 constraints, 12 success
criteria. This is the largest mission in the project by some distance and will produce
substantially more work packages than any predecessor.

## Charter Check

| Rule | Status |
|---|---|
| Generic only — no deployment hostnames, IPs, secrets or org names | **pass** — peers are configuration; the spec's examples are `example` domains |
| One core — no messaging logic outside the core, no client deciding | **pass** — federation widens `local_name()` (FR-047) and delivers through `house`; the console calls the API |
| No actor has authority (ADR 0008) | **pass, and load-bearing** — remote mail is the strongest form of "arriving content", and NFR-004 with FR-040 require it be framed as untrusted data. Peer and mode changes are operator-only |
| Identity is a surrogate key (ADR 0003) | **pass** — remote identity is stored as the actor URI (FR-021), never the typed handle or display name |
| Built for LLMs first (directive 7) | **pass** — FR-033 rejects follows, likes, announces, votes and boosts before delivery. No engagement mechanics arrive with the protocol |
| Settle a foundation before building on it (directive 3) | **⚠ see Complexity Tracking** |
| Regression tests from shipped bugfixes are requirements | **carry** — thread disclosure (0020) and per-turn visibility must be re-asserted across a federation boundary, not only locally |

## Complexity Tracking

| Violation | Why it is taken | Why the simpler path is insufficient |
|---|---|---|
| **Directive 3: the foundation is not in code.** `a-hub-has-a-name-of-its-own-01KYMD90` supplies `name`, the settings storage, the precedence rule, the Settings section and the `local` gate this mission wires. It is specified, planned, tasked and analysis-`ready`, with WP01 partially implemented (`hub_settings` on both stores). Planning federation against it is defensible; **implementing federation before it lands is not**. | Planning now is cheap and surfaces exactly this kind of ordering problem early. The mitigation is a hard sequencing rule, below, not a redesign. |
| **A new runtime dependency.** See Technical Context. | Hand-rolling per-host concurrency, pooling and retry against `urllib.request` is more code, less tested, in the part of the system most exposed to a hostile remote. |
| **[#21](https://github.com/salimfadhley/agent-inbox/issues/21) will re-org the console.** The operator wants a Settings tab with Federation as a *section*, and has chosen to do it after #15. | This mission's console work must target a *section*, not a tab, and should land after #21 or be trivially re-parentable. Recorded so it is not discovered during implementation. |

**Sequencing rule.** No federation work package may start until
`a-hub-has-a-name-of-its-own-01KYMD90` is implemented and merged. Planning artefacts may be
completed now.

## Project Structure

### Documentation (this mission)

```
kitty-specs/manual-activitypub-federation-v1-01KYJY10/
├── spec.md              # requirements; five clarifications recorded
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── contracts/           # Phase 1 — wire shapes
└── tasks/               # work packages
```

### Source Code (repository root)

```
src/agent_inbox/
├── federation.py            # EXISTS — the `local` rule; grows the mode gate
├── federation/              # NEW package, if federation.py outgrows one module
│   ├── policy.py            # the one place a decision is made
│   ├── peers.py             # peer records, add flow, compatibility check
│   ├── keys.py              # signing keypair, public key metadata
│   ├── signatures.py        # RFC 9421 sign and verify
│   ├── webfinger.py         # resolve `@alice@example.com`
│   ├── outbound.py          # resolution, queue, delivery, retry
│   └── inbound.py           # verify, gate, dedupe, deliver
├── addressing.py            # MODIFIED — `local_name()` widens (FR-047)
├── api.py                   # MODIFIED — inbox 501→403, descriptor, WebFinger, actor docs
├── console.py               # MODIFIED — the Federation section
├── sqlite_store.py          # MODIFIED — federation tables
├── store.py                 # MODIFIED — the same, in memory
└── exceptions.py            # MODIFIED — refusal reasons that name the rule

tests/
├── test_federation_policy.py    # NEW — the decision table, exhaustively
├── test_federation_wire.py      # NEW — two hubs in one process
├── test_federation_inbound.py   # NEW — every rejection path
├── test_federation_outbound.py  # NEW — queue, retry, suppression
└── test_addressing.py           # MODIFIED — @local still never egresses
```

**Structure Decision**: start in the existing `federation.py`; split to a package the moment
it holds more than policy plus one collaborator. Do not create the package up front — an
empty seven-module skeleton is a guess about shape, and this mission has enough real
unknowns without inventing structural ones.

## Implementation Concern Map

### IC-01 — The policy decision, in one place

- **Purpose**: one function answering "may this exchange happen" — mode, blocklist, peer
  state, scheme, actor visibility — consulted by every inbound and outbound path.
- **Requirements**: FR-004–FR-008, FR-012, FR-025–FR-027, FR-053, C-007
- **Surfaces**: `federation/policy.py`, `test_federation_policy.py`
- **Depends on**: nothing
- **Risks**: the highest-value target in the mission. If policy is evaluated in two places
  they will disagree, and the disagreement will be a disclosure. The blocklist overriding
  every mode is not a special case to remember at each call site — it belongs inside the one
  function.

### IC-02 — Federation storage

- **Purpose**: peers, blocklist, outbound queue, seen activity ids, audit entries.
- **Requirements**: FR-037, FR-042, FR-043–FR-045, FR-049
- **Surfaces**: `sqlite_store.py`, `store.py`, `test_store_contract.py`
- **Depends on**: `a-hub-has-a-name-of-its-own` WP01
- **Risks**: additive only, against live mail. Seen-activity-ids grows without bound unless
  it expires — and it must outlive the retry window of any sender, or duplicates return.

### IC-03 — Keys and signatures

- **Purpose**: a signing keypair, public key metadata in actor documents, RFC 9421 sign and
  verify.
- **Requirements**: FR-039, FR-017
- **Surfaces**: `federation/keys.py`, `federation/signatures.py`
- **Depends on**: IC-02
- **Risks**: the one place a mistake is silent and total. A verifier that accepts an unsigned
  request, or verifies the wrong bytes, passes every test that does not attack it. Tests must
  include a **tampered** request, a **replayed** one, and one signed by the wrong key — not
  merely a valid one and a garbage one.

### IC-04 — Discovery: descriptor, WebFinger, actor documents

- **Purpose**: what a peer reads about us before and during exchange.
- **Requirements**: FR-016, FR-017, FR-052, FR-018–FR-022, FR-029, FR-030, FR-048
- **Surfaces**: `api.py`, `federation/webfinger.py`
- **Depends on**: IC-01, IC-03
- **Risks**: unauthenticated by decision (`01KYMQC8Z4CKN86Y3R79T06BCB`), so FR-030's
  exclusions are a **security boundary**, not a tidiness rule. FR-048 forbids the hub `name`
  appearing here. A `local` actor must not resolve through WebFinger — the same disclosure
  class as mission 0020, one hop further out.

### IC-05 — Outbound: resolve, queue, deliver, retry

- **Purpose**: local send succeeds on persistence; delivery happens behind it.
- **Requirements**: FR-031, FR-032, FR-034, FR-038, delivery semantics
- **Surfaces**: `federation/outbound.py`, `addressing.py`
- **Depends on**: IC-01, IC-03, IC-04
- **Risks**: **the whole authorization must be re-derived at send time** (FR-050), not
  merely the peer. The outside review on 2026-07-28 corrected this concern's original
  framing: the blocked-peer case it named is *already covered* by FR-008, and the real holes
  are mode and actor visibility — neither of which is a property of the target, so a queue
  keyed by peer never notices them change. A stalled retry plus `mode=disabled` egresses
  after federation is off; a stalled retry plus an actor narrowing to `local` egresses as an
  actor forbidden to send. Implement one re-evaluation of everything, rather than a
  cancellation path per property; the per-property approach is what left two of three
  uncovered on paper.

### IC-06 — Inbound: verify, gate, dedupe, deliver

- **Purpose**: accept only what policy allows, exactly once, into the normal inbox flow.
- **Requirements**: FR-033, FR-035, FR-036, FR-037, FR-040, NFR-003, NFR-004
- **Surfaces**: `federation/inbound.py`, `api.py`
- **Depends on**: IC-01, IC-03
- **Risks**: every check must run **before** delivery. "Reject before delivery" is untestable
  unless a rejected message provably never reached a mailbox — so assert on the recipient's
  inbox, not on the response code.

### IC-07 — The switch, and the honest status code

- **Purpose**: turn federation on; make the inbox route mean what it says.
- **Requirements**: FR-013, FR-046, NFR-001
- **Surfaces**: `federation.py`, `api.py`
- **Depends on**: IC-01
- **Risks**: `check_may_enable_federation()` already exists with a test that fails if the
  rule is removed. **Wire the switch to it; do not reimplement the check.** The `501`→`403`
  change is a behaviour change for anyone who probed the old route.

### IC-08 — The console section

- **Purpose**: peers, modes, blocklist, warnings, delivery state, health.
- **Requirements**: FR-001, FR-006, FR-010, FR-011, FR-038, NFR-005, NFR-006
- **Surfaces**: `console.py`
- **Depends on**: everything above; and see Complexity Tracking on #21
- **Risks**: the warnings are requirements with near-exact text, including FR-011's stronger
  warning for HTTP-in-open. A warning the operator can skip is not a warning — NFR-005
  requires acknowledgement before activation, and the acknowledgement is audited.

### IC-09 — Actor visibility

- **Purpose**: `local` / `normal` / `discoverable`, set by the actor itself.
- **Requirements**: FR-023, FR-024, FR-028, FR-053
- **Surfaces**: profile handling, `federation/policy.py`
- **Depends on**: IC-01
- **Risks**: it is a *ceiling on exposure*, never a grant (FR-053). An implementation that
  treats `discoverable` as permission rather than consent inverts the policy.

### IC-10 — The words follow the code

- **Purpose**: prompt, README, error text and `doctor` stop describing a hub that cannot
  federate.
- **Requirements**: NFR-003, NFR-004, charter directive 2
- **Surfaces**: `prompts.py`, `README.md`, `doc/`, `exceptions.py`
- **Depends on**: everything
- **Risks**: `addressing.py`'s module docstring, `exceptions.py`'s `RemoteMailbox` and the
  prompt all currently assert *"this mailbox does not federate yet"*. Each becomes false the
  day this ships, and the prompt has twice been caught asserting something untrue.
