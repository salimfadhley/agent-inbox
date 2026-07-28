# Work Packages: a hub has a name of its own

**Inputs**: design documents in `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/`
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/hub-settings.md`, `quickstart.md`
**Branch**: planning base `main`; completed changes merge into `main`.

**Tests**: included deliberately and throughout. This mission's central risk — an
environment override silently erasing a stored value — is invisible to inspection and only
provable by assertion. The project's recurring defect shape is *a check that passes because
it had nothing to look at*, so several subtasks below require a test to be proved by
removing the code it guards and watching it fail.

**Organization**: 28 subtasks (`T001`–`T028`) roll into 5 work packages (`WP01`–`WP05`).
Each work package is independently deliverable. Deep guidance lives in the prompt files;
this document is the checklist.

## Subtask Index

Reference table only — progress is tracked by the checkboxes under each work package.
`[P]` marks a subtask that can proceed in parallel with its siblings (distinct files).

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | `hub_settings` table on the SQLite store, additive migration | WP01 | |
| T002 | The same surface on the in-memory store | WP01 | [P] |
| T003 | Store contract tests exercise settings against both stores | WP01 | |
| T004 | Resolution in `serve.py`: environment over stored over default | WP01 | |
| T005 | Resolution reports source, and the variable name when governed | WP01 | |
| T006 | The override-does-not-erase assertion | WP01 | |
| T007 | `hub_name` validator in `naming.py`, reusing the agent-name rule | WP02 | |
| T008 | Refusal names the rule that was broken | WP02 | |
| T009 | Validation applies at writes, never at startup | WP02 | |
| T010 | Validation tests, including the two worked refusals | WP02 | |
| T011 | `title` and `description` on `GET /`, omitted when unset | WP03 | |
| T012 | `GET /hub/settings` — value, source, variable | WP03 | [P] |
| T013 | `PUT /hub`, operator-gated | WP03 | |
| T014 | `409` when a field is governed by the environment | WP03 | |
| T015 | `422` when the name is invalid | WP03 | |
| T016 | API tests, including refusal with an agent device token | WP03 | |
| T017 | A Federation tab and its navigation entry | WP04 | |
| T018 | Render the three fields from the API, not from recomputation | WP04 | |
| T019 | Environment-governed fields render disabled, naming the variable | WP04 | |
| T020 | Submit through `PUT /hub`; surface refusals rather than swallowing them | WP04 | |
| T021 | Console tests, including the disabled rendering and the placeholder notice | WP04 | |
| T022 | The federation gate: `local` blocks *enabling*, in one place | WP05 | |
| T023 | Prove the gate's test by removing the rule | WP05 | |
| T024 | The prompt introduces the hub by `title` and `description` | WP05 | |
| T025 | The prompt reads correctly when both are absent — every hub today | WP05 | [P] |
| T026 | Documentation: README, admin runbook, and the mission's own record | WP05 | [P] |
| T027 | Assert that identity survives the address — NFR-003 | WP03 | |
| T028 | The outside-model review, before the mission closes | WP05 | |

---

## Work Package WP01: Settings storage, and environment precedence (Priority: P0)

**Goal**: give the hub somewhere to keep three values about itself, and settle which source
wins when two of them speak.
**Independent Test**: with nothing configured a hub behaves byte-for-byte as today; with a
value stored and an environment variable set, resolution reports the environment's value
*and* says the environment supplied it; unsetting the variable returns the stored value.
**Prompt**: `tasks/WP01-settings-storage-and-precedence.md`
**Requirement Refs**: FR-003, FR-004, NFR-001, NFR-002

### Included Subtasks

- [ ] T001 Add a `hub_settings` table to `src/agent_inbox/sqlite_store.py` — additive, never touching `actors`, `objects` or `reads` (WP01)
- [ ] T002 Give `src/agent_inbox/store.py` the same settings surface so the contract tests cover both (WP01)
- [ ] T003 Extend `tests/test_store_contract.py` so settings behave identically on each store (WP01)
- [ ] T004 Resolve hub settings in `src/agent_inbox/serve.py`: environment, then stored, then default (WP01)
- [ ] T005 Return `ResolvedSetting` — value, source, and the variable name when the source is the environment (WP01)
- [ ] T006 Assert directly in `tests/test_hub_settings.py` that an override does not erase: store, override, restart, unset, restart, still there (WP01)

### Implementation Notes

This is the **first persistent state the hub has ever kept about itself**. Three tables
exist today and all three are about mail. A fourth is small, but it is a genuine widening
of what the store is for.

`client.effective_settings()` already returns `(value, source)` for client configuration.
Copy that shape. Two nearly-identical answers to "which one won" is worse than one.

### Parallel Opportunities

T002 can proceed alongside T001 — different files, and the contract test in T003 is what
forces them to agree.

### Dependencies

None. Everything else in the mission reads through this package.

### Risks & Mitigations

- **Overriding must not erase** — the highest risk in the mission, and the reason T006 is a
  subtask rather than a line in an acceptance list. If startup writes the environment's
  value into the store, an operator who later unsets the variable has silently lost their
  own setting, and it looks exactly like it worked. Mitigation: assert the full
  set/override/unset cycle.
- **A schema change against live mail.** Mitigation: additive only; an upgraded hub with no
  settings row is the ordinary case, not a missing-configuration error.

---

## Work Package WP02: Hub-name validation (Priority: P0)

**Goal**: make `name` an address component rather than free text.
**Independent Test**: `saltclub` and `local` are accepted; `The Salt Club` and
`hub.thesaltclub.xyz` are refused with a message naming the rule; a hub already configured
with a name the new rule would refuse still starts.
**Prompt**: `tasks/WP02-hub-name-validation.md`
**Requirement Refs**: FR-002, FR-006

### Included Subtasks

- [ ] T007 Add hub-name validation to `src/agent_inbox/naming.py`, reusing the agent-name rule rather than writing a second one (WP02)
- [ ] T008 Make the refusal say which rule was broken, not merely that something was (WP02)
- [ ] T009 Apply validation at writes only — a running hub must not fail to start because a rule arrived after its configuration did (WP02)
- [ ] T010 Test the two worked refusals from the spec, `local`'s acceptance, and the start-with-a-legacy-name case (WP02)

### Implementation Notes

**FR-006 is claimed by both WP02 and WP05, deliberately.** It has two halves that belong in
different places: `local` is a *permitted name* (here), and `local` *blocks enabling
federation* (WP05, where the consequence is). Putting the whole requirement in one package
would put a constraint where its consequence is not.

Measured, not assumed: `trevor@The Salt Club` parses **successfully** today into
`trevor@the salt club`, and `hub.thesaltclub.xyz` is accepted as a hub *name*. That second
one is the hostname/name conflation the whole mission exists to remove, so it earns a named
test rather than a general "invalid input is refused".

### Parallel Opportunities

Independent of WP01 — it touches `naming.py` and nothing else. It can run concurrently.

### Dependencies

None.

### Risks & Mitigations

- **A second validator that nearly agrees with the first.** Mitigation: reuse
  `^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$` — already the rule for the left-hand side of the
  same address.
- **Breaking a running deployment.** Mitigation: T009. Validation is about *changing* a
  name, not about tolerating one already set.

---

## Work Package WP03: The descriptor, and an operator-gated write (Priority: P1)

**Goal**: let the hub say what it is, and let an operator change it — through the API,
because the API is where decisions live.
**Independent Test**: `GET /` on an unconfigured hub is indistinguishable from today's;
`PUT /hub` succeeds for an operator, is refused with an agent device token, returns `409`
for an environment-governed field and `422` for an invalid name.
**Prompt**: `tasks/WP03-descriptor-and-write-route.md`
**Requirement Refs**: FR-001, FR-008, FR-009, NFR-003

### Included Subtasks

- [ ] T011 Report `title` and `description` from `GET /` in `src/agent_inbox/api.py`, omitting them when unset rather than emitting empty strings (WP03)
- [ ] T012 Add `GET /hub/settings`, returning each field with its source and governing variable (WP03)
- [ ] T013 Add `PUT /hub`, gated on `provide_operator` exactly as `revoke_token` is (WP03)
- [ ] T014 Refuse with `409` when the requested field is fixed by the environment, naming the variable (WP03)
- [ ] T015 Refuse with `422` when the name fails validation, carrying WP02's message (WP03)
- [ ] T016 Test the gate with an agent device token, and each refusal's status code against `STATUS_BY_CODE` (WP03)
- [ ] T027 Assert NFR-003: changing `AGENT_INBOX_PUBLIC_URL` leaves `name` unchanged, and two addresses reaching one hub report the same `name` (WP03)

### Implementation Notes

Contract: `contracts/hub-settings.md`. The write is administrative, so ADR 0008 applies
directly — administration happens out of band, and nothing arriving in a mailbox can change
the mailbox. A hub's own name is the clearest case of that.

On an unauthenticating hub the console is already open and this changes nothing, which
matches how the console's `_gate` already behaves.

### Parallel Opportunities

T012 is a read and can be written alongside T011.

### Dependencies

WP01 (resolution and its source reporting), WP02 (the validator).

### Risks & Mitigations

- **A new error code defaulting to `500`.** `STATUS_BY_CODE.get(exc.code, 500)` has done
  this before in this repo, and the generic handler makes it look handled. Mitigation: T016
  asserts the status codes, and every new code is added to the map explicitly.
- **The console validating what the API does not.** Mitigation: refusals live in the route.
  A second client must not be able to write what the console would reject (ADR 0005).

---

## Work Package WP04: The Federation tab (Priority: P1)

**Goal**: somewhere to see and edit the three fields — and to be honest about which of them
the operator actually controls.
**Independent Test**: the tab renders three fields sourced from the API; with
`AGENT_INBOX_HUB_NAME` set, that field is disabled and names the variable; the page says
federation itself is not built yet.
**Prompt**: `tasks/WP04-federation-tab.md`
**Requirement Refs**: FR-005, FR-007

### Included Subtasks

- [ ] T017 Add a Federation tab and its navigation entry in `src/agent_inbox/console.py` (WP04)
- [ ] T018 Render the three fields from `GET /hub/settings`, not from values the console recomputes (WP04)
- [ ] T019 Render an environment-governed field disabled, saying so and naming the variable (WP04)
- [ ] T020 Submit through `PUT /hub`; surface a `409` or `422` to the operator rather than swallowing it (WP04)
- [ ] T021 Test the tab, the disabled rendering, and the placeholder notice in `tests/test_console.py` (WP04)

### Implementation Notes

The tab ships as a **placeholder for federation itself**, on the operator's instruction:
get the settings system working before the feature that needs it, and there are no
non-developer users to confuse. The page should say so plainly rather than implying
federation exists. Peers, modes and blocklists join it later —
`manual-activitypub-federation-v1-01KYJY10` FR-001 already plans that tab.

### Parallel Opportunities

Little within the package; the subtasks are sequential layers of one page.

### Dependencies

WP03.

### Risks & Mitigations

- **A disabled field that reads as broken.** A greyed box with no explanation looks like a
  bug; one that says `AGENT_INBOX_HUB_NAME` is set by this deployment reads as governed.
  Mitigation: T019 asserts the variable name appears in the rendering.
- **Offering a control that does nothing.** An editable field that silently loses its value
  on restart is the same family as a check that passes with nothing to look at, or a send
  that succeeds and reaches nobody. It looks like it worked.

---

## Work Package WP05: The federation gate, and the prompt (Priority: P2)

**Goal**: the rule that a hub called `local` cannot switch federation on, and letting an
arriving agent learn what the hub is.
**Independent Test**: enabling federation while named `local` is refused with a reason;
removing the rule makes a test fail; the prompt introduces the hub where title and
description are set and reads exactly as today where they are not.
**Prompt**: `tasks/WP05-federation-gate-and-prompt.md`
**Requirement Refs**: FR-006, FR-010

**Deferred with the switch**: the spec's *renaming back to `local` with federation on* row
is out of scope here and recorded as such in `spec.md`. This package ships no federation
state, so there is nothing for that rule to act on; it belongs to the mission that owns the
switch.

### Included Subtasks

- [ ] T022 Implement the gate in one place: federation cannot be *enabled* while `name` is `local`, and the refusal explains why (WP05)
- [ ] T023 Prove the gate's test by deleting the rule and watching the test fail — record the result (WP05)
- [ ] T024 Introduce the hub by `title` and `description` in `src/agent_inbox/prompts.py` where they are set (WP05)
- [ ] T025 Verify the prompt reads correctly when both are absent — that is every hub in existence today (WP05)
- [ ] T026 Update the README, the admin runbook, and this mission's record (WP05)
- [ ] T028 Run the outside-model review on the finished mission — one narrow question, `codex exec` under a hard alarm, findings reproduced before acting (WP05)

### Implementation Notes

The gate blocks *enabling the mode*, not merely *federating* — so a hub that has switched
federation on and not yet been named is not a reachable state. The refusal should be
self-explanatory at the moment it appears: a hub called "local" cannot be told apart from
every other hub called "local".

### Parallel Opportunities

T025 and T026 are independent of the gate work and of each other.

### Dependencies

WP02 (the name rule), WP04 (where the switch will live).

### Risks & Mitigations

- **A rule with nothing behind it.** There is no federation to gate yet — precisely the
  shape `AGENTS.md` warns about. Mitigation: T023. Ship the rule and a test that fails when
  the rule is removed, and leave the *switch* to the federation mission that will own it. A
  gate wired to nothing, with no test, is decoration someone will later believe.
- **The prompt asserting something untrue.** It is the most-read document in the project
  and has twice been caught doing exactly that. Mitigation: T025 treats the both-absent
  case as the common case, because it is.

---

## Suggested MVP scope

**WP01 + WP02.** Together they deliver the mission's actual claim — that a hub's identity
is a validated thing it keeps, rather than an address it happens to answer on — and they
carry the two risks worth being careful about. WP03 makes it visible, WP04 makes it
editable, WP05 puts it to work.
