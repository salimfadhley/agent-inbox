# Research — live-session push (mission 0017)

The mission's first deliverable is a decision, evidenced (FR-010, SC-007). Here it is,
with the sources actually read on 2026-07-25.

## Decision: build the hook-based wake now; defer Channels

**Channels are not yet a viable production path for agent-mailbox, so this mission ships the
hook-based wake and leaves a clean seam for a Channel adapter later.**

### Why not Channels (yet)

Anthropic's **Channels** are exactly the right shape — an MCP server that pushes an event
into a *running* Claude Code session — but they are a **gated research preview**:

- Launched **2026-03-20 as a research preview**, explicitly "not a finished product."
- The `--channels` flag **only accepts plugins from Anthropic's approved allowlist**.
  Loading a custom channel (which ours would be) requires
  **`--dangerously-load-development-channels`**. Shipping a feature that asks every operator
  to run a flag named "dangerously" is not acceptable, and getting our channel onto
  Anthropic's allowlist is out of our control and on no timeline we set.
- **stdio-only**, which conflicts with our hosted-HTTP hub identity
  (`http://<hub>/…/mcp`). Bridgeable by a local stdio shim — but moot while the allowlist
  gates us out.
- Requires **claude.ai/Console auth** (not Bedrock/Vertex/Foundry), and Team/Enterprise must
  enable it — so availability is per-account and cannot be assumed.

Verdict: **defer.** When the preview opens or our channel can be allowlisted, a Channel
adapter is a straightforward addition — it is just another client-side adapter behind the
same harness-agnostic hub. The spec's FR-003 stays a documented future path, not built here.

Sources: [Channels docs](https://code.claude.com/docs/en/channels);
[Towards AI, "Claude Code Channels" (2026)](https://pub.towardsai.net/claude-code-channels-message-your-ai-coding-agent-from-telegram-and-discord-2026-5f263ccc4b9c);
the 0017 brief.

## The hook contract we build on (verified from source)

[Claude Code hooks docs](https://code.claude.com/docs/en/hooks), read 2026-07-25. The
primitives the wake rides:

| Hook | Fires | How we use it | Output contract |
|---|---|---|---|
| **SessionStart** | session start/resume | announce unread when a session opens | exit 0 + JSON `hookSpecificOutput.additionalContext` (or plain stdout) |
| **UserPromptSubmit** | each time the human submits a prompt | remind of pending mail at turn start | exit 0 + JSON `additionalContext` |
| **Stop** | when Claude finishes a turn | keep a working agent from idling while NEW mail is pending | **exit 2** → "prevents Claude from stopping, continues the conversation"; stderr fed back to Claude |

Exit-code convention (universal): **0** = success, stdout parsed as JSON; **2** = blocking,
stdout/JSON ignored, **stderr fed to Claude**, action blocked; **any other** = non-blocking
error, shown in transcript. JSON stdout must be the whole object; the useful field is
`hookSpecificOutput.additionalContext`.

Configuration lives in `.claude/settings.json` under
`hooks -> <EventName> -> [ { matcher, hooks: [ { type:"command", command, timeout } ] } ]`.
There is also an `asyncRewake` command option (an async hook that can rewake an idle
session) — the richer "wake a fully idle session" path. We design so it *can* be turned on,
but the reliable, verifiable core is the three synchronous hooks above.

### What this means for the design

- **SessionStart + UserPromptSubmit** give reliable, deterministic "you have mail" injection
  at the two moments an agent is about to act. Fully unit-testable at the command level.
- **Stop exit-2** is the "don't go idle with mail pending" wake: on *newly-arrived*
  (unannounced) mail it exits 2 with a stderr notice so the agent keeps going and processes
  it. Announce-once (a watermark) makes this fire exactly once per message, so it cannot
  loop.
- **asyncRewake** (true idle-session wake) is left as an opt-in the install can enable; its
  end-to-end behaviour needs a live Claude Code session to verify, so it is not the core
  deliverable.

## The two rules, discharged

- **Harness-agnostic hub** (C-001, NFR-001): everything above is *client-side*. The hub
  already exposes `check_inbox`/unread; it gains nothing that names Claude Code, hooks, or
  channels.
- **Untrusted bodies** (C-004, FR-005): the wake injects `sender + subject + id` and tells
  the agent to `check_inbox` — it never puts a message body into the session as an
  instruction. Sender identity comes from the hub's authenticated `attributedTo`.
