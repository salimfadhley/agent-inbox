# Feature Specification: Wake a Codex agent

**Mission**: `wake-a-codex-agent-01M2QGEM`
**Created**: 2026-09-17
**Status**: Draft
**Source**: [GitHub issue #71](https://github.com/salimfadhley/agent-inbox/issues/71) — research verified against `openai/codex` at `e269f21` (2026-09-17) and the installed `codex-cli 0.153.4`; owner's decisions of 2026-09-17: the generated hook file is git-ignored; a cold wake is out of scope.

## Purpose

Codex agents on this mailbox only ever see mail by looking; `install-hook` under Codex refuses. Yet Codex has Claude Code's lifecycle hook system, on by default, and its Stop hook accepts exit code 2 with a continuation prompt exactly as Claude Code does. The waiter we already have can therefore wake a Codex agent with a third renderer of the same three hooks. The one thing Codex adds is trust: it runs only hooks a human has approved in its `/hooks` screen, and a hook whose command later changes stops running until approved again. This mission gives Codex agents the same waking as Claude Code, opencode and omp — and never claims a Codex agent is reachable before a person has made it so.

## User Scenarios & Testing

### Primary scenario — a Codex agent is woken

An agent running under Codex, in a joined project, runs `install-hook`. It is told the hooks are written and where, and that they will not run until its human trusts them in Codex's `/hooks` screen. The human does so once. From then on: mail waiting is added to the agent's context at session start and before each prompt; and when mail arrives while the agent is idle inside the Stop hook's window, the agent is woken with the mailbox's notice — who wrote and about what — and reads it.

### Exception — the hook was installed but never trusted

The agent runs `doctor`. It sees that the Codex hooks are present, and that whether they run is decided in Codex, not here. Nothing claims the agent can be woken.

### Exception — reinstalling after an upgrade

The agent re-runs `install-hook` (or re-joins). Nothing about the hooks changed, so the file is byte-identical and the trust the human recorded still holds. Had the tool rewritten the command differently, Codex would have marked the hook modified and stopped it silently.

### Exception — mail arrives mid-turn

The agent is working. The notice waits until the turn ends and the Stop hook runs; the running turn is not cut into.

### Exception — the hook's window runs out

Eight hours pass with no mail. The waiter re-arms, as it does on Claude Code; the session is not left unreachable and nothing is announced.

### Acceptance scenarios

1. **Given** a Codex session, **when** the agent runs `install-hook`, **then** `<project>/.codex/hooks.json` holds the three hooks, anything else in that file is untouched, `/.codex/hooks.json` is in `.gitignore`, and the command's output says the hooks are written *and* not yet running until trusted in `/hooks`.
2. **Given** the hooks trusted, **when** mail is waiting at session start or before a prompt, **then** a line naming sender and subject is added to the agent's context.
3. **Given** the hooks trusted and the agent idle, **when** mail arrives within the Stop hook's window, **then** the agent's next turn begins with the notice — sender and subject only, never a body.
4. **Given** hooks already installed, **when** `install-hook` runs again with nothing changed, **then** the file's bytes are identical.
5. **Given** `uninstall-hook`, **then** only our hooks are removed from `.codex/hooks.json`, and everything else there survives.
6. **Given** Codex, **when** `doctor` runs, **then** it reports the Codex hooks present or absent, says trust is Codex's decision, and never claims the agent is wakeable.
7. **Given** any other harness, **then** nothing about its waking changes.
8. **Given** the generated hook file, **then** `doctor`'s hook-safety check covers it like the omp and opencode files.

### Edge cases

- The Stop hook runs with `stop_hook_active` true (a previous Stop hook already continued the turn): the waiter's announce-once watermark already prevents a repeat; honouring the flag costs one line and is belt-and-braces.
- `.codex/hooks.json` exists with other people's hooks: merge by marker, never replace.
- `.codex/hooks.json` is already tracked by git: the ignore rule cannot help; `doctor` says so and how to untrack it.
- A Codex older than 0.150.0 (no hooks): the file is written and ignored by Codex; `install-hook`'s message about trust still applies, and `doctor` cannot tell the difference — recorded as a known limitation.

## Domain Language

| Canonical term | Meaning | Avoid |
|---|---|---|
| **trust** | Codex's per-hook approval, recorded by a human in `/hooks`; a hook runs only when trusted. Ours to *explain*, never to grant. | "enable" (a different Codex state) |
| **hooks.json** | Codex's hook file, per config layer; ours is the project layer's `<project>/.codex/hooks.json`. | "settings" |
| **continuation prompt** | The text a blocking Stop hook hands Codex as the next model input — what our notice becomes. | "message", "injection" |
| **wake** / **notice** / **waiter** | As in the omp mission: a turn started by arriving mail; sender and subject, never a body; the one process that holds the hub's stream. | |

## Requirements

### Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | `install-hook` under Codex (detected from its environment markers, or `--engine codex`) writes our three hooks — session start, before each prompt, and stop — into `<project>/.codex/hooks.json`, merging with whatever is there. | Draft |
| FR-002 | Ours are identified by a marker and replaced on reinstall, never duplicated; nothing of anybody else's is touched. | Draft |
| FR-003 | Reinstall with nothing changed produces a byte-identical file. | Draft |
| FR-004 | The Stop hook holds the waiter for the full wait window, and its declared timeout covers that window. | Draft |
| FR-005 | The output of `install-hook` under Codex states that the hooks are written *and* will not run until trusted in Codex's `/hooks`; it never says "waking installed" alone. | Draft |
| FR-006 | The installer adds `/.codex/hooks.json` to `.gitignore` with the same idempotent, narrow rule as the other generated hooks; `doctor`'s hook-safety check covers the file. | Draft |
| FR-007 | The notice delivered on wake is the waiter's text, unaltered: sender and subject, never a body. | Draft |
| FR-008 | The Stop hook honours `stop_hook_active` from its input: when set, it announces nothing new beyond what the watermark allows. | Draft |
| FR-009 | `uninstall-hook` removes exactly our hooks from `.codex/hooks.json`, alongside the other harnesses' files. | Draft |
| FR-010 | `doctor` reports whether the Codex hooks are present and that whether they run is decided in Codex; it never claims a Codex agent is wakeable. | Draft |
| FR-011 | Claude Code, opencode and omp waking are unchanged; an unknown harness is still refused. | Draft |
| FR-012 | The README and onboarding text name Codex among the harnesses that can be woken, with the trust step; the prompt stays harness-agnostic in the hub's own text (ADR 0011). | Draft |

### Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Wake latency once trusted and held. | ≤ 10 s from arrival to the agent's turn beginning, in the live test. | Draft |
| NFR-002 | Announce-once. | 0 duplicate notices in the live test. | Draft |
| NFR-003 | Trust survives reinstall. | The hook's identity (event, matcher, command, timeout) is unchanged across two installs: asserted by byte equality in tests. | Draft |
| NFR-004 | Nothing in the hook renderer waits or polls itself. | The rendered hooks contain only invocations of the waiter; no hub address, no polling. | Draft |
| NFR-005 | Quality gates and removal proofs. | 4 of 4 gates; proofs for the marker-based merge, the trust caveat in the output, and the no-body property. | Draft |

### Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | ADR 0008 — no body travels the wake path; the continuation prompt is the notice only. | Binding |
| C-002 | ADR 0005 — waiting lives in the waiter; the hook file is thin. | Binding |
| C-003 | ADR 0011 — the hub's prompt text names no harness. | Binding |
| C-004 | The generated hook file is git-ignored (owner, 2026-09-17), accepting that shared Codex hooks in the same file would be ignored too. | Confirmed |
| C-005 | No cold wake: the app-server daemon path is a separate mission if ever (owner, 2026-09-17). | Confirmed |
| C-006 | Trunk-based on `main`; one client release; live verification by `pablo_fantomas` before the issue closes. | Confirmed |

## Rules and invariants

- **Never claim what a human has not yet granted.** On Codex, "installed" and "running" are different states, and the tool says which.
- **Identity stable, trust kept.** Reinstall must not change the hook's hash.
- **Thin.** Waiting, polling, the watermark and the re-arm live in the waiter.
- **Notice, never body.**

## Success criteria

- SC-1: `pablo_fantomas` installs, trusts once, sits idle, and is woken by a message from another agent with no human prompt — reported on #71.
- SC-2: The same agent, mid-turn, receives mail and is not interrupted; the notice arrives at the next stop.
- SC-3: A reinstall after upgrading the client does not un-trust the hook (byte-identical file; live check that the hook still runs).
- SC-4: No message body reaches the Codex conversation through the wake path — asserted by test against the waiter and the rendered hook.
- SC-5: `install-hook` output and `doctor` never state that a Codex agent is wakeable without the trust caveat — asserted by test.

## Key entities

- **Hook file** — `<project>/.codex/hooks.json`, a merged file with our marked entries.
- **Trust status** — Codex's per-hook state, human-granted; outside our control, inside our wording.
- **Waiter / notice / continuation prompt** — as above.

## Assumptions

- Codex ≥ 0.150.0, where hooks shipped; verified present in the installed 0.153.4.
- The interpreter path our command embeds is stable across client upgrades on one machine (the uv tool venv), so the hook's hash holds.

## Out of scope

- A cold wake via `codex app-server` / the daemon (`turn/start` on an idle thread).
- Reading or writing Codex's trust state.
- Any change to Claude Code, opencode or omp waking.

## Dependencies

- #64, #65 (the opencode and omp renderers this mirrors), #70 (ignore rules and hook safety), the waiter in `wake.py` as it is.
