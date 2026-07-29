# Work Packages: Manual ActivityPub Federation V1

**Inputs**: design documents in `kitty-specs/manual-activitypub-federation-v1-01KYJY10/`
**Prerequisites**: `spec.md`, `plan.md`, and the outside review in `research/`
**Branch**: planning base `feat/federation`; completed changes merge into `feat/federation`.

**Tests**: included throughout, and several subtasks require a test to be **proved by
removing the code it guards and watching it fail**. This project has shipped four tests that
passed with the fix removed and caught all four that way. In a mission where the failure mode
is silent disclosure, an unproved test is worse than none — it is believed.

**Organization**: 84 subtasks (`T001`–`T084`) roll into 14 work packages
(`WP01`–`WP14`), 5–7 subtasks each. This is the largest mission in the project.

## ⛔ Sequencing gate

**No work package here may start until `a-hub-has-a-name-of-its-own-01KYMD90` is implemented
and merged.** Federation depends on the hub `name`, the settings storage, the precedence rule
and the `local` gate that mission builds. Charter directive 3: if layer N−1 is not settled,
settling it *is* the work.

## Two decisions still owed by the operator

1. **A new runtime dependency.** Outbound federation needs an async HTTP client; the project
   has none and uses stdlib `urllib.request`. See `plan.md` Technical Context.
