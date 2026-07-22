# The "check your inbox" convention

Paste one of the blocks below into your agent's `CLAUDE.md` / `AGENTS.md` (or the
system prompt / project instructions of any agent that should participate in
inter-agent mail). It tells the agent to look at its `agent-mail` inbox at the
points where doing so actually changes what it does next.

> **Honest limitation:** a running LLM turn cannot poll on a timer and cannot be
> interrupted mid-thought. So "check periodically" really means **"check every
> turn"** — at the moments the agent is naturally deciding what to do. `agent-mail`
> gives you a durable inbox to read and a `notify` wake to leave; it does not (and
> cannot) preempt a turn already in flight.

---

## CLI agents (Claude Code, Codex, Gemini CLI, …)

```markdown
## Inbox check (agent-mail)

You share a mailbox with other agents via `agent-mail` (NATS JetStream).
Your identity is the `AGENT_ID` environment variable.

- **At the start of every turn**, run `agent-mail inbox`. If it lists any
  messages, read and surface them to the user *before* continuing your task —
  another agent may have new information or a request that changes your plan.
- **Before starting a long or irreversible task**, run `agent-mail inbox` again.
- To actually consume a message (and stop it reappearing), run
  `agent-mail read <id>` — this acks it. Plain `inbox` only peeks.
- To answer, use `agent-mail reply <id> --body "…"` (replies on the same thread
  and acks the original).
- When you leave a message another agent should act on soon, follow your `send`
  with `agent-mail notify --to <agent>` so their listener can surface it.

Config: `AGENT_ID` = your name, `NATS_URL` = the shared JetStream URL.
```

## MCP-native agents

```markdown
## Inbox check (agent-mail MCP)

The `agent-mail` MCP server exposes these tools: `check_inbox`, `read_message`,
`reply_message`, `send_message`, `notify_agent`.

- **At the start of every turn**, call `check_inbox`. If it returns any messages,
  surface them to the user before continuing.
- **Before a long task**, call `check_inbox` again.
- Consume a message with `read_message(message_id=…)` (this acks it); answer with
  `reply_message(message_id=…, body="…")`.
- After `send_message(...)`, call `notify_agent(to=…)` when the recipient should
  act soon.
```
