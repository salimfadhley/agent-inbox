# Tasks: shared tokens only

**Mission**: `shared-tokens-only-01KYG7S7` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)
**Branch**: `main` · **Merges into**: `main`

## The shape of the work

Four packages, strictly sequential, because each one's surface is the previous one's
output: the service answers a new question, the API asks it, the console renders the
answer, and only then do the words describe it.

| WP | Goal | Depends on | Shippable alone |
|---|---|---|---|
| WP01 | The usage table, and one credential shape | — | Yes — invisible, but the whole foundation |
| WP02 | Three routes in, three out | WP01 | Yes |
| WP03 | One screen that lists tokens, not agents | WP02 | **Ships together with WP02** — see below |
| WP04 | The words follow the code | WP03 | Yes |

**WP04 must not lead.** Prose describing behaviour that has not shipped is a failure this
project keeps finding — a promise corrected in one file and left standing in another leaves
the reader with two answers.

**WP02 and WP03 ship as one release** (analysis finding A1). The console fetches
`/auth/agents/{name}/tokens` today; WP02 removes that route and WP03 repairs the console, so
releasing WP02 alone would leave the Tokens page broken on both deployed hubs until the next
release. The charter asks for small ships, and the smallest ship that is not broken is these
two together. The code is unchanged either way — only the release boundary moves.

## What is already there

Checked, not assumed. `auth_device_tokens` already carries `label`, `created`, `last_used`
and `revoked`. `resolve_token` already raises `TokenRevoked` before anything else.
`provide_caller` already takes the name from the header when the resolved caller is
`SHARED_ACTOR`. The console already mints, shows once, and copies.

So this mission adds one table, changes one function's return type, swaps three routes,
rewrites one screen, and corrects six files of prose.

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | `TokenUse` record and the `auth_token_use` table, both stores | WP01 | |
| T002 | Coarse recording: one write per token per minute, `last_used` folded in | WP01 | |
| T003 | `resolve_token` answers "is this credential good", not "who is this" | WP01 | |
| T004 | Minting takes a label and never an actor (`MintedToken.actor` goes); legacy bound rows keep working | WP01 | |
| T005 | Tests, starting with the lockout: a bound token still admits its agent | WP01 | |
| T006 | Directive 4 — outside review before WP01 closes | WP01 | |
| T007 | `POST /auth/tokens` — label required, refuses an empty one | WP02 | |
| T008 | `GET /auth/tokens` — every token, with `admitted` and `boundTo` | WP02 | |
| T009 | `DELETE /auth/tokens/{id}` — and the confirmation says what it cut off | WP02 | |
| T010 | The three `/auth/agents/{name}/tokens…` routes are removed | WP02 | |
| T011 | Tests: operator-only, shown once, revocation refuses on the next call | WP02 | [P] |
| T012 | Directive 4 — outside review before WP02 closes | WP02 | |
| T013 | `/tokens` lists every token on the hub | WP03 | |
| T014 | The mint form: a label and a button, and the label is required | WP03 | |
| T015 | Revoking says which agents it just cut off | WP03 | |
| T016 | `/tokens/{name}` and the Agents directory's Tokens column go away | WP03 | |
| T017 | Tests: the screen renders, the claim and the finding stay apart | WP03 | [P] |
| T018 | Directive 4 — outside review before WP03 closes | WP03 | |
| T019 | The served prompt stops describing a per-agent token | WP04 | |
| T020 | The prompt's doctor paragraph stops sending operators to `Agents -> you -> Tokens` | WP04 | |
| T021 | The MCP `join` tool's `token` parameter, and `README.md` | WP04 | [P] |
| T022 | FR-012: `doc/interrupting-an-agent.md` says what a shared token proves | WP04 | |
| T023 | Tests: no surviving sentence describes a token bound to one agent | WP04 | |
| T024 | Directive 4 — outside review before WP04 closes | WP04 | |

---

## WP01 — The usage table, and one credential shape

**Goal**: the hub records which agent each token admitted, cheaply and boundedly, and
`resolve_token` stops pretending a secret can name an agent.
**Independent test**: authenticate twice as two names with one token; both appear against
it with sensible first and last seen, and the second minute of traffic writes once.

- [x] T001 `TokenUse` record and the `auth_token_use` table, both stores (WP01)
- [x] T002 Coarse recording: one write per token per minute, `last_used` folded in (WP01)
- [x] T003 `resolve_token` answers "is this credential good", not "who is this" (WP01)
- [x] T004 Minting takes a label and never an actor, and `MintedToken` loses its `actor`; legacy bound rows keep working (WP01)
- [x] T005 Tests, starting with the lockout: a bound token still admits its agent (WP01)
- [x] T006 Directive 4 — outside review before WP01 closes (WP01)

