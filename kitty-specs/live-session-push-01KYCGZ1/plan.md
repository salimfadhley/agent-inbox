# Implementation Plan: Push mail into a live session

## Summary

Deliver a **client-side wake** so an agent notices new mail without a human relay, without
polling-as-a-tool, and without blocking. The evidenced decision (see `research.md`) is to
**build the hook-based wake now and defer Channels** (a gated research preview). The wake is
three Claude Code hooks — SessionStart, UserPromptSubmit, and Stop — each running a fast,
fail-silent `agent-mailbox wake-check`. The hub is **not touched**: it already exposes
`check_inbox`/unread, and every wake mechanism is a client-side adapter (charter). A local
watermark makes each message announced exactly once.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: none new — the wake is stdlib-only client code reusing the existing
`HubClient.check_inbox`. No hub dependency and no `mcp`/`clients`-extra dependency for the
hook command itself (it must run fast from a bare `agent-mailbox` install).
**Testing**: pytest at the command level — given a mocked hub response and a watermark file,
assert the exit code, the stdout JSON (`hookSpecificOutput.additionalContext`) or the stderr
notice, and that announce-once holds. `.claude/settings.json` merge/idempotency/uninstall
tested against a temp dir. No live Claude Code session is required for the unit tests.
**Target Platform**: the agent's own machine (a local CLI), any OS Claude Code runs on.
**Constraints**: hub unchanged (harness-agnostic); no blocking; fail-silent (never break or
slow a turn); message bodies never injected as instructions.
**Scale/Scope**: one wake-check invocation per hook fire; a handful of unread rows.

## Charter Check

- **Harness-agnostic hub (C-001, NFR-001).** Nothing in `src/agent_mailbox` outside the
  client references Claude Code, hooks, or channels. A structural test enforces it.
- **No blocking (C-002, NFR-003; mission 0003).** `wake-check` is a fast one-shot; it never
  waits for mail. The Stop-hook exit-2 continues an *already-finishing* turn; it does not
  suspend the agent waiting.
- **Untrusted input (DIR-001, C-004).** The wake carries sender+subject+id and says
  "check_inbox"; it never injects a body as instructions.
- **No secrets/hostnames in the repo (DIR-001).** Config/identity come from
  `agent-mailbox.toml`; nothing deployment-specific is written.
- No charter violations → Complexity Tracking omitted.

## Project Structure

```
src/agent_mailbox/
  wake.py            # NEW — wake-check logic: unread → notice, watermark, per-event output
  hookconfig.py      # NEW — read/merge/remove hooks in .claude/settings.json (pure, testable)
  cli.py             # + `wake-check`, `install-hook`, `uninstall-hook` modes
doc/decisions/0011-wake-is-a-client-side-hook.md   # the ADR (channels deferred)
tests/
  test_wake.py       # command logic: exit codes, additionalContext, stderr, announce-once
  test_hookconfig.py # settings.json merge / idempotency / uninstall / no-clobber
```

## Design decisions (resolved)

1. **Client-side only; hub untouched.** The wake reads `check_inbox` (existing). No new hub
   route, no server push. This is the charter's harness-agnostic rule and closes NFR-001 by
   construction (plus a structural test).
2. **One command, event-aware:** `agent-mailbox wake-check --event <SessionStart|
   UserPromptSubmit|Stop>`.
   - **SessionStart / UserPromptSubmit** → if there is new mail, print
     `{"hookSpecificOutput":{"hookEventName":…,"additionalContext":"📬 …"}}` and exit 0;
     else print nothing, exit 0.
   - **Stop** → if there is *new* (unannounced) mail, print the notice to **stderr** and
     **exit 2** (Claude Code continues the turn so the agent processes it); else exit 0.
3. **Announce-once via a watermark.** A small JSON state file (last-announced message ids)
   in the project root (e.g. `.agent-mailbox-seen.json`). Each message is announced once, so
   the Stop-hook exit-2 fires once per new message and cannot loop. Silent when nothing new.
4. **Fail-silent, fast.** A short hub timeout; any error, hub-down, or unconfigured state →
   no output, exit 0. A wake must never break, block, or noticeably slow a turn (NFR-004).
5. **Notice format.** Terse, capped: `📬 2 new: jed_smith 'flaky tests', host 'welcome' —
   call check_inbox to read.` Sender + subject + implicit id; never the body (C-004/FR-005).
   Sender is the hub's authenticated `attributedTo`.
6. **Install/uninstall.** `agent-mailbox install-hook` writes the three hook entries into
   `.claude/settings.json` (project scope), **merging** existing hooks (never clobbering),
   idempotent; `uninstall-hook` removes exactly ours. Reads `agent-mailbox.toml` for
   identity — one install, one config, one identity (builds on mission 0014).
7. **asyncRewake (true idle wake) is opt-in, not core.** `install-hook --rewake` can add the
   `async`/`asyncRewake` options to the Stop hook, but its end-to-end behaviour needs a live
   session to verify, so the shipped, tested core is the three synchronous hooks.

## Charter Check (post-design)

Still clean: no hub change, no new dependency, no deployment specifics, one config file,
fail-silent by construction. A structural test asserts the hub/engine never import or name
the wake/hooks/channels.

## Implementation Concern Map

### IC-01 — Wake-check logic
- **Purpose**: turn "unread for me" into a per-event hook response, announced once.
- **Requirements**: FR-001, FR-005, FR-007, FR-008, NFR-003, NFR-004, NFR-005.
- **Surfaces**: `src/agent_mailbox/wake.py`, `tests/test_wake.py`.
- **Depends-on**: none (reuses `HubClient.check_inbox`).
- **Risks**: fail-silence must be total (a raised exception in a Stop hook must still exit 0,
  never 2); announce-once must be robust to a corrupt/missing watermark.

### IC-02 — Hook install/uninstall
- **Purpose**: write/remove the three hooks in `.claude/settings.json` safely.
- **Requirements**: FR-002, FR-009.
- **Surfaces**: `src/agent_mailbox/hookconfig.py`, `cli.py`, `tests/test_hookconfig.py`.
- **Depends-on**: IC-01 (installs commands that call it).
- **Risks**: JSON merge must never clobber a user's existing hooks; idempotent re-install;
  uninstall removes only ours.

### IC-03 — Decision, ADR, and the harness-agnostic guard
- **Purpose**: record the evidenced Channels decision (ADR 0011) and enforce the
  harness-agnostic boundary with a structural test.
- **Requirements**: FR-006, FR-010, FR-011, NFR-001, SC-006, SC-007.
- **Surfaces**: `doc/decisions/0011-wake-is-a-client-side-hook.md`, a structural test.
- **Depends-on**: none.
- **Risks**: keeping the guard honest (assert the hub/engine modules never name wake/hook/
  channel).
