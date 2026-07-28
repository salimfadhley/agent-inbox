---
work_package_id: WP03
title: The descriptor, and an operator-gated write
dependencies:
- WP01
- WP02
requirement_refs:
- FR-001
- FR-008
- FR-009
- FR-011
- NFR-003
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/hub-identity
merge_target_branch: feat/hub-identity
branch_strategy: Planning artifacts for this mission were generated on feat/hub-identity. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/hub-identity unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
- T014
- T015
- T016
- T027
- T029
phase: Phase 2 - Surfaces
agent: python-pedro
history:
- at: '2026-07-28T14:17:34Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/api.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/api.py
- tests/test_api.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP03 – The descriptor, and an operator-gated write

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `python-pedro`
- **Role**: `implementer`
- **Agent/tool**: `python-pedro`

If no profile is specified, run `spec-kitty agent profile list` and select the best match
for this work package's `task_type` and `authoritative_surface`.

---

## Markdown Formatting

Wrap HTML/XML tags in backticks: `` `<div>` ``. Use language identifiers in code blocks.

---

## Objectives & Success Criteria

Let the hub say what it is, and let an operator change it — through the API, because the
API is where decisions live. ADR 0005: one API, every client is a client. The console is
not privileged; it will call these same routes in WP04.

Complete when:

- `GET /` carries `name`, `title` and `description`. Absent values are **absent**, not
  empty strings pretending to be values.
- A hub with nothing configured returns exactly what it returns today.
- `GET /hub/settings` reports each field with its source and, where governed, the variable.
- `PUT /hub` succeeds for an operator and is refused with an agent's device token.
- An environment-governed field returns `409`; an invalid name returns `422`. Both are in
  `STATUS_BY_CODE`, asserted.

## Context & Constraints

Read before starting:

- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/contracts/hub-settings.md` — the wire
  contract for all three routes; it is the authority here
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md` — FR-001, FR-008, FR-009
- `doc/decisions/0008-no-actor-has-authority.md`
- `doc/decisions/0005-one-api-every-client-is-a-client.md`

Constraints:

- **The write is administrative.** It hangs off `provide_operator`, exactly as
  `revoke_token` does. No agent credential may reach it. ADR 0008 is that administration
  happens out of band and nothing arriving in a mailbox can change the mailbox; a hub's own
  identity is the clearest case of that.
- **On an unauthenticating hub the console is already open**, and this changes nothing —
  which matches how the console's `_gate` already behaves. Do not invent a second security
  posture for this route.
- **Refusals live in the route.** A second client must not be able to write what the
  console would reject.

## Branch Strategy

- **Strategy**: Planning artifacts for this mission were generated on `main`. During
  `/spec-kitty.implement` this WP may branch from a dependency-specific base, but completed
  changes must merge back into `main` unless the human explicitly redirects the landing
  branch.
- **Planning base branch**: `main`
- **Merge target branch**: `main`

Execution worktrees are allocated per computed lane from `lanes.json`; do not create one by
hand. Assert the branch and `HEAD` before any commit.

Implementation command (depends on WP01 and WP02):

```bash
spec-kitty agent action implement WP03 --agent <name>
```

## Subtasks & Detailed Guidance

### T011 — `title` and `description` on `GET /`

- **Purpose**: the hub says what it is, not only how to authenticate to it.
- **Files**: `src/agent_inbox/api.py`
- **Steps**:
  1. Add both fields to the descriptor beside the existing `name`, `version`, `id`,
     `authenticated`, `note` and `policies`.
  2. **Omit them when unset.** Do not emit `"title": ""`. An empty string is a value someone
     chose; absence is the state of every hub today, and the two must stay distinguishable
     because the console renders them differently.
  3. Read through WP01's resolution. Do not read the environment directly here — there is
     one place that answers this question and it is not the API layer.
- **Regression guard**: a hub with nothing configured must produce a descriptor
  indistinguishable from today's in every existing field. Assert the whole payload, not just
  the new keys.

### T012 — `GET /hub/settings` `[P]`

