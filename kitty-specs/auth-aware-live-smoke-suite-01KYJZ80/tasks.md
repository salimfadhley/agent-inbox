# Tasks — live smoke tests that know what kind of hub they are pointed at

Mission: `auth-aware-live-smoke-suite-01KYJZ80` · Branch: `main` ·
Spec: `spec.md` · Plan: `plan.md` · Model: `data-model.md`

## The defect, in one sentence

`tests/live/` has **no representation of what kind of hub it is talking to**, so the
answer is hardcoded as an assumption and every assertion inherits it. Pointed at a hub
that enforces authentication — which both of ours now do — most of the suite fails for
reasons that have nothing to do with the deployment being broken.

## What changed since this was specified

Written 2026-07-28; both open questions are now closed.

**Question 1 resolved in v0.23.0, and it guts the riskiest package.** The initial-password
log line is now a contract — `INITIAL_PASSWORD_LOG_PREFIX` is a named constant asserted by
`tests/test_auth_bootstrap.py` — *and* `AGENT_MAILBOX_ADMIN_PASSWORD` exists as a standing
low-security mode. All three facts verified in the code before starting, not taken from
the note. WP03 was a six-step chain (scrape password → fetch TOTP secret → compute a code
→ enrol → session → mint); CI can now set the variable on a throwaway hub and sign in
directly, removing five steps and the whole class of risk that made it the mission's most
dangerous work.

**Question 2 answers itself.** An override, not a second compose file — because the
compose file is part of what the smoke job validates, and a second one would mean the
thing under test is not the thing that ships.

## Subtask index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | The probe: fetch `GET /` once, expose the descriptor and mode | WP01 | |
| T002 | Every mode-dependent failure says which mode it assumed | WP01 | |
| T003 | `-k auth` selects the auth tests instead of deselecting all 11 | WP01 | [P] |
| T004 | Expected status codes derive from the mode, not from an assumption | WP02 | |
| T005 | Console copy assertions derive from the mode too | WP02 | |
| T006 | The honesty check: advertised `authenticated` vs what a route actually does | WP02 | |
| T007 | A run where everything skipped must not read as a pass | WP02 | |
| T008 | Unattended credential on an enforcing hub, from the environment only | WP03 | |
| T009 | The bootstrap is asserted, not merely used | WP03 | |
| T010 | `adminPasswordSet` means *not fully secured*, and is asserted when relied on | WP03 | |
| T011 | A second CI pass against an enforcing hub, via a compose override | WP04 | |
| T012 | The enforcing pass fails if it ends up running unauthenticated | WP04 | |
| T013 | Directive 4 — outside model review before the mission ships | WP04 | |

---

## WP01 — Mode detection, and making `-k auth` work

**Goal**: give the suite a premise. Nothing else in the mission can be done first.

**Independent test**: pointed at an open hub the fixture reports `open`; at an enforcing
hub, `enforcing`; with the hub unreachable the run stops naming the URL it tried.

- [x] T001 The probe: fetch `GET /` once, expose the descriptor and mode (WP01)
- [x] T002 Every mode-dependent failure says which mode it assumed (WP01)
- [x] T003 `-k auth` selects the auth tests instead of deselecting all 11 (WP01)

**Sketch**: a session-scoped fixture in `tests/live/conftest.py` holding a
`HubDescriptor` (`name`, `version`, `authenticated`, `note`) and a derived `AuthMode` of
`open` or `enforcing`.

**Risks**: **a failed probe must fail the run, never fall back to a default.** A default
is precisely the current bug, and it would then be invisible because the suite would look
like it was working. `warn` is deliberately not modelled — its caller-facing semantics are
an open question in another mission, and modelling it now encodes a guess.

**Dependencies**: none.

---

## WP02 — Assertions keyed to the mode, and the honesty check

**Goal**: every live assertion follows from the recorded mode rather than from a belief.

**Independent test**: the same suite passes against an open hub and an enforcing one,
with no test edited between the two runs.

- [x] T004 Expected status codes derive from the mode, not from an assumption (WP02)
- [x] T005 Console copy assertions derive from the mode too (WP02)
- [x] T006 The honesty check: advertised `authenticated` vs what a route actually does (WP02)
- [x] T007 A run where everything skipped must not read as a pass (WP02)

**Sketch**: replace hardcoded expectations with lookups keyed on the mode.

**Risks**: T006 is the requirement, not a nicety. **Only one direction is a failure** — a
hub advertising `authenticated: true` while a protected route answers unauthenticated is
broken; the reverse is a hub that is merely stricter than it admits. Asserting both would
fail honest deployments.

T007 is the shape this project keeps paying for: a suite that skipped everything and
reported green is a check that passed because it had nothing to look at.

**Dependencies**: WP01.

---

## WP03 — Unattended operator bootstrap

**Goal**: an enforcing hub the suite can actually authenticate against, with no secret in
the repository and none typed by a human.

**Independent test**: against a throwaway enforcing hub, the suite obtains a credential
and runs its authenticated assertions.

- [x] T008 Unattended credential on an enforcing hub, from the environment only (WP03)
- [x] T009 The bootstrap is asserted, not merely used (WP03)
- [x] T010 `adminPasswordSet` means *not fully secured*, and is asserted when relied on (WP03)

**Sketch**: `AGENT_MAILBOX_ADMIN_PASSWORD` on the throwaway hub, sign in, mint a token.
The log-scraping chain remains valid and is now contract-backed, so either route works —
prefer the variable, and say why in a comment.

**Risks**: T010 is the honesty clause on the shortcut. A hub running the low-security
admin override is **not** fully secured, and a suite that used the override while
reporting the hub as enforcing would be making exactly the false claim this mission
exists to stop.

**Dependencies**: WP01, WP02.

---

## WP04 — The second CI pass

**Goal**: CI runs the suite twice — against the open hub it already uses, and against one
started with `AGENT_MAILBOX_AUTH_MODE=enforce`. Both must pass.

**Independent test**: the workflow runs both passes and fails if either does.

- [ ] T011 A second CI pass against an enforcing hub, via a compose override (WP04)
- [ ] T012 The enforcing pass fails if it ends up running unauthenticated (WP04)
- [ ] T013 Directive 4 — outside model review before the mission ships (WP04)

**Sketch**: a compose **override**, not a second file (question 2). The enforcing pass
reuses the built image — no second build (NFR-003).

**Risks**: T012 is what stops the second pass being theatre. A credential that turns out
not to be needed would make the whole pass a duplicate of the first while appearing to
prove something new.

**Dependencies**: WP03.

---

## MVP scope

**WP01 + WP02 are the feature**: after them the suite tells the truth against either kind
of hub, which is the reported problem. WP03 and WP04 are what make it *stay* true without
a human pointing it at things.

## Parallelisation

One lane. T003 is marked `[P]` because it touches selection rather than assertions, but
the whole change is one directory and splitting it would cost more than it saves.

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 | T001 |
| FR-002 | T004, T005 |
| FR-003 | T006 |
| FR-004 | T003 |
| FR-005 | T008 |
| FR-006 | T007 |
| FR-007 | T011 |
| FR-008 | T008 |
| FR-009 | T009 |
| FR-010 | T012 |
| FR-011 | T010 |
| FR-012 | T010 |
| NFR-001 | T008 — and now enforced repo-wide by `tests/test_no_deployment_specifics.py` |
| NFR-002 | T002 |
| NFR-003 | T011 |
