# Implementation Plan: a hub has a name of its own

**Branch**: `main` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md`

## Summary

Give the hub an identity that is not an address. Add `name`, `title` and `description`;
persist them; let the console edit them; keep the environment authoritative where it
speaks; and gate federation on the hub having a name that is not `local`.

The work divides along a natural seam: **storage and precedence first**, because
everything else reads through them, then validation, then the two surfaces that expose
them.

## Technical Context

**Language/Version**: Python 3.12+ (CI matrix covers 3.12 and 3.13)
**Primary Dependencies**: `aiosqlite` for the store, Litestar for the API and console,
Click for the CLI. No new dependency — this is the first hub-level state the hub keeps
about itself, and it lives beside the mail.
**Storage**: the existing SQLite file. Three tables today — `actors`, `objects`, `reads`
— so this adds one. No new mount: the volume the mail lives on is already there, which is
what makes `serve.py`'s "anything else would need mounting" objection inapplicable.
**Testing**: pytest against both the in-memory and SQLite stores, as the store contract
tests already do; Litestar's `TestClient` for the API and console.
**Target Platform**: the hub container; the console sidecar reads through the API.
**Project Type**: single
**Performance Goals**: none specific — three values read at startup and on `GET /`, never
on the mail path.
**Constraints**: environment always wins (the container contract, `serve.py`); no
deployment-specific values in the repo (`AGENTS.md`); editing is operator-gated where the
hub authenticates (ADR 0008); `name` must satisfy the addressing parser, which splits on
`@`.
**Scale/Scope**: three fields, one table, one new console tab, one new API surface.

## Charter Check

| Rule | Status |
|---|---|
| Generic only — no deployment hostnames or org names in the repo | **pass** — the values are *configured*, never defaulted to anything naming a machine; `local` is deliberately meaningless |
| One core — no messaging logic outside `Mailbox`, no client deciding | **pass** — the console reads and writes through the API; validation lives with the hub, not the client (ADR 0005) |
| No actor has authority (ADR 0008) | **pass** — editing is operator-gated, out of band, exactly as `revoke_token` is. No message can change a hub's name |
| Identity is a surrogate key (ADR 0003) | **the point of the mission** — it applies that ADR's own argument one level up |
| Establish the premise before asserting on it | see NFR-002 and the test matrix: an upgrade with nothing configured must behave *exactly* as today, asserted rather than assumed |

No violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this mission)

```
kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/
├── spec.md              # requirements; no open questions
├── plan.md              # this file
└── tasks/               # work packages
```

### Source Code (repository root)

```
src/agent_inbox/
├── sqlite_store.py      # MODIFIED — a settings table, the first hub-level state
├── store.py             # MODIFIED — the same on the in-memory store; contract tests cover both
├── serve.py             # MODIFIED — precedence: environment over stored, and which won
├── naming.py            # MODIFIED — hub-name validation, reusing the agent-name rule
├── api.py               # MODIFIED — title/description on GET /; an operator-gated write
└── console.py           # MODIFIED — a Federation tab; env-fixed fields disabled

tests/
├── test_store_contract.py   # MODIFIED — settings behave the same on both stores
├── test_hub_settings.py     # NEW — precedence, including unset-after-override
├── test_api.py              # MODIFIED — descriptor fields, operator gating
└── test_console.py          # MODIFIED — the tab, and the disabled-field rendering
```

**Structure Decision**: single project, no new modules. Hub settings are a property of the
hub, so they belong in the store the hub already owns rather than in a new component.

## Complexity Tracking

*No Charter Check violations. Nothing to justify.*

## Implementation Concern Map

### IC-01 — Settings storage

- **Purpose**: give the hub somewhere to keep three values about itself, on both store
  implementations, so the existing contract tests cover it.
- **Relevant requirements**: FR-003, NFR-001
- **Affected surfaces**: `sqlite_store.py`, `store.py`, `test_store_contract.py`
- **Sequencing/depends-on**: none — everything else reads through it
- **Risks**: a schema addition to a store holding live mail. The migration must be
  additive and must not touch existing tables. An upgraded hub with no settings row is the
  normal case, not an error.

### IC-02 — Precedence, and reporting which source won

- **Purpose**: environment over stored, always; and the ability to say *which*, because
  the console cannot render a disabled field without knowing.
- **Relevant requirements**: FR-004, FR-005
- **Affected surfaces**: `serve.py`, `test_hub_settings.py`
- **Sequencing/depends-on**: IC-01
- **Risks**: **the one that matters.** Overriding must not erase. An operator who sets an
  environment variable, restarts, then unsets it must get their configured value back — if
  the stored value is overwritten at startup by whatever the environment said, that is
  silent data loss that looks exactly like it worked. Assert it directly.

  The CLI's `effective_settings()` already returns `(value, source)` for client config and
  is the pattern to copy rather than invent.

### IC-03 — Hub-name validation

- **Purpose**: make `name` an address component rather than free text.
- **Relevant requirements**: FR-002, FR-006
- **Affected surfaces**: `naming.py`
- **Sequencing/depends-on**: none
- **Risks**: reuse the agent-name rule rather than writing a second one — two validators
  that nearly agree is worse than one. The current state is not merely lax: `trevor@The
  Salt Club` parses today into `trevor@the salt club`, and `hub.thesaltclub.xyz` is
  accepted as a *name*, which is the exact conflation being removed. An existing hub may
  already hold a name that would now be refused; validation applies to **writes**, and a
  running hub must not fail to start because of it.

### IC-04 — The descriptor and the write route

- **Purpose**: `GET /` reports title and description; an operator can change all three.
- **Relevant requirements**: FR-001, FR-008, FR-009
- **Affected surfaces**: `api.py`, `test_api.py`
- **Sequencing/depends-on**: IC-01, IC-02, IC-03
- **Risks**: the write is administrative, so it is operator-gated like `revoke_token`
  (ADR 0008) — never reachable with an agent credential. On an unauthenticating hub the
  console is already open and this changes nothing, matching how `_gate` already behaves.

### IC-05 — The Federation tab

- **Purpose**: somewhere to see and edit them, with environment-fixed fields shown but not
  offered.
- **Relevant requirements**: FR-005, FR-007
- **Affected surfaces**: `console.py`, `test_console.py`
- **Sequencing/depends-on**: IC-04
- **Risks**: a disabled field must say *why* and name the variable, or it reads as broken
  rather than as governed. The tab ships as a placeholder for federation itself — a
  deliberate choice, and the page should say so rather than implying federation exists.

### IC-06 — The federation gate

- **Purpose**: federation cannot be **enabled** while the hub is called `local`.
- **Relevant requirements**: FR-006
- **Affected surfaces**: `console.py`, `api.py`
- **Sequencing/depends-on**: IC-03, IC-05
- **Risks**: there is no federation to gate yet, so this is a rule with nothing behind it
  — precisely the shape `AGENTS.md` warns about. Whatever ships must be exercised by a
  test that fails if the gate is removed, or it is decoration that will be believed later.
  Strongly consider shipping only the **rule and its test** here, and leaving the
  mechanism to the federation mission that will own the switch.

### IC-07 — The prompt introduces the hub

- **Purpose**: an arriving agent learns what the place is, not only how it authenticates.
- **Relevant requirements**: FR-010
- **Affected surfaces**: `prompts.py`, `test_console.py`
- **Sequencing/depends-on**: IC-04
- **Risks**: the prompt is the most-read document here and has twice been found asserting
  something untrue. Title and description are optional, so the wording must read correctly
  when both are absent — which is every hub today.
