# Spec — Federated identity and trust

> **Audited 2026-08-03 — NOT complete.** Most of this shipped, but requirements
> listed in **issue #44** have no implementation. Read that issue before assuming
> anything here is done.

- Mission: `federated-identity-and-trust-01KYN49V`
- Parent: [`manual-activitypub-federation-v1-01KYJY10`](../manual-activitypub-federation-v1-01KYJY10/spec.md),
  issue [#15](https://github.com/salimfadhley/agent-inbox/issues/15)
- Raised by: the operator, 2026-07-28
- Status: **shipped 2026-08-06.** All six work packages built, tested and released
  (v0.76.0 – v0.80.1). FR-020 was found **already satisfied** and closed with evidence
  rather than re-satisfied: neither `501` nor the superseded mission numbers appear in
  `api.py`, and the federation inbox already refuses with a reason.

## What this is

**Another hub can discover this one, verify what it is, and be told whether it may talk to
it. An operator decides who that is. No mail crosses.**

That is the whole mission. It is the first carved out of
`manual-activitypub-federation-v1`, and it is deliberately the half with no delivery in it:
the identity a peer reads, the policy that decides, and the CLI an operator uses to
configure both.

## Why this exists as its own mission

The parent spec reached 53 functional requirements and a 14-package breakdown, and **it did
not converge**. Two independent review rounds each found requirements mapped to a work
package but not deliverable from its subtasks — the second found six, three of which were
genuinely missing work rather than mis-filed.

The failure was not in any one artefact. It was size: a coverage metric counted mapped rows
and called it delivery, and at 53 requirements nobody — human or model — held enough of it
at once to notice. The operator's decision was to stop widening and lock down one capability
at a time.

**So the test for this spec is not "is it complete" but "can it converge."** If it cannot be
held in one head, it is still too big.

## What it delivers

An operator can:

- give the hub a federated identity and switch federation on, or find out why they cannot;
- add a peer and see a real compatibility check rather than a hopeful green tick;
- decide who may talk to this hub, and block anyone, in any mode;
- see which of those settings the deployment has fixed and which they control.

Another hub can:

- fetch a descriptor and learn what this software is and what it supports;
- resolve `@alice@hub.example` to an actor document, when that actor permits it;
- read the public key it will later need in order to verify anything we send.

Nothing sends. Nothing receives. The federation inbox refuses honestly and says why.

## Scope reductions taken, and why

Three cuts, recorded so a later reader sees they were chosen rather than forgotten.

### HTTPS only

The parent's FR-010 and FR-011 add experimental HTTP federation, with two warning texts, an
acknowledgement flow, a persistent insecure marker and audit around all of it. The parent
already calls it experimental.

That is a disproportionate share of the risk and the surface for a capability most hubs will
never use, and it is safer absent. **`https` is the only accepted scheme here.** Every other
scheme is refused, and the refusal names the rule.

### `allowlist` and `disabled` only — no `open` mode

`open` mode is where a hub accepts mail from strangers. It is the parent's FR-006 and it is
gated behind a strong warning for good reason. **A mission with no delivery has nothing to
open**, so it ships `disabled` and `allowlist`, and refuses `open` as not yet supported.

### The key is published; signing and verification are not built

A peer must be able to read our public key to plan on verifying us, so key generation and
publication belong here. **Nothing in this mission signs or verifies anything**, because
nothing sends or receives. Building a verifier with no traffic to verify would be a rule with
nothing behind it — the shape `AGENTS.md` warns about, and one the parent mission already
caught itself in once.

## Decisions inherited, not re-litigated

Settled during the parent mission and carried in unchanged.

| Decision | Effect here |
|---|---|
| The hub `name` never crosses the wire (`01KYMQ4GNS4B1PRD6WJ6W75DRG`) | It appears on no federated surface. Renaming stays free |
| Federated identity is the **domain**; DNS is the registry | No name registry is built. [#16](https://github.com/salimfadhley/agent-inbox/issues/16) stays deferred |
| Precedence applies to scalars; lists are stored-only (`01KYMQ6PTT9J16PCA5H8FF66QX`) | Peer lists and the blocklist have no environment equivalent |
| Actors set their own visibility (`01KYMQ8T23YB16YY7Y88EZPVVD`) | It is a profile field, not an administrative setting |
| The peer descriptor is unauthenticated and full (`01KYMQC8Z4CKN86Y3R79T06BCB`) | A prospective peer can compatibility-check us before either side commits |
| **When in doubt, do what Lemmy does** | The standing tie-breaker. Departures allowed; silent departures not |

## Functional requirements

Parent ids are given so traceability survives the split.

| ID | Requirement | Parent | Status |
|---|---|---|---|
| FR-001 | A fresh hub federates with nobody: mode `disabled`, no peers, no ingress, no egress, without operator action. | FR-002 | planned |
| FR-002 | Federation cannot be enabled unless the hub has a stable public URL **and** a `name` that is not `local`. The `local` rule already exists as `check_may_enable_federation()`; wire the switch to it rather than reimplementing it. | FR-013 | planned |
| FR-003 | Modes are `disabled` and `allowlist`. `allowlist` is the default enabled mode, and an empty allowlist means effectively local-only. `open` is refused as not yet supported, naming the mission that will add it. | FR-004, FR-005 | planned |
| FR-004 | A blocklist exists and **overrides the mode in every case**. It is not a mode. Matching is deterministic and resistant to case, trailing-slash and default-port confusion. | FR-007 | planned |
| FR-005 | `https` is the only accepted scheme. Every other — `http`, `file`, `gopher`, `s3`, `ftp` and the rest — is refused by allowlist, never by denylist. | FR-009, FR-012 | planned |
| FR-006 | Adding a peer authorises **addressed mail exchange and nothing else**: no database access, no inbox reads, no thread history, no operator-gated route, no actor enumeration beyond the discoverable directory. Asserted as negative tests, not stated. | FR-003 | planned |
| FR-007 | The peer add flow runs in order: normalise, **check the blocklist before any network call**, fetch the descriptor, read its fields, warn on a base-URL mismatch, confirm WebFinger, accept descriptor-only readiness for an empty server, record fingerprint and first-seen, and report `Ready` / `Warning` / `Failed` with an exact reason. | FR-013 | planned |
| FR-008 | Adding a peer imports nothing. No directory fetch, no actor enumeration. | FR-013 | planned |
| FR-009 | A server descriptor at `/.well-known/agent-inbox`, unauthenticated, carrying software, version, base URL, `title`, `description`, mode, capabilities, supported schemes and public key metadata. | FR-016, FR-017 | planned |
| FR-010 | The descriptor discloses the mode openly, accepted deliberately. It carries **no actor data, no counts, no operator information**, and **no hub `name`**. | FR-052, FR-030, FR-048 | planned |
| FR-011 | WebFinger resolves `acct:alice@hub.example` to a JRD with a `self` link to the actor document. | FR-018, FR-019 | planned |
| FR-012 | An actor whose visibility is `local` **does not resolve at all** — not through WebFinger, not in the directory, not by actor-document lookup. A hit is itself disclosure that the actor exists. | FR-025 | planned |
| FR-013 | Actor documents carry the inbox URL, public key metadata and display fields, and none of FR-010's exclusions. | FR-021, FR-030 | planned |
| FR-014 | A federated directory lists **only** `discoverable` actors, minimal profile data, paged at 50. `normal` actors are addressable but unlisted — that distinction is why there are three levels rather than two. | FR-029, FR-030 | planned |
| FR-015 | Actor visibility is `local` / `normal` / `discoverable`, defaulting to `normal`, set by the actor through the existing profile surface. An unknown value is refused at the write; a bad stored value does not stop the hub starting. | FR-023, FR-024, FR-028 | planned |
| FR-016 | Visibility is a **ceiling on exposure, never a grant**. Server policy still wins: a `discoverable` actor on a `disabled` hub, or behind the blocklist, is unreachable. | FR-053 | planned |
| FR-017 | Local and remote actors may share a username. Remote actors are always displayed with their domain, and remote identity is stored as the actor URI — never the typed handle or display name. | FR-021, FR-022 | planned |
| FR-018 | A signing keypair is generated once, stored beside the mail, never regenerated silently. The **public** half appears in actor documents and the descriptor; the private half appears in no log, error, audit entry or response. | FR-039 (part) | planned |
| FR-019 | Federation configuration uses the hub settings mechanism: the environment wins for scalars, and overriding never erases. A governed setting is **reported as governed, naming the variable** — as `config list` already reports each client setting with its source, which is the pattern to copy rather than invent. Peer lists and the blocklist are stored-only. | FR-043, FR-044, FR-045, FR-049 | planned |
| FR-020 | The federation inbox route refuses with `403` and a reason. `501 Not Implemented` says *this software cannot*, and once this ships that is false — a hub in `disabled` mode is saying *this hub will not*. The body must stop citing superseded mission numbers 0024 and 0025. | FR-046 | planned |
| FR-021 | Changing the **public URL** warns that federated identifiers become stale. Changing the hub **`name`** does not, and needs no forwarding, aliases or grace periods — nothing outside the hub ever held it. | FR-015, FR-051 | planned |
| FR-022 | The operator surface is the **CLI**: enable and disable, add / remove / list peers with their check result and reason, add / remove / list blocklist entries, and a status view showing which settings the deployment has fixed. ADR 0005 already makes the CLI a first-class client, so this is not a downgrade from a console — it is the same API, reached by the surface an operator already has in the terminal. | FR-001 (part) | planned |
| FR-023 | Every administrative action and every automated refusal is audited: timestamp, acting human where there is one, action, target, before and after **where safe**, and the reason. Append-only, never carrying a key, a token or message content. | FR-042 (slice) | planned |
| FR-024 | All authenticated human operators may manage federation. Finer-grained roles are future work. Administration is out of band; no message can change any of it. | FR-041, C-005 | planned |

## Non-functional requirements

| ID | Requirement | Threshold | Parent |
|---|---|---|---|
| NFR-001 | Federation is off by default. | A newly started hub has no ingress or egress without operator action | NFR-001 |
| NFR-002 | Federation is testable without external services. | Two hubs in one process, wired by a transport stub, in normal CI — no sockets, no network | NFR-008 |
| NFR-003 | One API. | The CLI reads and writes through the API and recomputes no policy. No client re-implements the decision | NFR-007 |
| NFR-004 | Unauthenticated surfaces disclose nothing beyond FR-009's list. | Asserted as **absences**, not as presences | NFR-003 |

## Constraints

| ID | Constraint | Parent |
|---|---|---|
| C-001 | Do not invent names for concepts ActivityStreams already names. | C-001 |
| C-002 | `@local` must never be federated. Already enforced in `addressing.py`; this mission must not regress it. | C-007 |
| C-003 | When in doubt, do what Lemmy does. Departures recorded, never silent. Engagement mechanics are out regardless, and a binding ADR beats Lemmy. | C-008 |
| C-004 | No public self-registration is introduced. | C-006 |
| C-005 | Groups, bridges and NAT relays are out. | C-003, C-004 |
| C-006 | The policy decision is made in **one place**. If it is made twice the two will disagree, and a disagreement here is a disclosure. | parent IC-01 |

## Test matrix

| Case | Expected |
|---|---|
| A hub nobody has configured | mode `disabled`, no peers, inbox `403`, descriptor says federation off |
| Enabling while named `local` | refused, saying why |
| Renaming, then enabling | permitted |
| Enabling with no public URL | refused |
| A blocked domain in `allowlist` mode | refused, and **no network call made** |
| A blocked domain added with trailing slash / different case / explicit default port | still blocked |
| An `http://` peer | refused, naming the rule |
| A valid hub with no actors | `Ready` |
| A peer whose descriptor declares a different base URL | `Warning`, with the mismatch shown |
| Adding a peer | zero directory fetches, asserted by counting |
| An enabled peer attempting an inbox read, a history read, or an operator route | refused, each asserted separately |
| WebFinger for a `normal` actor | resolves |
| WebFinger for a `local` actor | does not resolve — absent, not flagged |
| The directory | lists `discoverable` only |
| A `discoverable` actor on a `disabled` hub | unreachable |
| Any unauthenticated surface | no actor data, no counts, no operator info, no hub `name` |
| Renaming the hub | every federated surface byte-identical |
| Changing the public URL | warns about stale identifiers |
| An environment variable governing a federation scalar | field disabled in the UI, naming the variable |

`@local` is absent from this table because it is already enforced and tested; C-002 exists so
that stays true.

## Out of scope — and where it goes

| Deferred | To |
|---|---|
| Sending and receiving mail, queues, retry, dedupe, provenance | the delivery missions |
| Signing and verifying requests | the mission that first moves mail |
| **Send-time re-authorization (parent FR-050)** — found by outside review, the sharpest requirement in the parent | the outbound mission. It must not be lost in the split |
| `open` mode, HTTP federation, and both warning flows | a later mission, if wanted at all |
| Delivery state and peer health in the UI | the delivery missions |
| A friendly-name registry | [#16](https://github.com/salimfadhley/agent-inbox/issues/16), deferred with a trigger |
| The console section for federation | its own mission, after [#21](https://github.com/salimfadhley/agent-inbox/issues/21) settles where settings live |

## Answered, 2026-07-28

### `Warning` is advisory, but enabling over one is deliberate

Decision `01KYN7QVXF2ADJ1W0KHZ1X89MD`. If a `Warning` blocked enabling it would be
indistinguishable from `Failed`, and the three states would be two with extra words. But a
base-URL mismatch is exactly the shape of *you typed the wrong host*, so it must not pass
silently either.

So: enabling a peer in `Warning` requires explicit confirmation, and the warning text is
recorded in the audit entry (FR-023). C-008 gives no steer — Lemmy has no equivalent
compatibility check, instances go straight onto allow and block lists — so this is our own
call, recorded as a gap in the tie-breaker rather than a disagreement with it.

### The descriptor is always served, and reports the mode honestly

Decision `01KYN7QX8706MRGW27FF2E13N5`. Requiring federation to be *on* before the descriptor
is served creates a **bootstrap deadlock**: hub A cannot compatibility-check hub B until B
enables, and B cannot check A until A enables. Two fresh hubs could never peer.

The disclosure objection turns out to be empty. `GET /` already publishes
`"federates": false` to anyone, unauthenticated, today. A descriptor served while disabled
tells a stranger nothing they cannot already learn.

### The operator surface is the CLI; the console comes later

Decision `01KYN8T9HXADTFM3B2TK9DZH4X`. ADR 0005 says one API and every client is a client,
and the CLI is one — so a CLI-only mission is not a reduced version of a console mission, it
is the same capability reached from the terminal.

Three things follow. The mission loses its dependency on
[#21](https://github.com/salimfadhley/agent-inbox/issues/21), so nothing outside it gates it.
It becomes pure backend plus CLI, which is one fewer kind of work to hold at once. And the
console section becomes **its own small mission**, landing after #21 has settled where
settings live — which is a better order anyway, since building a section before the tab it
sits in is what made the parent mission's WP12 fragile.

## Provenance

Carved from `manual-activitypub-federation-v1-01KYJY10` on 2026-07-28, after that mission
failed to converge across two review rounds. The split was proposed independently by the
assistant and by an outside model (charter directive 4); they agreed on this first seam and
disagreed after it, which is why only this mission is specified. The scope reductions above
are the assistant's, taken on the operator's instruction to shape the first mission, and
reversible on request.
