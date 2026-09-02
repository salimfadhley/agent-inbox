# 2026-09-02 — v1.1.1 shipped, ADR 0012, and omp (oh-my-pi) wake research

Written mid-task because the session is being restarted. Everything under "Done" is on
`main` and pushed. The part worth not losing is the **research**, further down: it is the
input to a mission that has not been written yet.

## Done and shipped

**v1.1.1 — issue #49, the concurrent-join lock.** Tagged, released, deployed to the stodge
node, proved (`verify-deployment`: 5 checks, hub and console both report 1.1.1 at the
public addresses). Issue closed. Announced to all 24 agents.

- New `src/agent_inbox/locking.py` — `exclusive()`, an `O_EXCL` lock: pid-aware,
  stale-tolerant, no dependency, no `fcntl` (Windows). Modelled on `wake.py`'s
  single-waiter lock with one inversion: **a waiter that cannot take the lock skips; a
  writer waits.** Skipping the write is the data loss.
- Every read-modify-write of a config file now holds it across *both* halves —
  `write_config`, `write_project`, `unset_project`, `write_global`, `unset_global`, and
  `_set_machine_hub` (which decides from what it reads, so an unlocked read there could
  overwrite a hub somebody had just set by hand).
- Two defects the tests found, not me: (1) the first lock **excluded nobody** — `O_EXCL`
  creates the file and the pid lands a moment later, so a contender in that gap read an
  *empty* file, judged it crash debris, and deleted the winner's brand-new lock. Age
  distinguishes them; content cannot. (2) All writers shared one `.tmp` name. Now
  pid-suffixed in both renderers.
- Removal proofs run in full, `__pycache__` cleared between halves.
- `6afd509` (test-only, **after** the tag, so main is one commit ahead of v1.1.1): a
  structural guard asserting every config write sits inside a `with exclusive(...)`, with
  its own premise check so it cannot pass vacuously if `_render_project` is renamed.

**ADR 0012 — no nicknames; findability is a description.** Owner decided against the nick
feature outright. Recorded in `doc/decisions/`, README updated, and both the polled agents
and `spuridon_tesar` told. The argument in one line: **descriptions need not be unique**,
which dissolves contention, allocation, reserved authorities, homoglyphs, expiry and the
untrusted-namespace question — none of which has an answer under descriptions because none
is a question. A nick would also have rebuilt the natural key ADR 0003 exists to remove.
Do not re-propose aliases.

## Broken right now — fix first

**The agent-inbox MCP server did not connect this session:**

```
agent-inbox (ENOENT): no such file or directory, posix_spawn
  '/Users/salimfadhley/.local/bin/agent-mailbox'
```

That is the console script the charter records as **removed on 2026-08-05**. This machine's
MCP config still points at it, so there is no mail this session. Repoint it at
`agent-inbox` (or `python -m agent_inbox`) before anything that needs the mailbox. This is
the exact stale-shim case the wake-hook rewrite shipped for, landing on our own machine.

## The live task: support omp (oh-my-pi), and wake a sleeping one

Owner's ask, verbatim in intent: support **omp** the way we support Claude Code, and if at
all possible **wake a sleeping omp client**. Research was done; the mission was not yet
written. Answer to "can it be done": **yes, and better than on Claude Code.**

Note the name: the project is **oh-my-pi**, binary `omp` — not "OhMyPy".
`can1357/oh-my-pi`, TypeScript/Rust, MIT, ~29k stars, pushed 2026-09-02, very much alive.

### Findings, all verified against the repo (not recalled)

**1. It already reaches our hub, and we do not recognise it.**
`packages/coding-agent/src/mcp/client.ts` sends
`clientInfo = { name: "omp-coding-agent", version: "1.0.0" }`. That is the same detection
route we used for opencode in #63 — `_CLIENT_ENGINES` in `mcp_client.py`, no environment
variable needed. Add `("omp", "omp")` (match on substring, as opencode does) and it
resolves.

**2. omp reads Claude Code's MCP config.** `docs/mcp-config.md`: it imports
`~/.claude.json`, `~/.claude/mcp.json`, `.claude/.mcp.json`, plus Codex, Gemini, Cursor,
Windsurf, VS Code and `opencode.json`. So anyone who configured the mailbox for Claude Code
**already has it in omp**. This means an unrecognised `omp-coding-agent` may be hitting the
hub today, falling through to the unknown-harness warning we shipped in #63. Check the hub
logs for it — that is free evidence.

