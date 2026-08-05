# Tasks — Federated identity and trust

- Mission: `federated-identity-and-trust-01KYN49V`
- Spec: `kitty-specs/federated-identity-and-trust-01KYN49V/spec.md`
- Plan: `kitty-specs/federated-identity-and-trust-01KYN49V/plan.md`
- Planning base: `main` · Merge target: `main`

## What this covers, and what it does not

The spec has 24 functional requirements. **Eight are already shipped** and are not
scheduled here — see the audit table in `plan.md`, every row of which was read in the
source rather than assumed. Scheduling them would be work that produces no change.

This decomposes the eight that are genuinely unbuilt, plus one to verify.

**It also supersedes two work packages of the parent mission.** `manual-activitypub-
federation-v1-01KYJY10` WP03 (the policy decision) and WP10 (actor visibility) describe
the same work as WP01–WP04 below. They must not both be built: the parent's own WP03 says
*"if the decision is made in two places they will disagree, and a disagreement here is a
disclosure"*, and two work packages is the most direct way to arrange that.

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | One decision function: *may this exchange happen* | WP01 | |
| T002 | Stored blocklist, with case / trailing-slash / default-port normalisation | WP01 | |
| T003 | The blocklist overrides the mode in every case — it is not a mode | WP01 | |
| T004 | Consult the blocklist **before** any network call in the add flow | WP01 | |
| T005 | Tests, including the no-network-call assertion and a single-decision proof | WP01 | |
| T006 | `local` / `normal` / `discoverable` on the actor record, default `normal` | WP02 | |
| T007 | Set through the existing profile surface; unknown values refused at the write | WP02 | |
| T008 | A bad stored value does not stop the hub starting | WP02 | |
| T009 | Tests for the field and its refusals | WP02 | |
| T010 | The directory lists `discoverable` only | WP03 | |
| T011 | A `local` actor does not resolve — WebFinger, directory, or document | WP03 | |
| T012 | Visibility is a ceiling: hub mode and blocklist still win | WP03 | |
| T013 | Refusals are indistinguishable from "no such actor" | WP03 | |
| T014 | Tests written as absences, not presences | WP03 | |
| T015 | `/.well-known/agent-inbox` descriptor, unauthenticated | WP04 | [P] |
| T016 | It carries no actor data, no counts, no operator info, no hub `name` | WP04 | [P] |
| T017 | Served whether or not federation is on, reporting the mode honestly | WP04 | [P] |
| T018 | Tests asserting the exclusions | WP04 | [P] |
| T019 | `federation enable` / `disable`, refusing with the reason | WP05 | |
| T020 | `peers add` / `remove` / `list`, with check result and reason | WP05 | |
| T021 | `blocklist add` / `remove` / `list` | WP05 | |
| T022 | `federation status`, naming which settings the environment has fixed | WP05 | |
| T023 | The CLI recomputes no policy — asserted | WP05 | |
| T024 | Audit every administrative action and every automated refusal | WP06 | [P] |
| T025 | Never carrying a key, a token, or message content | WP06 | [P] |
| T026 | Verify FR-020: the inbox refusal may already be correct | WP06 | [P] |

---

## Ship 1 — an operator can refuse a peer

### WP01 — The decision, and the blocklist

**Goal**: one function that answers *may this exchange happen*, and a blocklist that
overrides the mode in every case. **Independent test**: a blocked domain is refused in
`allowlist` mode **with no network call made**, and the refusal survives a trailing slash,
a different case, and an explicit default port.

- [ ] T001 One decision function: *may this exchange happen* (WP01)
- [ ] T002 Stored blocklist, with case / trailing-slash / default-port normalisation (WP01)
- [ ] T003 The blocklist overrides the mode in every case — it is not a mode (WP01)
- [ ] T004 Consult the blocklist **before** any network call in the add flow (WP01)
- [ ] T005 Tests, including the no-network-call assertion and a single-decision proof (WP01)

**Risks**: C-006. The proof that matters is not that the function returns the right answer
but that **no second implementation exists** — grep for anywhere else that decides, and
assert on it.

---

## Ship 2 — an actor decides who can find it

### WP02 — Visibility as a field the actor owns

**Goal**: `local` / `normal` / `discoverable`, default `normal`, set through the existing
profile surface. **Dependencies**: none — parallel with WP01. **Independent test**: an
unknown value is refused at the write, and a bad value already in the store does not stop
the hub starting.

- [ ] T006 `local` / `normal` / `discoverable` on the actor record, default `normal` (WP02)
- [ ] T007 Set through the existing profile surface; unknown values refused at the write (WP02)
- [ ] T008 A bad stored value does not stop the hub starting (WP02)
- [ ] T009 Tests for the field and its refusals (WP02)