- **Purpose**: the console needs value *and* provenance to render a field honestly.
- **Files**: `src/agent_inbox/api.py`
- **Steps**:
  1. Return each of the three fields as `{value, source, variable}` per
     `contracts/hub-settings.md`. `variable` appears only when `source` is `environment`.
  2. **Operator-gated**, as the contract states. The descriptor at `GET /` is public, but
     this route exposes *how the deployment is configured*, which is administrative — so it
     sits in `revoke_token`'s neighbourhood, behind `provide_operator`. This is settled; do
     not re-decide it. If you believe it is wrong, change the contract first and say why,
     because an unexplained exemption in this file has already had to be re-derived once.
  3. An unset `title` or `description` is `"value": null` with `"source": "default"` here,
     while `GET /` omits it entirely. The console needs to know the field exists and is
     unset; a reader of the descriptor does not. A field an operator deliberately cleared to
     `""` is `stored` with an empty value — that is what FR-009's "may be empty" means, and
     it must stay distinguishable from never-set.
  4. Never return the value of a secret. These three are not secrets, but the shape invites
     reuse; make it clear in the docstring that this route reports configuration, not
     credentials.
- **Parallel**: can be written alongside T011.

### T013 — `PUT /hub`, operator-gated

- **Purpose**: let an operator set the three values.
- **Files**: `src/agent_inbox/api.py`
- **Steps**:
  1. Accept a partial body — an operator setting only `description` must not have to resend
     `name`. Omitted keys are unchanged; explicit `null` clears (contract).
  2. Gate on `provide_operator`, copying `revoke_token`'s dependency rather than writing a
     new check.
  3. Write through WP01's store surface. **Never write the environment's value.** If a field
     is governed by the environment, refuse it (T014) rather than storing a copy — storing a
     copy is precisely the silent erasure WP01's T006 exists to prevent, arriving through a
     different door.
  4. Return the resolved state after the write, so a caller sees what actually took effect
     rather than what they asked for. These differ whenever the environment governs.

### T014 — `409` when the environment governs the field

- **Purpose**: refuse honestly rather than accepting a write that will never take effect.
- **Files**: `src/agent_inbox/api.py`
- **Steps**:
  1. If the request sets a field whose resolved source is `environment`, refuse with `409`
     and name the variable in the message.
  2. Add the error code to `STATUS_BY_CODE` explicitly. **This repo has shipped a code
     missing from that map**, where `STATUS_BY_CODE.get(exc.code, 500)` turned a clean `422`
     into a `500` and the generic handler made it look handled. Do not rely on the default.
  3. Accepting the write and quietly having no effect is the alternative, and it is the
     project's recurring defect shape: it looks like it worked.

### T015 — `422` when the name is invalid

- **Purpose**: the API is where the decision lives.
- **Files**: `src/agent_inbox/api.py`
- **Steps**:
  1. Call WP02's validator. Carry its message through to the response body — the operator
     needs to learn the rule, and re-wording it here would give two versions of the same
     rule.
  2. Add the code to `STATUS_BY_CODE`.
  3. Validate before writing anything. A partial write followed by a refusal leaves the hub
     in a state the operator did not ask for.

### T016 — API tests

- **Purpose**: prove the gate and the two refusals, and the no-change-for-existing-hubs
  claim.
- **Files**: `tests/test_api.py`
- **Steps**:
  1. `GET /` on an unconfigured hub — assert the full payload matches today's, and that
     `title` and `description` are absent rather than empty.
  2. `GET /` after setting all three — assert all three appear.
  3. `PUT /hub` as an operator — succeeds; the change persists; the response reports the
     resolved state.
  4. `PUT /hub` **with an agent device token** — refused. This is the ADR 0008 assertion and
     the most important test in the package. Mint a real device token for a real agent; do
     not fake the dependency, or the test proves only that a mock refuses.
  5. `PUT /hub` naming an environment-governed field — `409`, **asserted as `409` and not
     merely as "an error"**, with the variable named in the body.
  6. `PUT /hub` with `The Salt Club` — `422`, with WP02's message.
  7. `PUT /hub` on an unauthenticating hub — succeeds, matching `_gate`'s existing posture.