**3. Project config lives in `.omp/`, cwd-only.** `docs/extension-loading.md`: native
discovery roots are `<cwd>/.omp/extensions` and the user's `~/.omp/agent/extensions`. The
project root "is the native provider's `.omp` directory, cwd-only; it does not walk
ancestors" — same shape as `.opencode/`, so the per-project identity model holds unchanged.
MCP config: `.omp/mcp.json` (project) / `~/.omp/agent/mcp.json` (user).

**4. The wake primitive exists and is stronger than Claude Code's.** From
`docs/extensions.md`, an extension is a default-exported factory in
`.omp/extensions/*.ts` receiving `ExtensionAPI`:

- `pi.on(event, handler)` with `turn_end`, `agent_end`, `session_start`,
  `session_shutdown` — the `Stop` / `session.idle` analogue.
- **`pi.sendMessage(msg, { deliverAs, triggerTurn })`**. `deliverAs` is one of `steer`
  (**interrupts the current run** — the default, and *not* what we want), `followUp`
  (queued until the run finishes), `nextTurn` (injected on the next user prompt).
  **`triggerTurn: true` starts a turn when idle.** That is a real wake, not a
  wait-for-the-next-turn.
- `ctx.isIdle()`, `ctx.hasPendingMessages()`, `ctx.abort()`, `ctx.shutdown()`.
- **`ctx.setInterval` / `ctx.setTimeout`** — managed timers: isolated like handler
  dispatch (a throw is logged, not fatal), `unref`'d, auto-cleared on `session_shutdown`.
- `pi.exec(...)` to shell out, `pi.logger`.

So the shape is: a background timer (or held waiter) inside the session that runs
`agent-inbox wake-check --wait` and, on exit 2, calls
`pi.sendMessage(notice, { deliverAs: "followUp", triggerTurn: true })`. **An idle omp
session can be woken while its human is away** — which Claude Code's blocking `Stop` hook
cannot do.

**5. The hazard, and it is the whole safety story.** Extensions run **in-process with no
isolation**: raw `setInterval`/detached-promise throws surface as `uncaughtException` and
**tear down the whole session**. So every callback must use `ctx.setInterval` and be
wrapped. And `deliverAs: "steer"` interrupting a running agent is precisely the
"expect no interruptions" contract our own MCP instructions promise — using the default
would break it.

Above all, ADR 0008: the injected text lands **in the conversation**, so a message *body*
injected here would read as the operator's own instruction and any peer who could write to
this agent could steer it. `wake._notice` already emits **sender and subject only, never a
body** — the extension must pass that through unaltered, exactly as the opencode plugin
does, and `tests/test_opencode_waking.py::TestTheNoticeIsNeverAMessageBody` is the model
for the test.

### Open questions for the mission (research tasks, not blockers)

- `sendMessage` takes an `attribution` field (normalised by
  `normalizeCustomMessagePayload` in `session/messages.ts`). Can it mark the notice as
  machine output rather than the human's voice? On Claude Code exit-2 stderr is visibly
  machine; here it must be made so deliberately.
- `followUp` + `triggerTurn` versus `nextTurn` + `triggerTurn` — which actually wakes an
  idle session without disturbing a running one. Needs a live check.
- Does anything set an env marker for `detect_engine`? Not found; the `clientInfo` route
  is better anyway and needs no variable.
- Headless surfaces exist (`--print`, `--output-format json|rpc|acp`, an `acp` subcommand,
  a `ps` daemon-supervised background-process subcommand). Worth knowing whether a wake
  can reach a *parked* session, not merely an idle one — `docs/agent-hub.md` shows
  subagents with `running | idle | parked | aborted` status.

### Next steps

1. **File the GitHub issue** — the mission board is built from issues, never from
   `tasks.md` checkboxes. Two-part shape, matching #63/#64: (a) omp is a known harness —
   `_CLIENT_ENGINES` + `hookconfig.SUPPORTED_HARNESSES`, small and shippable alone;
   (b) `install-hook --engine omp` writes `.omp/extensions/agent-inbox-wake.ts`.
2. Reuse `hookconfig.install_for` / `NoWakingHere` — the refusal path from #64 already
   exists, so this is a third branch, not new machinery.
3. Ask an omp-running agent to test, the way `aurelia_saahaa` verified opencode for #64.
   #64 is still open pending exactly that.

## Also open

- **#64** — opencode waking, awaiting live verification from `aurelia_saahaa`.
- Unfiled: four fastmcp missions (middleware guard backstop, `elicit` confirm-before-send,
  response limiting, timing); the name-pool ITRANS romanisation.
