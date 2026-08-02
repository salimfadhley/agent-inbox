# ADR 0011 — The wake is a client-side hook; Channels are deferred

- Status: Accepted
- Date: 2026-07-25
- Context: `agent-mailbox` — getting an agent's attention without polling or a human relay
- Related: [ADR 0005](0005-one-api-every-client-is-a-client.md), mission 0003 (blocking
  cancelled), mission 0017 (this)

## Context

Agents are pull-only: they see mail only when they look, so today a human relays "go check
your inbox." We want the agent to notice new mail the moment it is next active. Two rules
constrain any answer: **no blocking** (mission 0003 cancelled a blocking `check_mailbox`; the
competitive survey confirmed it — postal-mcp shipped it and its author reports Claude Code
"doesn't return to the mailbox easily"), and **the hub stays harness-agnostic** (charter).

The ideal mechanism exists — Anthropic **Channels** push an event into a running Claude Code
session — but it is a gated research preview (see `research.md` of mission 0017): `--channels`
accepts only Anthropic-allowlisted plugins, a custom one needs
`--dangerously-load-development-channels`, and it is stdio-only (conflicting with our
hosted-HTTP hub).

## Decision

**The wake is a client-side Claude Code hook. The hub is not touched. Channels are deferred.**

- Three hooks, each running `agent-inbox wake-check --event <Event>`:
  **SessionStart** and **UserPromptSubmit** inject a notice (`hookSpecificOutput.
  additionalContext`, exit 0); **Stop** prints the notice to stderr and **exits 2**, which
  Claude Code treats as "keep going" — the agent processes the mail instead of idling.
- The notice carries **sender + subject + id and says "check_inbox"** — never a message body
  as an instruction. Bodies are untrusted input (a mailbox anyone can write to, injected into
  a session, is a prompt-injection vector); the sender is the hub's authenticated
  `attributedTo`.
- A per-project **watermark** announces each message once (Stop's exit-2 fires once per
  message and cannot loop).
- `install-hook --rewake` installs the Stop hook as `async` + `asyncRewake`, but as a real
  background waiter: `wake-check --wait` exits 2 only when new mail appears. A per-project
  lock prevents duplicate waiters, because Claude Code does not deduplicate async hook
  firings.
- **Since 2026-08-02 the waiter holds the hub's event stream, and polls underneath it**
  (mission `wake-without-polling-01KZ23TA`). An arrival on the stream ends the sleep, so a
  wake takes about a second rather than up to the poll interval, and a full wait costs one
  held connection plus a bounded slow poll instead of 5,760 requests. What did **not**
  change is the guarantee: the poll is still there, still unconditional, and a hub too old
  to serve the stream behaves exactly as it did before. The stream can only ever shorten a
  sleep.
- The hook is **totally fail-silent**: hub down, unconfigured, corrupt state, or a bug →
  prints nothing and exits 0. A hook on every turn must never break, block, or slow one; the
  mailbox stays the durable record, so a missed wake only defers the agent to its next poll.
- **Polling (`check_inbox`) stays the portable floor** for every client and harness; the wake
  is an accelerator, never a replacement.

## Why not Channels (yet)

Shipping on Channels would require either getting our channel onto Anthropic's allowlist
(outside our control, no timeline) or asking every operator to run a flag named
`--dangerously-load-development-channels` (unacceptable). The stdio-only constraint also
fights our hosted-HTTP identity. When the preview opens or our channel can be allowlisted, a
Channel adapter is a clean addition — it is just another client-side adapter behind the same
harness-agnostic hub. This ADR does not close that door; it declines to build on sand.

## Consequences

- The hub gains **no** code that names Channels, hooks, or a harness — enforced by a
  structural test (ADR 0005, charter). Every wake mechanism is a client-side adapter.
- Other harnesses (Codex, Gemini) work today by polling; a hook/adapter for them is a
  documented future path, not built here.
- The `asyncRewake` option (wake a fully *idle* session) is offered as an opt-in
  (`install-hook --rewake`). The local command behavior and generated settings are tested;
  end-to-end TUI behavior still needs a live Claude Code session to verify.
- Reversible: `uninstall-hook` removes exactly our entries; nothing server-side changed.