**Risks**: this is actor-owned, not administrative (ADR 0008 is not in tension — an agent
choosing its own reachability is not administration of the hub). Do not add a second place
where actor facts live.

### WP03 — What visibility actually withholds

**Goal**: the directory lists `discoverable` only, and a `local` actor does not resolve at
all. **Dependencies**: WP01, WP02. **Independent test**: WebFinger for a `local` actor is
**absent, not flagged** — and indistinguishable from a name nobody has held.

- [ ] T010 The directory lists `discoverable` only (WP03)
- [ ] T011 A `local` actor does not resolve — WebFinger, directory, or document (WP03)
- [ ] T012 Visibility is a ceiling: hub mode and blocklist still win (WP03)
- [ ] T013 Refusals are indistinguishable from "no such actor" (WP03)
- [ ] T014 Tests written as absences, not presences (WP03)

**Risks**: the whole mission's sharpest requirement, and the one most likely to be
implemented as a directory filter and called done. `House.directory()` returns every actor
today (`house.py:448`); filtering it is necessary and nowhere near sufficient. A differently
worded refusal is an oracle.

---

## Ship 3 — the surfaces an operator and a peer use

### WP04 — The server descriptor

**Goal**: `/.well-known/agent-inbox`, unauthenticated, carrying what a prospective peer
needs to compatibility-check us. **Dependencies**: none. **Independent test**: it is served
on a hub with federation off, and carries none of FR-010's exclusions.

- [ ] T015 `/.well-known/agent-inbox` descriptor, unauthenticated (WP04)
- [ ] T016 It carries no actor data, no counts, no operator info, no hub `name` (WP04)
- [ ] T017 Served whether or not federation is on, reporting the mode honestly (WP04)
- [ ] T018 Tests asserting the exclusions (WP04)

**Risks**: served while disabled **on purpose** — decision `01KYN7QX8706MRGW27FF2E13N5`.
Requiring federation to be on first is a bootstrap deadlock: two fresh hubs could never
peer. The disclosure objection is empty because `GET /` already publishes `federates` to
anyone.

### WP05 — The operator's CLI

**Goal**: enable, disable, peers, blocklist, status. **Dependencies**: WP01, WP02.
**Independent test**: every command goes through the API, and none recomputes policy.

- [ ] T019 `federation enable` / `disable`, refusing with the reason (WP05)
- [ ] T020 `peers add` / `remove` / `list`, with check result and reason (WP05)
- [ ] T021 `blocklist add` / `remove` / `list` (WP05)
- [ ] T022 `federation status`, naming which settings the environment has fixed (WP05)
- [ ] T023 The CLI recomputes no policy — asserted (WP05)

**Risks**: NFR-003 and C-006 again. `config list` already reports each setting with its
source; copy that rather than inventing a second way to say "the environment governs this".

### WP06 — Audit, and one thing to verify

**Goal**: every administrative action and automated refusal recorded. **Dependencies**:
WP01. **Independent test**: an audit entry exists for a refusal nobody typed, and no entry
anywhere carries a key, a token, or message content.

- [ ] T024 Audit every administrative action and every automated refusal (WP06)
- [ ] T025 Never carrying a key, a token, or message content (WP06)
- [ ] T026 Verify FR-020: the inbox refusal may already be correct (WP06)

**Risks**: T026 is a *check*, not a build. Neither `501` nor missions 0024/0025 appear in
`api.py` today, so this requirement may already be satisfied — in which case close it rather
than re-satisfying it.

## On the requirement-mapping validator

`finalize-tasks --validate-only` reports twenty-five unmapped functional requirements.
Recorded rather than worked around, because the number is misleading in two distinct
ways and a later reader will otherwise think this decomposition has holes.

**Most of them are not this mission's requirements.** The spec's FR table carries a
*Parent* column for traceability — `FR-025`, `FR-041` through `FR-053` and the rest are
ids belonging to `manual-activitypub-federation-v1`, kept so the split can be traced
back. The validator reads that column as requirements of this mission. They have no
work packages here because they are not requirements here.

**The remainder are already shipped**, and the audit in `plan.md` names each with a file
and line: FR-001 (federation off by default), FR-002 (the enable guard), FR-005
(https-only by allowlist), FR-011 (WebFinger), FR-018 (the signing keypair). Mapping them
to a work package would schedule work that produces no change, which is the exact failure
the audit exists to prevent.

Ownership *was* worth re-checking by hand, and found something real: WP03 and WP06 both
claimed `house.py`. WP06 now owns `federation.py`, where a federation audit belongs
anyway. No overlaps remain across the fourteen owned paths.

## MVP

**WP01 alone is shippable and is the safety gap.** Without it there is no way to refuse a
specific peer except by never adding it, which FR-004 says is not the same thing.

## Parallel opportunities

- WP01 and WP02 have no dependency on each other.
- WP04 depends on nothing and can run alongside either.
