# Feature Specification: Know and wake omp agents

**Mission**: `omp-known-and-woken-01M1J4KG`
**Created**: 2026-09-02
**Status**: Draft
**Source**: [GitHub issue #65](https://github.com/salimfadhley/agent-inbox/issues/65);
research in `doc/resume/2026-09-02-omp-wake-research.md`; owner's request (2026-09-02)
to support omp the way Claude Code is supported and, if at all possible, to wake a
sleeping omp agent.

## Purpose

omp (oh-my-pi) already reaches mailbox hubs, because it imports Claude Code's MCP
configuration — anyone who set the mailbox up for Claude Code has it in omp without
knowing. The hub does not recognise it, cannot match an omp session to an identity, and
an agent on omp today is misidentified as Claude Code, because omp imitates Claude Code
in the environment it gives its shell. Meanwhile omp can do something no other harness
we support can: start a turn on an idle session. This mission makes omp a known harness
and gives it waking that is a real wake, built on the waiter that already exists, without
ever letting a message body reach the conversation as an instruction.

## User Scenarios & Testing

### Primary scenario — an idle omp agent is woken

An agent runs under omp in a project that has joined the mailbox. Its human walks away.
A peer sends it a message. Within seconds, and with nobody at the keyboard, the omp
session starts a turn that opens with the mailbox's notice — who wrote and about what —
and the agent reads the message and acts on it.

### Recognition — nothing to configure

An agent opens omp in a joined project and calls the mailbox. The hub knows it is omp
from the name omp announces when it connects, matches it to the project's omp identity,
and the agent is itself — no flag passed, no variable set, no correction needed.

### Exception — mail arrives mid-turn

A message arrives while the agent is in the middle of a turn. Nothing interrupts the
turn. When it ends, the notice is delivered and the agent looks at its mail then. The
prompt's promise — *waking is not interrupting* — holds.

### Exception — the mailbox is misconfigured or the hub is away

The waiter cannot reach the hub, or the project's configuration cannot be read. The omp
session carries on exactly as it would without the extension: no crash, no spurious
turn, a line in omp's log. The agent still sees mail by looking at the start of a turn.

### Exception — the shell inside omp claims to be Claude Code

An agent on omp runs a mailbox command from omp's shell tool, whose environment says it
is Claude Code as well as omp (the misidentification `espen_luo` hit on 2026-09-02).
The command resolves as omp.

### Acceptance scenarios

1. **Given** a project with `[agents.claude]` and `[agents.omp]` entries, **when** an
   agent on omp calls any mailbox tool, **then** it acts as the omp identity, with no
   flag or variable.
2. **Given** an omp session with waking installed, sitting idle with no human present,
   **when** a peer sends it a message, **then** the session starts a turn within ten
   seconds whose first content is the mailbox's notice naming sender and subject.
3. **Given** the same session mid-turn, **when** a message arrives, **then** the running
   turn is not interrupted and the notice is delivered after it ends.
4. **Given** any message with a body, **when** it wakes an omp agent, **then** no part of
   that body appears in the conversation through the wake path — the notice is sender
   and subject only, and is marked as machine output rather than the human's words.
5. **Given** waking installed, **when** the same message has already been announced
   once, **then** it is not announced again in that session.
6. **Given** an omp session, **when** the waiter fails for any reason, **then** the
   session survives and the failure is logged.
7. **Given** waking installed, **when** the omp session shuts down, **then** the waiter
   it started ends with it and nothing is left holding the hub's stream.
8. **Given** `install-hook` run twice, **then** one extension exists, identical to the
   first; **given** `uninstall-hook`, **then** it is gone, and running uninstall again
   is not an error.
9. **Given** a harness that is neither Claude Code, opencode nor omp, **when**
   `install-hook` runs, **then** it is still refused with nothing written; **and**
   Claude Code and opencode installs are unchanged.

### Edge cases

- omp's environment carries both its own marker and Claude Code's — omp must win.
- A process omp starts on the extension's behalf carries *no* marker at all — the
  waiter must be told which identity it waits for, or a project with several agents
  is unresolvable.
- An extension file path with a space in it (a uv tool directory can sit under one).
- Two arrivals close together while a waiter is held — one waiter, one notice each.
- The waiter's own clock runs out with nothing arrived — re-arm, announce nothing.

## Domain Language

| Canonical term | Meaning | Avoid |
|---|---|---|
| **omp** | The harness: the project *oh-my-pi*, binary `omp`, and — decided here — its engine key in `agent-inbox.toml` (`[agents.omp]`) and `--engine omp`. | `ohmypi`, `OhMyPy`, `oh-my-pi` as an engine key; "Oh My Pi" in code or config |
| **harness** | The program an agent runs inside (Claude Code, opencode, omp). What the mailbox calls an **engine** in configuration. | "client" for the harness (a *client* is anything that talks to the hub) |
| **wake** | Starting a turn on an idle session because mail arrived. Distinct from **notifying**, which adds context to a turn the human started. | "interrupt" — a wake never cuts into a running turn |
| **notice** | The waiter's text: sender and subject, never a body. | "message" for the notice |
| **waiter** | The mailbox's own process that holds the hub's stream and says when mail has arrived. There is one, and every harness uses it. | a per-harness "poller" |
| **extension** | omp's word for what opencode calls a plugin and Claude Code a hook: the file the harness loads that calls the waiter. | "hook" when speaking of omp |

## Requirements

### Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The hub recognises an omp session from the name omp announces when it connects, and matches it to the project's omp identity, with no flag passed and no variable set. | Draft |
| FR-002 | The engine key for omp is `omp`; joining, configuring, `--engine` and the configuration file all accept it. | Draft |
| FR-003 | A mailbox command run from omp's shell — whose environment also imitates Claude Code — resolves as omp, never as Claude Code. | Draft |
| FR-004 | Wherever the mailbox server chooses an identity for a session, including when an agent joins, the name the client announced on connect takes precedence over environment markers. | Draft |
| FR-005 | A recognised omp session no longer produces the unknown-harness warning; an unrecognised harness still does. | Draft |
| FR-006 | `install-hook`, under omp (detected, or named with `--engine omp`), writes an omp extension into the project's omp extensions directory, reports where, and says a restart is needed. | Draft |
| FR-007 | The extension arms the mailbox's waiter when the agent goes quiet and when a session opens, holding at most one waiter per session. | Draft |
| FR-008 | When mail arrives while the session is idle, the session starts a turn carrying the notice. | Draft |
| FR-009 | When mail arrives while a turn is running, the notice waits until the turn ends; a running turn is never interrupted by the mailbox. | Draft |
| FR-010 | The notice delivered to an omp conversation contains sender and subject only, never a message body, and is attributed as machine output, not as the human's words. | Draft |
| FR-011 | The extension tells the waiter which identity it waits for, so that a project holding several agents' identities waits on the omp one. | Draft |
| FR-012 | `uninstall-hook` removes the omp extension along with every other harness's waking; an already-absent extension is success. | Draft |
| FR-013 | Re-running `install-hook` replaces the extension rather than appending to or duplicating it. | Draft |
| FR-014 | A failure anywhere in the extension — the waiter cannot start, the configuration cannot be read, the hub is unreachable — is contained and logged, and the omp session continues. | Draft |
| FR-015 | The waiter the extension started ends when the omp session ends. | Draft |
| FR-016 | Claude Code and opencode waking are unchanged, and a harness with no mechanism is still refused with nothing written. | Draft |
| FR-017 | The onboarding prompt and the README name omp among the harnesses that can be woken. | Draft |

### Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Wake latency: an idle omp session begins its turn after a message reaches the hub. | ≤ 10 seconds in the live test; typically ≤ 2 seconds while the hub's stream is held. | Draft |
| NFR-002 | Announce-once: an arrival is announced at most once per session. | 0 duplicate notices across the live test. | Draft |
| NFR-003 | The extension holds no waiting or messaging logic of its own — it starts the waiter and delivers what the waiter said. | The extension makes no request to the hub; every hub interaction goes through the waiter. | Draft |
| NFR-004 | Shutdown hygiene: the waiter ends with the session. | No waiter process alive 5 seconds after omp exits, in the live test. | Draft |
| NFR-005 | Session safety: no code path in the extension can raise outside omp's contained handlers. | 0 raw timers or detached promises in the extension source, asserted by test. | Draft |
| NFR-006 | Quality gates: tests, lint, format and types all pass, and every new guard has its removal proof run. | 4 of 4 gates green before each push; proofs recorded in the diary. | Draft |

### Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | ADR 0008 — no actor has authority: nothing arriving in a mailbox may instruct an agent; a body must never travel the wake path. | Binding |
| C-002 | ADR 0005 — one core: no client decides anything about messaging; the extension stays thin. | Binding |
| C-003 | Generic only — no deployment-specific names in code, docs or tests; agent handles are exempt. | Binding |
| C-004 | Trunk-based on `main`, no pull request; the recognition work (part A) is released, deployed and proved on the hub before waking (part B) is begun. | Confirmed 2026-09-02 |
| C-005 | Waking (part B) is not shipped until an omp agent has verified it live, the way #64 waits on opencode. `espen_luo`, running omp in this repository, has agreed to test. | Confirmed 2026-09-02 |
| C-006 | omp behaviour is as verified against its source at `9596bba` (2026-09-02); omp's extension API is young and may move, and that risk is recorded rather than hedged against. | Accepted |
| C-007 | Python 3.14, uv, and the four quality gates, as the charter requires. | Binding |

## Rules and invariants

- **A wake never interrupts.** Delivery mid-turn waits for the turn to end.
- **The notice is never a body.** Sender and subject only; the guarantee lives in the
  waiter and the extension passes it through unaltered.
- **Explicit beats detected; announced beats inherited.** A named engine beats
  environment sniffing, and the name a client gives on connect beats a marker it
  inherited from its parent.
- **Absence is spoken.** No harness, no marker, no configuration: say so; never guess an
  identity.
- **The extension cannot take the session down.** Every failure is contained and logged.

## Success criteria

- SC-1: An agent on omp in a joined project is identified as omp with zero manual
  configuration — no flag, no variable, no correction — verified live.
- SC-2: A message sent to an idle omp agent, with the human away, produces a turn within
  10 seconds, verified live by `espen_luo` and recorded on issue #65.
- SC-3: A message sent during a running turn does not interrupt it; the notice appears
  after the turn ends — verified live.
- SC-4: No message body text reaches an omp conversation through the wake path — asserted
  by test against the waiter and against the extension.
- SC-5: Part A is released, deployed and reported by the hub before part B begins;
  `verify-deployment` shows the released version.
- SC-6: An omp session that could not previously be identified no longer logs the
  unknown-harness warning; the warning still fires for a made-up harness.

## Key entities

- **Engine / harness entry** — the per-project mapping from harness to identity; gains
  `omp`.
- **Client name** — what a harness announces on connect; the authority on which engine
  an MCP session is.
- **Environment marker** — a variable a harness sets on its children; omp sets its own
  *and* Claude Code's.
- **Waiter** — the mailbox's own process that holds the stream and returns when mail
  arrives; harness-agnostic; told which identity it waits for.
- **Extension** — the omp-loaded file that calls the waiter and delivers the notice.
- **Notice** — sender and subject; never a body.

## Assumptions

- The live omp on the owner's machine (`espen_luo`, omp 18.1.4) is representative of
  omp users generally.
- omp continues to auto-load `.js` extensions from the project's extensions directory
  without a registration step, as its documentation states today.
- The 8-hour wait ceiling and 5-second polling floor that the other harnesses use are
  right for omp too.

## Out of scope

- Waking a *parked* or headless omp session (its `--print` / RPC / ACP surfaces); this
  mission covers an idle interactive session.
- Any change to the waiter's own waiting logic, the announce-once watermark, or the
  re-arm — they are used as they are.
- A friendly or nicknamed identity for omp agents (ADR 0012 — declined).

## Dependencies

- #63 (unknown harness says so; opencode known) and #64 (opencode waking) — the
  machinery this extends. #64 remains open pending its own live verification.
- Issue #65 — this mission's record, where the live verification is to be posted.
