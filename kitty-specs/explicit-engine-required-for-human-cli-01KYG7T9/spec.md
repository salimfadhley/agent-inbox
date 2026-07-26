# Spec — Explicit engine selection for human CLI use

## What this is

The CLI is used by two different callers:

- **An agent session**, where the surrounding client usually identifies the engine
  (`codex`, `claude`, etc.) and the CLI can safely select that engine's entry in
  `agent-mailbox.toml`.
- **A human shell**, where there may be no engine marker at all. In a repository with
  multiple configured agents, the CLI cannot know which project-scoped agent entry the
  human meant.

This mission makes that boundary explicit. A human shell may still inspect machine-wide
and project-wide configuration, and may still set machine-wide shared credentials. But
any command that acts as a project agent or writes project-scoped agent configuration must
either resolve the engine from the environment or receive it explicitly from the caller.

The explicit selector is **engine**, not hub-issued agent name. The local config is keyed
by engine (`[agents.codex]`, `[agents.claude]`); the hub-issued name is a value inside
that entry. Selecting by hub name would make the CLI reverse-map a mutable value when the
thing it actually writes is an engine slot.

## Problem

After shared tokens were introduced, `agent-inbox config list` could truthfully show a
machine-wide token while `agent-inbox doctor` from a plain shell still behaved as though
no usable credential existed. The immediate token bug is small: the diagnostic fallback
dropped the shared token when no engine identity was resolved. But the deeper user
experience issue is broader.

When a plain shell has no engine marker, the CLI has three bad choices:

- Guess a default entry, risking writes to the wrong agent.
- Use a synthetic `default` entry, creating config that no real agent owns.
- Refuse project-scoped agent actions until the caller names the target engine.

Only the third preserves the project invariant: every project-scoped identity and token
belongs to a concrete agent engine.

## Decision

The CLI gains an explicit engine selection path for human shell use.

Preferred spelling:

```bash
agent-inbox --engine codex doctor
agent-inbox --engine claude config set role host
agent-inbox --engine codex ping
```

If the command parser cannot support a root option cleanly, equivalent per-command
options are acceptable, but the user-facing concept remains `--engine`, not `--agent`.

`--agent` is intentionally not the primary name. In this codebase, "agent" often means
the hub actor (`pablo_fantomas` style), while the local config needs the engine slot
(`codex`, `claude`, etc.). The CLI should avoid overloading that term.

## Command behaviour

Commands fall into three groups.

### Machine-wide commands

These do not require an engine:

- `agent-inbox config --global set token ...`
- `agent-inbox config --global get token`
- `agent-inbox config --global list`
- `agent-inbox config --global unset token`
- `agent-inbox config --global path`

They write or read the machine-wide file only. A shared token admits the machine and is
not owned by a specific project agent.

### Inspection commands

These may run without an engine, but must be honest about what is unresolved:

- `agent-inbox config list`
- `agent-inbox config get hub`
- `agent-inbox config path`
- `agent-inbox doctor`

For `doctor`, the expected plain-shell behaviour in a multi-engine project is:

- report the project config path;
- report that no engine is selected;
- list configured engine keys when available;
- still check hub reachability;
- still send any available shared token to the hub's remote doctor route;
- stop before agent API calls with a clear "rerun with `--engine <engine>`" message.

The result should never say `token not presented` when a global token was actually sent,
and should never invite the user to mint a token when the blocking issue is unresolved
engine selection.

### Agent-acting and project-writing commands

These require a resolved engine from either environment detection or `--engine`:

- `join`
- `ping`
- `inbox`
- `send`
- `read`
- `reply`
- `agents`
- `whoami`
- `role`
- `hub`
- `config set name`
- `config set role`
- `config set token`
- `config unset name`
- `config unset role`
- `config unset token`

If no engine can be resolved and more than one project agent entry exists, the command
must fail before contacting the hub or writing files. The error must name the configured
engines and show the exact retry shape, for example:

```text
cannot tell which engine to use for this project.
Configured engines: claude, codex.
Rerun with:
  agent-inbox --engine codex <command>
```

If exactly one project agent entry exists and no engine marker is present, the CLI may
continue to use that single entry for backward compatibility. The command output should
still make the selected engine visible where identity is reported.

## User scenarios & testing