**Risks**: this is the hot path. Every authenticated request passes through it, and the
mission puts an upsert there. The bucket must be checked *before* the write, not the write
made conditional afterwards. And revocation must stay the first thing that happens.

**Prompt**: [tasks/WP01-the-usage-table.md](tasks/WP01-the-usage-table.md)

---

## WP02 — Three routes in, three out

**Goal**: one operator-only API for tokens that never names an agent, and no surviving
route that can mint one bound to a single actor.
**Independent test**: `POST /auth/tokens` with no label is refused; with one it returns a
secret once; `GET` lists it with an empty `admitted`; `DELETE` revokes it.

- [ ] T007 `POST /auth/tokens` — label required, refuses an empty one (WP02)
- [ ] T008 `GET /auth/tokens` — every token, with `admitted` and `boundTo` (WP02)
- [ ] T009 `DELETE /auth/tokens/{id}` — and the confirmation says what it cut off (WP02)
- [ ] T010 The three `/auth/agents/{name}/tokens…` routes are removed (WP02)
- [ ] T011 Tests: operator-only, shown once, revocation refuses on the next call (WP02)
- [ ] T012 Directive 4 — outside review before WP02 closes (WP02)

**Risks**: removing routes is the irreversible half. Anything still calling them — the
console, tests, `doctor` — breaks at once rather than degrading, which is the right
failure but has to be found before release rather than after.

**Prompt**: [tasks/WP02-three-routes-in-three-out.md](tasks/WP02-three-routes-in-three-out.md)

---

## WP03 — One screen that lists tokens, not agents

**Goal**: the screen the mission exists for. Every token on the hub, with the one field
that makes it worth having — when it was last used — and the agents it has admitted.
**Independent test**: mint from the console; it appears with its label; an agent
authenticates; the agent's name appears against it; revoke; the row stays, marked.

- [ ] T013 `/tokens` lists every token on the hub (WP03)
- [ ] T014 The mint form: a label and a button, and the label is required (WP03)
- [ ] T015 Revoking says which agents it just cut off (WP03)
- [ ] T016 `/tokens/{name}` and the Agents directory's Tokens column go away (WP03)
- [ ] T017 Tests: the screen renders, the claim and the finding stay apart (WP03)
- [ ] T018 Directive 4 — outside review before WP03 closes (WP03)

**Risks**: FR-010. **Issued to** is a claim the operator typed; **Admitted** is what the
hub observed. Rendering them as one column is how somebody revokes the wrong credential,
and it is an easy mistake to make while making the table look tidy.

**Prompt**: [tasks/WP03-one-screen.md](tasks/WP03-one-screen.md)

---

## WP04 — The words follow the code

**Goal**: nothing anywhere still describes a token bound to one agent, and the interrupt
documentation says what a shared token actually proves.
**Independent test**: search the repository for the per-agent token story; every hit is
either corrected or is a dated record of what was true at the time.

- [ ] T019 The served prompt stops describing a per-agent token (WP04)
- [ ] T020 The prompt's doctor paragraph stops sending operators to `Agents -> you -> Tokens` (WP04)
- [ ] T021 The MCP `join` tool's `token` parameter, and `README.md` (WP04)
- [ ] T022 FR-012: `doc/interrupting-an-agent.md` says what a shared token proves (WP04)
- [ ] T023 Tests: no surviving sentence describes a token bound to one agent (WP04)
- [ ] T024 Directive 4 — outside review before WP04 closes (WP04)

**Risks**: T022 is the one with teeth. `v0.41.0` gates interruption on identity and refuses
when the hub does not authenticate. After this mission `authenticated` stays true while the
name behind it is header-supplied — so the check still separates "anyone on the network"
from "a machine the operator admitted", but it no longer separates one agent from another.
The code stays; the claim shrinks to what is true.

**Prompt**: [tasks/WP04-the-words-follow.md](tasks/WP04-the-words-follow.md)

## Requirement coverage

| FR | Where |
|---|---|
| FR-001 one Tokens screen | T013, T016 |
| FR-002 one mint form, label required | T007, T014 |
| FR-003 revoking is immediate and honest | T009, T015 |
| FR-004 the API | T007, T008, T009, T010 |
| FR-005 record which token admitted which agent | T001, T003 |
| FR-006 existing bound tokens keep working | T004, T005 |
| FR-007 the words follow the code | T019, T020, T021, T023 |
| FR-008 last used, with "never" distinct | T002, T013 |
| FR-009 recording is coarse | T002 |
| FR-010 claim and finding are separate columns | T013, T017 |
| FR-011 admitted history is bounded | T001 |
| FR-012 what a shared token proves | T022 |
