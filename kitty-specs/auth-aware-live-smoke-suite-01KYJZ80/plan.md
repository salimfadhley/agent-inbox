# Implementation Plan: auth-aware live smoke suite

**Branch**: `main` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `kitty-specs/auth-aware-live-smoke-suite-01KYJZ80/spec.md`

## Summary

`tests/live/` assumes a hub with authentication off. Against an enforcing hub it produces
five failures that are all the hub behaving correctly, which trains operators to ignore
live validation — the damage is to the habit, not the run.

Make the suite read the hub's advertised auth mode from `GET /` and assert what is true
for the hub in front of it, then run it in CI **twice**: once against today's open compose
stack, once against an enforcing one that mints its own credential. The enforcing
configuration is what production runs and is currently untested anywhere.

## Technical Context

**Language/Version**: Python 3.12+ (project floor; CI matrix covers 3.12 and 3.13)
**Primary Dependencies**: pytest, httpx (already used by `tests/live`), Docker Compose for
the stack; `agent_mailbox.auth.totp` for computing enrolment codes
**Storage**: SQLite, owned by the hub container; created fresh per CI run and discarded
**Testing**: pytest against a running deployment, selected by `LIVE_HUB_URL` /
`LIVE_CONSOLE_URL`; skips when unset. No mocking — the point is the real image.
**Target Platform**: Linux containers (CI: `ubuntu-latest`); the same suite runs from a
developer machine against any hub
**Project Type**: single
**Performance Goals**: the second CI pass must not require a second image build
**Constraints**: no deployment hostnames in the repo (`AGENTS.md` generic-only rule); no
credentials in the repo or in CI secrets — the enforcing hub is created and destroyed
within the job
**Scale/Scope**: 11 existing live tests, one new conftest-level mode probe, one new CI step

## Charter Check

| Rule | Status |
|---|---|
| Generic only — no deployment hostnames, IPs, tokens or org names | **pass** — URLs come from environment variables; the CI hub is `localhost` |
| One core — no messaging logic outside `Mailbox` | **pass** — tests only; no product behaviour changes |
| No actor has authority (ADR 0008) | **pass** — the suite authenticates as an *operator* out of band, exactly as the ADR describes administration working |
| Establish the premise before asserting on it | **the whole point.** FR-010 exists so the enforcing pass cannot pass while unauthenticated |

No violations; Complexity Tracking is therefore empty.

## Project Structure

### Documentation (this mission)

```
kitty-specs/auth-aware-live-smoke-suite-01KYJZ80/
├── spec.md              # requirements and the decisions taken
├── plan.md              # this file
└── tasks/               # work packages (/spec-kitty.tasks output)
```

### Source Code (repository root)

```
tests/live/
├── conftest.py          # NEW — probes GET /, exposes the mode as a fixture,
│                        #   performs the operator bootstrap when a credential is needed
└── test_live_smoke.py   # MODIFIED — assertions keyed to the mode; auth tests renamed
                         #   so `-k auth` selects them

.github/workflows/ci.yml # MODIFIED — a second live pass against an enforcing hub
docker-compose.yml       # UNCHANGED — the enforcing hub is an environment override,
                         #   so one topology definition stays under test
```

**Structure Decision**: single project. Everything lands in `tests/live/` and the CI
workflow. No `src/` change is required, which is the strongest argument that this mission
is correctly scoped: it is a testing defect, not a product defect. The one thing that
would change that is open question 1 — if the human prefers a bootstrap environment
variable to reading the log line, this grows a product surface and a security review.

## Complexity Tracking

*No Charter Check violations. Nothing to justify.*

## Implementation Concern Map

### IC-01 — Mode detection

- **Purpose**: Establish, once per run, what kind of hub the suite is pointed at, so every
  later assertion has a premise instead of an assumption.
- **Relevant requirements**: FR-001, FR-002, NFR-002
- **Affected surfaces**: `tests/live/conftest.py`
- **Sequencing/depends-on**: none — everything else needs this
- **Risks**: If the probe itself fails it must stop the run with a clear message. A probe
  that silently defaults to "open" would reproduce the current failure with extra steps.

### IC-02 — Mode-keyed assertions

- **Purpose**: Express each existing live assertion against the detected mode, including
  the console copy case, which currently asserts a warning that is *correctly absent* on
  an authenticated hub.
- **Relevant requirements**: FR-002, FR-005, FR-006
- **Affected surfaces**: `tests/live/test_live_smoke.py`
- **Sequencing/depends-on**: IC-01
- **Risks**: The temptation is to skip the awkward cases under enforcement. A skip is not
  a pass — FR-006 exists to stop the suite quietly covering less than it appears to.

### IC-03 — The honesty check

- **Purpose**: Fail when a hub's advertised auth mode disagrees with its behaviour.
- **Relevant requirements**: FR-003
- **Affected surfaces**: `tests/live/test_live_smoke.py`
- **Sequencing/depends-on**: IC-01
- **Risks**: This is the one genuinely new assertion in the mission, and it covers a defect
  class nothing else does. It is also adjacent to
  `auth-mode-truthful-error-text-01KYJZ81`, which found the hub already contradicting
  itself in prose — cross-check the two rather than assuming they are unrelated.

### IC-04 — Test selection

- **Purpose**: Make `-k auth` select the auth cases instead of deselecting all 11.
- **Relevant requirements**: FR-004
- **Affected surfaces**: `tests/live/test_live_smoke.py`, possibly a pytest marker in
  `pyproject.toml`
- **Sequencing/depends-on**: none
- **Risks**: Trivial, and worth doing early — it makes every other concern easier to
  iterate on.

### IC-05 — Unattended operator bootstrap

- **Purpose**: Obtain a device token inside CI with no stored secret: read the first-run
  admin password from the container log, enrol, compute a TOTP code, mint a token.
- **Relevant requirements**: FR-008, FR-009
- **Affected surfaces**: `tests/live/conftest.py`, `.github/workflows/ci.yml`
- **Sequencing/depends-on**: IC-01
- **Risks**: The largest risk in the mission. It depends on a log line that is not a
  contract (open question 1), and it spans six steps of the auth flow, so a failure
  anywhere must name itself — FR-009 — or it will present as a baffling 401 in an
  unrelated test. Offsetting that: this is the only live exercise of the operator
  bootstrap that exists, and that path runs exactly once per deployment, when getting it
  wrong is most expensive.

### IC-06 — The second CI pass

- **Purpose**: Run the suite against an enforcing hub on every push, reusing the built
  image.
- **Relevant requirements**: FR-007, FR-010, NFR-003
- **Affected surfaces**: `.github/workflows/ci.yml`
- **Sequencing/depends-on**: IC-05
- **Risks**: FR-010 is the guard that matters. The plausible bad outcome is not a failing
  second pass — it is a *passing* one that never authenticated, which would add a green
  tick and no coverage. Verify by removing the credential and watching it fail, the same
  way the v0.22.0 regression tests were verified.
