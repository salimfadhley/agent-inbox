# Research — waking Codex and OpenCode

Read 2026-07-27. Companion to `research.md`, which covers Claude Code. Separate file so
it cannot collide with pablo_fantomas's work in the same mission.

**The question:** the mission claims a harness-agnostic hub (C-001, NFR-001). The hub side
of that is true — nothing in it names Claude Code. But only one client can actually be
woken, and "harness-agnostic" is a claim about the *clients* too. So: can Codex and
OpenCode be woken, and by what?

## The short answer

| harness | wake an *idle* session? | mechanism | verdict |
|---|---|---|---|
| **Claude Code** | **yes** | Stop hook, `async` + `asyncRewake`, exit 2 | shipped |
| **Codex** | **no, not today** | Stop hook exists, but `async` is unimplemented | turn-boundary only |
| **OpenCode** | **yes, and better** | `POST /session/{id}/prompt` on the local server | not a hook at all |

They are three genuinely different capabilities, not one feature with three adapters. A
spec that says "harness-agnostic" without saying that is overclaiming.

## Codex

**Hooks exist and the contract is nearly identical to Claude Code's.** Ten lifecycle
events, including `SessionStart`, `UserPromptSubmit` and — the one that matters — `Stop`,
which "fires when the main agent completes a turn". The conventions match ours almost
exactly:

- exit `2` + stderr → treated as a block, with the stderr text fed back to the agent;
- or JSON `{"decision": "block", "reason": "…"}` to keep the agent going;
- `additionalContext` injects model-visible text;
- `{"continue": false}` stops the agent permanently.

So `wake_response`'s existing shape — exit 2 with a sender+subject notice on stderr —
should port to Codex with little more than a config translation. Hooks live in
`hooks.json` or inline `[hooks]` tables in `config.toml`.

**But the waiter pattern is impossible today, and this is the finding.** From the official
docs, verbatim:

> The `async` option is parsed, but asynchronous command hooks aren't supported yet.

Everything runs synchronously. A `wake-check --wait` Stop hook would therefore **hold the
session open** for as long as it polled, rather than releasing it and rewaking later. That
is not a slow wake; it is a hung session.

Consequence for us: on Codex we can implement *"do not go idle while mail is already
waiting"* — a fast one-shot Stop check that exits 2 — but **not** *"wake when mail arrives
ten minutes from now"*. The second needs async, and async is not there.

Two smaller notes worth carrying into any installer:

- **`notify`** runs a command after each completed task. It is outbound (Codex tells you),
  not inbound, so it cannot deliver mail into a session — but it is the natural hook for
  *the reverse* direction if we ever want a Codex agent to announce its own idleness.
- **`notify` is ignored in project-local `.codex/config.toml`** and warns at startup:
  project config may not run machine-local commands. So an installer must write user-level
  config for that key, unlike our `.claude/settings.json` approach. Do not assume the
  Claude Code installation shape transfers.

*Uncertain and not to be asserted:* sources disagree on the `Stop` hook's timeout. The
general default is 600 s, `SessionEnd` is documented as 1 s (max 3 s), and at least one
summary conflated the two. Anyone building this should read the current timeout table
rather than trust either number here.

## OpenCode

**A different architecture, and the only one of the three with real push.**

Plugins are TypeScript modules subscribing to an event bus — `session.idle`,
`session.status`, `session.updated`, `tool.execute.before`, `file.edited` and many more —
and receive a `client` (the OpenCode SDK) plus `$` for shell. `session.idle` fires when a
session goes inactive, which is the natural place to *notice* idleness.

But the interesting capability is not the plugin system at all. **`opencode serve` runs a
headless HTTP server (default port 4096) exposing the full session API**, including:

```
POST /session/{sessionID}/prompt
```

with an SDK equivalent:

```js
await client.session.prompt({ sessionID, parts: [{ type: "text", text: "…" }] })
```

That means an external process — our hub, a relay, anything — can **push text directly
into a running session** with no hook, no polling, no blocking, and no dependence on the
agent reaching a turn boundary. It is the mechanism the Claude Code `asyncRewake` path is
approximating.

Two cautions, and the second is the serious one:

- It needs the server reachable and the session id known. That is discovery work we do not
  currently do, and it is per-machine rather than per-hub.
- **A pushed prompt looks like the user speaking.** Our whole wake design deliberately
  injects *sender and subject only* and never a body, because message bodies are untrusted
  input (C-004). A `session.prompt` call is a far more powerful primitive than a hook
  notice, and it would be very easy to build something that pipes a stranger's message
  text straight into an agent's context as though the operator had typed it. If we build
  this adapter, the notice discipline matters more here than anywhere else, not less.

## What this means for the mission

1. **The harness-agnostic claim should be narrowed in the spec.** The *hub* is
   harness-agnostic and that is real. Client capability is not uniform, and the difference
   is not cosmetic: idle-wake works on Claude Code, cannot work on Codex today, and would
   work by an entirely different route on OpenCode.
2. **A Codex adapter is worth building anyway**, at the reduced capability: `SessionStart`
   and `UserPromptSubmit` context injection, plus a one-shot `Stop` that refuses to idle on
   pending mail. That is most of the value, and it is honest about what it is.
3. **Watch Codex's `async`.** The moment asynchronous command hooks land, the existing
   `wake-check --wait` waiter ports over nearly unchanged — the exit-2-with-stderr contract
   is already the same. This is a one-line capability change for us, gated entirely on
   them.
4. **OpenCode should be designed deliberately, not by analogy.** Reaching for a hook there
   would be building the weaker mechanism when a stronger one exists. But the stronger one
   is also the one that can most easily be misused, so it wants the notice rule written
   down before any code.

## Sources

- [Codex hooks](https://learn.chatgpt.com/docs/hooks) — event list, exit codes, the
  `async`-not-supported quote, timeouts
- [Codex configuration reference](https://developers.openai.com/codex/config-reference) —
  `notify`, `[hooks]` in `config.toml`
- [Codex advanced configuration](https://developers.openai.com/codex/config-advanced) —
  project-local `notify` refusal
- [OpenCode plugins](https://opencode.ai/docs/plugins/) — event list, `client`, `session.idle`
- [OpenCode server](https://opencode.ai/docs/server/) — headless HTTP server, port 4096
- [OpenCode SDK](https://opencode.ai/docs/sdk/) — `client.session.prompt()`