2. **[#21](https://github.com/salimfadhley/agent-inbox/issues/21) re-organises the console**
   into a Settings tab with Federation as a *section*. WP12 builds a section on that
   assumption.

## Subtask Index

Reference table only — progress is tracked by the checkboxes under each work package.
`[P]` marks a package with no dependencies, which can start immediately once the gate above
is cleared.

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | Two apps, two stores, one process | WP01 | [P] |
| T002 | A transport that carries A's outbound to B's inbound | WP01 | [P] |
| T003 | Injectable failure: 503, timeout, and a stalled retry | WP01 | [P] |
| T004 | Controllable time, so backoff is testable without sleeping | WP01 | [P] |
| T005 | Prove the harness, by making it fail | WP01 | [P] |
| T006 | Peers and blocklist | WP02 | [P] |
| T007 | The outbound delivery queue | WP02 | [P] |
| T008 | Seen inbound activity ids, with expiry | WP02 | [P] |
| T009 | Audit entries | WP02 | [P] |
| T010 | Contract tests across both stores | WP02 | [P] |
| T011 | An existing database survives | WP02 | [P] |
| T012 | Convert `federation.py` to a package, rule intact | WP03 |  |
| T013 | The decision function | WP03 |  |
| T014 | Modes, and the blocklist that overrides them | WP03 |  |
| T015 | Scheme policy | WP03 |  |
| T016 | Actor visibility as a ceiling | WP03 |  |
| T017 | The decision table, exhaustively | WP03 |  |
| T018 | A signing keypair, generated once and kept | WP04 |  |
| T019 | Public key metadata in actor documents | WP04 |  |
| T020 | Sign outbound requests | WP04 |  |
| T021 | Verify inbound requests | WP04 |  |
| T022 | Attack the verifier | WP04 |  |
| T023 | Clock skew, deliberately | WP04 |  |
| T024 | The server descriptor at `/.well-known/agent-inbox` | WP05 |  |
| T025 | WebFinger for local actors | WP05 |  |
| T026 | Actor documents | WP05 |  |
| T027 | The federated directory | WP05 |  |
| T028 | Outbound resolution of `@alice@example.com` | WP05 |  |
| T029 | Disclosure tests | WP05 |  |
| T030 | Local and remote may share a username | WP05 |  |
| T031 | Normalise, then check the blocklist first | WP06 |  |
| T032 | Fetch and read the descriptor | WP06 |  |
| T033 | Confirm WebFinger, and readiness | WP06 |  |
| T034 | Ready / Warning / Failed, with exact reasons | WP06 |  |
| T035 | Adding a peer imports nothing | WP06 |  |
| T036 | Identity changes: the two directions | WP06 |  |
| T037 | Widen `local_name()`, and only that | WP07 |  |
| T038 | Resolve recipients to actor URIs and inboxes | WP07 |  |
| T039 | Persist locally first, then queue | WP07 |  |
| T040 | `Create` wrapping `Note`, with `to`, `cc`, `inReplyTo` | WP07 |  |
| T041 | One queue entry per target inbox | WP07 |  |
| T042 | Tests, including the one that must not regress | WP07 |  |
| T043 | Re-derive the whole decision at send time | WP08 |  |
| T044 | Backoff, bounded | WP08 |  |
| T045 | One concurrent send per peer | WP08 |  |
| T046 | Delivery state, visible | WP08 |  |
| T047 | Blocking cancels what is pending | WP08 |  |
| T048 | The stale-authorization tests | WP08 |  |
| T049 | The gate, in order | WP09 |  |
| T050 | Reject unsupported activity types | WP09 |  |
| T051 | Duplicate activity ids are no-ops | WP09 |  |
| T052 | Deliver into the normal flow, visibly remote | WP09 |  |
| T053 | Remote content is data, never instruction | WP09 |  |
| T054 | Rejection tests that look in the mailbox | WP09 |  |
| T055 | Visibility as a profile field | WP10 |  |
| T056 | Validate the enum, refuse the rest | WP10 |  |
| T057 | A ceiling, never a grant | WP10 |  |
| T058 | Narrowing takes effect on in-flight mail | WP10 |  |
| T059 | Humans and agents both | WP10 |  |
| T060 | Register the federation routes | WP11 |  |
| T061 | The enable/disable route, operator-gated | WP11 |  |
| T062 | `501` becomes `403` when the meaning changes | WP11 |  |
| T063 | `federates` tells the truth | WP11 |  |
| T064 | Tests | WP11 |  |
| T065 | The section, reading through the API | WP12 |  |
| T066 | Peer add, showing the check | WP12 |  |
| T067 | The HTTP warning, unavoidable | WP12 |  |
| T068 | Open mode, and open-plus-HTTP | WP12 |  |
| T069 | Delivery state and peer health | WP12 |  |
| T070 | Console tests | WP12 |  |
| T071 | Emit from the decision, not beside it | WP13 |  |
| T072 | Administrative events | WP13 |  |
| T073 | Before and after, where safe | WP13 |  |
| T074 | Append-only | WP13 |  |
| T075 | Tests | WP13 |  |
| T076 | The prompt | WP14 |  |
| T077 | `addressing.py`'s module docstring | WP14 |  |
| T078 | `RemoteMailbox` and the refusal text | WP14 |  |
| T079 | README and a federation runbook | WP14 |  |
| T080 | Sweep for stale claims | WP14 |  |
| T081 | The trust boundary, asserted as negatives | WP06 |  |
| T082 | A fresh hub federates with nobody, asserted | WP11 |  |
| T083 | Blocklist management | WP12 |  |
| T084 | Delivery state where an operator looks for it | WP12 |  |

---

## Work Package WP01: Two hubs in one process: the federation harness

**Goal**: Federation is two hubs talking. Every delivery requirement in this mission is a
statement about what hub B ends up holding after hub A does something, and none of it can be
asserted without two hubs. Build that first.
**Prompt**: `tasks/WP01-two-hubs-in-one-process.md`
**Requirement Refs**: NFR-008
**Owns**: `tests/federation/__init__.py`, `tests/federation/harness.py`, `tests/federation/test_harness.py`

### Included Subtasks

- [ ] T001 Two apps, two stores, one process (WP01)
- [ ] T002 A transport that carries A's outbound to B's inbound (WP01)
- [ ] T003 Injectable failure: 503, timeout, and a stalled retry (WP01)
- [ ] T004 Controllable time, so backoff is testable without sleeping (WP01)
- [ ] T005 Prove the harness, by making it fail (WP01)

### Dependencies

None

### Risks & Mitigations

- **A harness that always delivers** — Every policy test downstream becomes vacuous. *Mitigation*: T005 breaks it on purpose and asserts the break.
- **Shared state between the two hubs** — Isolation assertions pass for the wrong reason. *Mitigation*: T001 asserts the stores differ.
- **Wall-clock sleeps** — An unrunnable suite, so retry logic goes untested. *Mitigation*: T004 injects the clock.
---

## Work Package WP02: Federation storage: peers, blocklist, queue, seen ids, audit

**Goal**: Somewhere to keep what federation knows: peers, blocklist entries, the outbound
delivery queue, the ids of inbound activities already seen, and the audit trail.
**Prompt**: `tasks/WP02-federation-storage.md`
**Requirement Refs**: FR-037, FR-042, FR-043, FR-044, FR-045, FR-049
**Owns**: `src/agent_inbox/sqlite_store.py`, `src/agent_inbox/store.py`, `tests/test_store_contract.py`

### Included Subtasks

- [ ] T006 Peers and blocklist (WP02)
- [ ] T007 The outbound delivery queue (WP02)
- [ ] T008 Seen inbound activity ids, with expiry (WP02)
- [ ] T009 Audit entries (WP02)
- [ ] T010 Contract tests across both stores (WP02)
- [ ] T011 An existing database survives (WP02)

### Dependencies

None

### Risks & Mitigations

- **A blocklist that can be bypassed by a trailing slash** — It is believed, so the bypass is silent. *Mitigation*: T006 and T010 test the confusable forms.
- **Persisting the authorization decision** — Recreates the FR-050 hole in the storage layer. *Mitigation*: T007 forbids it explicitly.
- **Seen-ids growing without bound, or expiring too soon** — Disk exhaustion, or duplicate delivery. *Mitigation*: T008 sets the floor above the retry cap, with reasoning.
---

## Work Package WP03: The policy decision, in one place

**Goal**: One function that answers *may this exchange happen*, and every inbound and
outbound path asks it.
**Prompt**: `tasks/WP03-the-policy-decision.md`
**Requirement Refs**: C-007, C-008, FR-004, FR-005, FR-006, FR-007, FR-008, FR-012, FR-025, FR-026, FR-027, FR-053
**Owns**: `src/agent_inbox/federation/__init__.py`, `src/agent_inbox/federation/policy.py`, `tests/test_federation_policy.py`

### Included Subtasks

- [ ] T012 Convert `federation.py` to a package, rule intact (WP03)
- [ ] T013 The decision function (WP03)
- [ ] T014 Modes, and the blocklist that overrides them (WP03)
- [ ] T015 Scheme policy (WP03)
- [ ] T016 Actor visibility as a ceiling (WP03)
- [ ] T017 The decision table, exhaustively (WP03)

### Dependencies

WP02

### Risks & Mitigations

- **Policy evaluated in more than one place** — They diverge; the divergence is a disclosure. *Mitigation*: One entry point; T017's table is the contract.
- **Blocklist checked per call site** — One site forgets. *Mitigation*: T014 puts it inside, before the mode check.
- **Visibility read as a grant** — Inverts the policy — a `discoverable` actor becomes reachable on a disabled hub. *Mitigation*: T016 encodes the ordering; T017 tests it.
- **Moving the `local` rule breaks its guard test** — The gate silently stops being enforced. *Mitigation*: T012 runs it before and after.
---

## Work Package WP04: Keys and RFC 9421 signatures

**Goal**: Sign what we send; verify what arrives. `cryptography` is already a dependency
(auth uses it), so this needs no new package.
**Prompt**: `tasks/WP04-keys-and-signatures.md`
**Requirement Refs**: FR-039
**Owns**: `src/agent_inbox/federation/keys.py`, `src/agent_inbox/federation/signatures.py`, `tests/test_federation_signatures.py`

### Included Subtasks

- [ ] T018 A signing keypair, generated once and kept (WP04)
- [ ] T019 Public key metadata in actor documents (WP04)
- [ ] T020 Sign outbound requests (WP04)
- [ ] T021 Verify inbound requests (WP04)
- [ ] T022 Attack the verifier (WP04)
- [ ] T023 Clock skew, deliberately (WP04)

### Dependencies

WP02

### Risks & Mitigations

- **A path that accepts without verifying** — Total, and silent. *Mitigation*: T021 defaults to refusal; T022 removes the call and watches tests fail.
- **Signing different bytes than are sent** — Passes locally, fails against strict peers. *Mitigation*: T020 signs the sent body.
- **The private key reaching a log or the descriptor** — Compromise. *Mitigation*: T018 forbids it; audit records no secrets.
---

## Work Package WP05: Discovery: descriptor, WebFinger, actor documents

**Goal**: What a peer can read about us: the server descriptor, WebFinger resolution, actor
documents, and the discoverable-actor directory.
**Prompt**: `tasks/WP05-discovery-surfaces.md`
**Requirement Refs**: C-001, C-006, FR-016, FR-017, FR-018, FR-019, FR-020, FR-021, FR-022, FR-025, FR-029, FR-030, FR-048, FR-052
**Owns**: `src/agent_inbox/federation/routes.py`, `src/agent_inbox/federation/webfinger.py`, `tests/test_federation_discovery.py`

### Included Subtasks

- [ ] T024 The server descriptor at `/.well-known/agent-inbox` (WP05)
- [ ] T025 WebFinger for local actors (WP05)
- [ ] T026 Actor documents (WP05)
- [ ] T027 The federated directory (WP05)
- [ ] T028 Outbound resolution of `@alice@example.com` (WP05)
- [ ] T029 Disclosure tests (WP05)
- [ ] T030 Local and remote may share a username (WP05)

### Dependencies

WP03, WP04

### Risks & Mitigations

- **A field added to the descriptor without a disclosure decision** — It is unauthenticated; anyone reads it. *Mitigation*: T029 asserts absences, not presences.
- **`local` actors resolving through WebFinger** — Existence disclosure — mission 0020's class, one hop out. *Mitigation*: T025 and T029.
- **The hub name leaking onto a federated surface** — Breaks FR-051's free rename. *Mitigation*: T024 and T029 assert its absence.
---

## Work Package WP06: Peers, the add flow, and the compatibility check

**Goal**: Adding a peer, and finding out before you trust it whether it can actually talk to
you. The spec's nine-step add flow, implemented in order — the order is the requirement.
**Prompt**: `tasks/WP06-peers-and-the-add-flow.md`
**Requirement Refs**: C-004, FR-002, FR-003, FR-009, FR-013, FR-014, FR-015, FR-051
**Owns**: `src/agent_inbox/federation/peers.py`, `tests/test_federation_peers.py`

### Included Subtasks

- [ ] T031 Normalise, then check the blocklist first (WP06)
- [ ] T032 Fetch and read the descriptor (WP06)
- [ ] T033 Confirm WebFinger, and readiness (WP06)
- [ ] T034 Ready / Warning / Failed, with exact reasons (WP06)
- [ ] T035 Adding a peer imports nothing (WP06)
- [ ] T036 Identity changes: the two directions (WP06)
- [ ] T081 The trust boundary, asserted as negatives (WP06)

### Dependencies

WP03, WP04, WP05

### Risks & Mitigations

- **Two normalisers** — A blocklist bypass. *Mitigation*: T031 shares WP02's canonical form.
- **Network calls before the blocklist check** — The blocklist stops being a boundary. *Mitigation*: T031 orders it first; T035 counts fetches.
- **A peer's text rendered as markup** — Stored XSS from a hostile peer. *Mitigation*: T032 treats fetched fields as untrusted.
- **Adding a peer quietly importing a directory** — Unbounded work from one operator click. *Mitigation*: T035 asserts the fetch was not made.
---

## Work Package WP07: Outbound: resolution and queueing

**Goal**: A local send that names a remote actor succeeds locally and queues delivery behind
itself. The sender never waits on a remote server (FR-034).
**Prompt**: `tasks/WP07-outbound-resolution-and-queueing.md`
**Requirement Refs**: FR-031, FR-032, FR-034, FR-047
**Owns**: `src/agent_inbox/federation/outbound.py`, `src/agent_inbox/addressing.py`, `tests/test_federation_outbound.py`, `tests/test_addressing.py`

### Included Subtasks

- [ ] T037 Widen `local_name()`, and only that (WP07)
- [ ] T038 Resolve recipients to actor URIs and inboxes (WP07)
- [ ] T039 Persist locally first, then queue (WP07)
- [ ] T040 `Create` wrapping `Note`, with `to`, `cc`, `inReplyTo` (WP07)
- [ ] T041 One queue entry per target inbox (WP07)
- [ ] T042 Tests, including the one that must not regress (WP07)

### Dependencies

WP03, WP05, WP06

### Risks & Mitigations

- **`@local` egressing once federation is on** — Breaks a guarantee agents rely on by inspection. *Mitigation*: T042 removes the guard and asserts failure.
- **Address knowledge spreading beyond `local_name()`** — Undoes the seam the module was built around. *Mitigation*: T037 restricts the change.
- **A local send failing because a peer is unreachable** — Loses mail for a remote problem. *Mitigation*: T039 orders persistence first.
---

## Work Package WP08: Delivery, retry, and send-time re-authorization

**Goal**: Drain the queue: sign, send, retry with backoff, and report state.
**Prompt**: `tasks/WP08-delivery-retry-and-send-time-authorization.md`
**Requirement Refs**: FR-008, FR-050, NFR-002
**Owns**: `src/agent_inbox/federation/delivery.py`, `tests/test_federation_delivery.py`

### Included Subtasks

- [ ] T043 Re-derive the whole decision at send time (WP08)
- [ ] T044 Backoff, bounded (WP08)
- [ ] T045 One concurrent send per peer (WP08)
- [ ] T046 Delivery state, visible (WP08)
- [ ] T047 Blocking cancels what is pending (WP08)
- [ ] T048 The stale-authorization tests (WP08)

### Dependencies

WP07

### Risks & Mitigations

- **Authorization carried from queue time** — The mission's known hole; egress after federation is disabled. *Mitigation*: T043 re-derives everything; T048 proves it by removal.
- **Asserting on the inbox instead of the attempt** — A refused attempt still leaked that we tried. *Mitigation*: T048 asserts on the attempt log.
- **Ambient time in backoff** — Untestable, so untested. *Mitigation*: T044 injects the clock.
- **Per-property cancellation paths** — Exactly what left two of three cases uncovered. *Mitigation*: T043 forbids it.
---

## Work Package WP09: Inbound: verify, gate, dedupe, deliver

**Goal**: Accept what policy allows, exactly once, into the normal inbox and thread flow.
**Prompt**: `tasks/WP09-inbound.md`
**Requirement Refs**: FR-031, FR-033, FR-035, FR-036, FR-037, FR-040, NFR-002, NFR-003, NFR-004
**Owns**: `src/agent_inbox/federation/inbound.py`, `tests/test_federation_inbound.py`

### Included Subtasks

- [ ] T049 The gate, in order (WP09)
- [ ] T050 Reject unsupported activity types (WP09)
- [ ] T051 Duplicate activity ids are no-ops (WP09)
- [ ] T052 Deliver into the normal flow, visibly remote (WP09)
- [ ] T053 Remote content is data, never instruction (WP09)
- [ ] T054 Rejection tests that look in the mailbox (WP09)

### Dependencies

WP03, WP04, WP05

### Risks & Mitigations

- **Checks after delivery** — A rejected message is already in a mailbox. *Mitigation*: T054 asserts inbox contents for every rejection.
- **A second delivery path** — Bypasses read tracking and the messaging rules. *Mitigation*: T052 goes through the core.
- **Thread disclosure across the boundary** — A shipped bug returning through a new door. *Mitigation*: T054 re-asserts mission 0020.
- **Unbounded parse before size check** — A hostile peer costs us memory. *Mitigation*: T049 rejects on size first.
---

## Work Package WP10: Actor visibility, set by the actor

**Goal**: `local` / `normal` / `discoverable`, as a profile field the actor edits itself
(clarified 2026-07-28, decision `01KYMQ8T23YB16YY7Y88EZPVVD`).
**Prompt**: `tasks/WP10-actor-visibility.md`
**Requirement Refs**: C-003, FR-023, FR-024, FR-028
**Owns**: `src/agent_inbox/federation/visibility.py`, `src/agent_inbox/wire.py`, `tests/test_federation_visibility.py`

### Included Subtasks

- [ ] T055 Visibility as a profile field (WP10)
- [ ] T056 Validate the enum, refuse the rest (WP10)
- [ ] T057 A ceiling, never a grant (WP10)
- [ ] T058 Narrowing takes effect on in-flight mail (WP10)
- [ ] T059 Humans and agents both (WP10)

### Dependencies

WP03

### Risks & Mitigations

- **A parallel administrative setting** — Two places actor facts live, diverging. *Mitigation*: T055 uses the existing profile surface.
- **`discoverable` read as permission** — Inverts policy; invisible until federation is live. *Mitigation*: T057 asserts unreachability under disabled and blocked.
- **Free-form validation** — A typo silently means `local`. *Mitigation*: T056 refuses unknown values at the write.
---

## Work Package WP11: The switch, and the honest status code

**Goal**: Turn federation on, and make the inbox route mean what it says.
**Prompt**: `tasks/WP11-the-switch-and-the-honest-status.md`
**Requirement Refs**: C-005, FR-002, FR-013, FR-041, FR-046, NFR-001
**Owns**: `src/agent_inbox/api.py`, `tests/test_federation_api.py`

### Included Subtasks

- [ ] T060 Register the federation routes (WP11)
- [ ] T061 The enable/disable route, operator-gated (WP11)
- [ ] T062 `501` becomes `403` when the meaning changes (WP11)
- [ ] T063 `federates` tells the truth (WP11)
- [ ] T064 Tests (WP11)
- [ ] T082 A fresh hub federates with nobody, asserted (WP11)

### Dependencies

WP03, WP09

### Risks & Mitigations

- **Reimplementing the `local` check** — Two rules that will disagree. *Mitigation*: T061 calls the shipped function.
- **A new code missing from `STATUS_BY_CODE`** — Becomes a 500; the generic handler hides it. *Mitigation*: T062 adds explicitly; T064 asserts codes.
- **Enabling permitted, federating blocked** — Leaves a half-configured hub reachable, which FR-013 forbids. *Mitigation*: T061 gates the mode.
---

## Work Package WP12: The Federation section of the console

**Goal**: Where an operator manages federation: peers, mode, blocklist, delivery state, peer
health, and the warnings that must be acknowledged before anything risky is switched on.
**Prompt**: `tasks/WP12-the-federation-console-section.md`
**Requirement Refs**: FR-001, FR-010, FR-011, FR-038, FR-041, NFR-005, NFR-006, NFR-007
**Owns**: `src/agent_inbox/console.py`, `tests/test_console_federation.py`

### Included Subtasks

- [ ] T065 The section, reading through the API (WP12)
- [ ] T066 Peer add, showing the check (WP12)
- [ ] T067 The HTTP warning, unavoidable (WP12)
- [ ] T068 Open mode, and open-plus-HTTP (WP12)
- [ ] T069 Delivery state and peer health (WP12)
- [ ] T070 Console tests (WP12)
- [ ] T083 Blocklist management (WP12)
- [ ] T084 Delivery state where an operator looks for it (WP12)

### Dependencies

WP06, WP08, WP11

### Risks & Mitigations

- **Building a tab that #21 immediately renames** — Wasted work and a rename across tests and docs. *Mitigation*: Build a section; read #21 first.
- **Warnings that can be clicked past** — NFR-005 requires acknowledgement, and the risk is real. *Mitigation*: T067 and T070 assert unavoidability.
- **Identical warning text for different risks** — Teaches click-through. *Mitigation*: T068 makes the stronger one distinguishable.
- **Console recomputing policy** — Two implementations diverging. *Mitigation*: T065 renders API output only.
---

## Work Package WP13: The audit log: who opened the door

**Goal**: Enough record to answer two questions: *who opened the door*, and *why was this
message accepted or rejected*.
**Prompt**: `tasks/WP13-the-audit-log.md`
**Requirement Refs**: FR-015, FR-042
**Owns**: `src/agent_inbox/federation/audit.py`, `tests/test_federation_audit.py`

### Included Subtasks

- [ ] T071 Emit from the decision, not beside it (WP13)
- [ ] T072 Administrative events (WP13)
- [ ] T073 Before and after, where safe (WP13)
- [ ] T074 Append-only (WP13)
- [ ] T075 Tests (WP13)

### Dependencies

WP02, WP08, WP09

### Risks & Mitigations

- **Decisions that produce no entry** — Silence reads as 'not rejected'. *Mitigation*: T071 emits from the decision itself.
- **Secrets in before/after** — Compromise via the audit trail. *Mitigation*: T073 redacts; T075 scans whole entries.
- **Audit purged with mail** — Loses the record of exactly the events worth keeping. *Mitigation*: T074 forces an explicit decision.
---

## Work Package WP14: The words follow the code

**Goal**: Several documents currently assert that this hub cannot federate. Each becomes false
the day this ships.
**Prompt**: `tasks/WP14-the-words-follow-the-code.md`
**Requirement Refs**: C-002, NFR-003, NFR-004
**Owns**: `src/agent_inbox/prompts.py`, `src/agent_inbox/exceptions.py`, `README.md`, `doc/runbook/federation.md`

### Included Subtasks

- [ ] T076 The prompt (WP14)
- [ ] T077 `addressing.py`'s module docstring (WP14)
- [ ] T078 `RemoteMailbox` and the refusal text (WP14)
- [ ] T079 README and a federation runbook (WP14)
- [ ] T080 Sweep for stale claims (WP14)

### Dependencies

WP11, WP12

### Risks & Mitigations

- **The prompt asserting something untrue** — Third time; it is the most-read document here. *Mitigation*: T076 generates per-hub truth rather than hedging.
- **Docs describing a switch that is off by default as if it were on** — Operators expect federation they do not have. *Mitigation*: T079 states the default plainly.
- **Deployment specifics returning to the repo** — Charter violation; 77 were removed once. *Mitigation*: T079 forbids them explicitly.

---

## Suggested order

**WP01 and WP02 first, in parallel** — the harness and the storage. Neither depends on
anything, and every other package asserts through one or both.

Then **WP03**, the policy decision, which is the highest-value target in the mission: if that
decision is made in two places they will disagree, and a disagreement there is a disclosure.

**WP08 carries the outside review's finding** (FR-050) and is the single package most worth
reviewing carefully. Its three stale-authorization tests must fail when the send-time re-check
is removed.