1. **Human sets a shared token.** In a plain shell with no engine marker, a human runs
   `agent-inbox config --global set token <secret>`. The token is written to the
   machine-wide file with private permissions. No project agent entry is created or
   modified.
2. **Human diagnoses a multi-agent project.** In a project with `[agents.codex]` and
   `[agents.claude]`, a plain-shell `agent-inbox doctor` checks hub reachability and the
   shared token, then stops with "no engine selected" and lists `codex` and `claude`.
3. **Human diagnoses as a specific agent.** The same shell runs
   `agent-inbox --engine codex doctor`; the CLI uses `[agents.codex]`, sends the shared
   token, pings as that actor, and reports the inbox count.
4. **Human attempts a project write without engine.** In a multi-agent project, a
   plain-shell `agent-inbox config set role host` fails before writing, names the
   configured engines, and tells the human to rerun with `--engine`.
5. **Agent session behaviour is unchanged.** Inside a Codex or Claude session, the CLI
   resolves the engine from the environment or MCP client context and existing commands
   keep working without explicit flags.
6. **Single-entry compatibility.** In a project with only `[agents.claude]`, a plain
   shell may continue to use that single entry, and `doctor` reports that `claude` was
   selected because it is the only configured engine.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The CLI provides an explicit engine selector named `--engine`, applicable to commands that need to resolve a project agent entry. | implemented |
| FR-002 | `load_config` and related config helpers can be called with an explicit engine and use it ahead of environment detection. Existing MCP behaviour, where the MCP server supplies the client engine, remains supported. | implemented |
| FR-003 | Project-scoped writes (`config set/unset` for `name`, `role`, or project token; `join`) refuse to run from an unresolved multi-engine shell. | implemented |
| FR-004 | Agent-acting commands refuse to run from an unresolved multi-engine shell before contacting the hub. | implemented |
| FR-005 | Machine-wide config commands remain engine-free and never create or mutate project agent entries. | implemented |
| FR-006 | `doctor` can run without an engine as a diagnostic: it checks configuration path, duplicate names, hub reachability, and credential status, including machine-wide shared tokens. | implemented |
| FR-007 | `doctor` distinguishes missing credentials from missing engine selection. If a shared token is present and accepted, the credentials line reports that instead of asking for a new token. | implemented |
| FR-008 | When engine selection is required, the error message lists configured engine keys and shows a concrete retry command using `--engine`. | implemented |
| FR-009 | If exactly one project agent entry exists and no engine marker is available, commands may use it as a compatibility fallback and report which engine was selected. | implemented |
| FR-010 | `config list` shows effective values with provenance without requiring engine selection; when project agent values cannot be resolved because multiple entries exist, it should show that ambiguity rather than silently omitting or inventing an entry. | implemented |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | No wrong-agent writes. | In tests, a plain shell in a multi-engine project cannot modify any `[agents.<engine>]` table unless `--engine` is supplied. | implemented |
| NFR-002 | Diagnostics remain useful before onboarding is complete. | `doctor` without engine still reaches the hub and remote doctor route when a hub URL is known. | implemented |
| NFR-003 | Existing agent sessions keep working. | Codex/Claude engine detection and MCP-supplied engine context continue to resolve the same entries as before. | implemented |
| NFR-004 | No deployment-specific facts enter the repo. | Tests and docs use generic hub URLs and fake names only; no real hostnames, tokens, or local operator identities. | implemented |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | Identity is per project and per engine; no machine-wide name or role is introduced. | accepted |
| C-002 | A shared token is a credential, not an identity; it stays valid without selecting an engine. | accepted |
| C-003 | The local project file remains keyed by engine. The mission does not re-key config by hub-issued actor name. | accepted |
| C-004 | The CLI and MCP server continue to delegate mailbox operations to the shared HTTP client and server API; no mailbox logic is duplicated in command parsing. | accepted |
| C-005 | No secrets are printed in full by `config list`, `doctor`, test output, or errors. | accepted |

## Key entities

- **Engine** — the local client family that owns one project config entry, such as `codex`
  or `claude`.
- **Agent actor name** — the hub-issued mailbox identity stored inside an engine entry.
- **Shared token** — a machine-wide bearer credential that authenticates the machine but
  does not select a project identity.
- **Resolved engine** — the engine chosen by explicit flag, MCP client context,
  environment detection, or the single-entry compatibility fallback.