### T027 — Assert that identity survives the address

- **Purpose**: NFR-003, and the mission's headline claim. Untested, it is just a sentence.
- **Files**: `tests/test_api.py`
- **Steps**:
  1. Set a `name`, read `GET /`, then change `AGENT_INBOX_PUBLIC_URL` and read it again.
     `id` changes; `name` does not.
  2. Request the descriptor by two different addresses that reach the same hub, and assert
     both report the same `name`. This is the exact confusion that prompted the mission —
     two agents reaching one hub by different addresses and concluding they were on
     different hubs.
  3. Assert `name` is unchanged **in the store**, not merely in the response. An identity
     that survives a re-read but not a restart has not survived.
- **Why this is its own subtask**: NFR-003 was mapped to this package with nothing asserting
  it. A requirement whose only evidence is that someone believed it is the shape this
  project has learned to distrust.

- **Establish the premise**: in test 5, assert the field really is environment-governed
  before asserting the refusal. A `409` returned for the wrong reason passes an unexamined
  test.

### T029 — Refuse a write-back of an environment-sourced value

- **Purpose**: FR-011. The second door into the erasure that WP01's T006 closes at startup.
- **Files**: `src/agent_inbox/api.py`, `tests/test_api.py`
- **Steps**:
  1. `PUT /hub` must treat an omitted field as unchanged — never as "clear it". A client
     sending a partial body is the normal case, not an edge case.
  2. Refuse a write whose value the client cannot have authored: if the request carries the
     value currently resolved *from the environment*, refuse with `409` rather than storing
     it. The operator did not type it; a rendered form did.
  3. Test the sequence the reviewer gave: store a title, set the variable, resolve (the
     environment wins), remove the variable, then submit the environment's former value.
     **Assert the stored value is unchanged.** Assert the store, not the response.
- **Why**: found by outside review, 2026-07-28. Startup was guarded and this was not, so the
  invariant held everywhere except the one path an operator actually uses.

## Test Strategy

Litestar's `TestClient` against the app, as `tests/test_api.py` already does.

Assert **status codes**, not exception types. The `500`-instead-of-`422` defect in this
repo was invisible at the exception layer and obvious at the wire.

## Definition of Done

- [ ] `GET /` carries all three; absent values are absent.
- [ ] An unconfigured hub's descriptor is unchanged, asserted against the full payload.
- [ ] `GET /hub/settings` reports value, source and variable per the contract.
- [ ] `PUT /hub` is operator-gated, accepts partial bodies, and returns resolved state.
- [ ] `409` for environment-governed fields, naming the variable.
- [ ] `422` for an invalid name, carrying WP02's message.
- [ ] Both codes are in `STATUS_BY_CODE` explicitly.
- [ ] An agent device token cannot reach the write — asserted with a real token.
- [ ] Changing the public URL leaves `name` unchanged, in the response and in the store.
- [ ] Two addresses reaching one hub report the same `name`.
- [ ] All four charter gates pass: `uv run pytest`, `uv run ruff check`,
      `uv run ruff format --check`, `uv run pyright`.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A new code missing from `STATUS_BY_CODE` | Becomes a `500`; the generic handler hides it | T014/T015 add explicitly; T016 asserts codes |
| Storing a copy of the environment's value | Silent erasure through a second door | T013 step 3; refuse instead |
| Faking the operator dependency in tests | Proves a mock refuses, not that the gate holds | T016 step 4 uses a real device token |
| Validating only in the console | A second client writes what the console rejects | Refusals live in the route (ADR 0005) |
| Emitting `""` for unset fields | Console cannot distinguish unset from cleared | T011 step 2 |

## Reviewer Guidance

- Check the descriptor test asserts the whole payload. A test that checks only the new keys
  cannot see a regression in the old ones.
- Check the `409` test establishes that the field is governed before asserting the refusal.
- Remove the `provide_operator` dependency from `PUT /hub` and run the tests. If they pass,
  the gate is untested.