- **Unresolved multi-engine shell** — a plain shell with no engine marker in a project file
  containing more than one agent entry.

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | A plain shell in a multi-engine project can set a global shared token, run `config list`, and run diagnostic `doctor` without creating or modifying any project agent entry. |
| SC-002 | The same shell cannot run `config set role host`, `join`, `ping`, or `send` until it supplies `--engine`. |
| SC-003 | `doctor` from that shell reports accepted shared credentials when the token is valid, then stops with an explicit engine-selection instruction. |
| SC-004 | `agent-inbox --engine codex doctor` uses the Codex project entry, sends the shared token, and reaches the normal API checks. |
| SC-005 | Existing Codex and Claude sessions do not need to change their command invocations. |

## Assumptions

- The finite engine keys currently used by the project (`codex`, `claude`, and similar)
  remain suitable local config keys.
- A root-level click option can be threaded through the command group cleanly; if not,
  per-command `--engine` flags are acceptable as long as the user-facing behaviour is
  consistent.
- Human shell use is primarily diagnostic and administrative; acting as an agent should
  be explicit.

## Out of scope (non-goals)

- Renaming hub-issued actors or changing the name reservation model.
- Re-keying `agent-mailbox.toml` by actor name.
- Changing the authentication model or token minting flow.
- Introducing a global default engine.
- Replacing environment-based engine detection for real agent sessions.

## Edge cases

- **No config file, global token present** → `doctor` can test hub only if a hub URL is
  supplied by flag, environment, or global config; it must not invent an identity.
- **Config file has a hub but no agent entries** → `doctor` checks hub and token, then
  points to `join --engine <engine>` or an equivalent explicit onboarding command.
- **Config file has duplicate actor names across engines** → duplicate-name diagnostics
  still run and remain separate from engine-selection diagnostics.
- **Explicit engine not present in the project file** → project-writing commands may create
  that entry only through the normal claim/write flow; agent-acting commands fail with a
  missing-entry diagnostic.
- **Explicit engine conflicts with detected engine** → the explicit flag wins, and output
  should make the selected engine visible.

## Implementation notes (nicole_ruzickova, 2026-07-26)

Implemented as a **root** option — `agent-inbox --engine codex doctor` — which the
assumptions allowed for but did not assume. click threads it through the group context
cleanly, so no per-command flags were needed and the concept stays singular. `join`
keeps its own `--engine` as well, since it predates this and reads naturally there; the
root option wins when both are given.

Three points where the spec left a choice and this is what was chosen:

- **The refusal happens before anything else.** `_resolve_engine` raises before a hub
  client is constructed, so an unresolved shell cannot contact the hub *or* touch a
  file. The test for FR-004 uses an unroutable hub deliberately: if the order were
  wrong the failure would be a timeout rather than a usage error.
- **The selection is reported, and how it was made.** `doctor` says `engine codex —
  named`, `— detected`, or `— the only one configured`. FR-009's fallback means the
  same command behaves differently as a project grows a second agent; saying which
  engine was chosen, and why, is what makes that legible when it changes.
- **Ambiguity is a value, not an omission.** `config list` shows
  `<ambiguous: claude, codex>` for name and role rather than dropping the rows, so a
  configured project is never reported as empty (FR-010).

Verified against the six user scenarios, including that a plain shell in a two-engine
project leaves `agent-mailbox.toml` byte-identical after a refused write (NFR-001).

### Edge cases (completed after the first release)

Two of the listed edge cases were shipped unfinished in 0.16.0 and are now done:

- **Explicit engine not present in the project file.** It fell through to the generic
  "no mailbox configuration — write agent-mailbox.toml in your project root", which
  tells someone to create a file that is open in front of them, for an engine they had
  just named. It is now its own error naming the configured engines and offering
  `join --engine <engine>`. Distinct from the unresolved case on purpose: there the
  caller said nothing and must choose; here they chose and the choice does not exist.
  Acting as a missing engine is refused, but *creating* one through `join` or
  `config set` stays allowed — otherwise a project could never gain a second agent.
- **A hub with no agent entries.** `doctor` suggested a bare `agent-inbox join`, which
  from an unresolved shell refuses for the same reason everything else does, sending
  the reader in a circle. It now suggests `join --engine <engine> --hub …` whenever no
  engine is resolved.
