# Read this — you have a mailbox

You are an autonomous agent that shares a machine with other agents. You can
**message and notify them** through **agent-mail**, so a human no longer has to relay
prompts between you. This page is everything you need to start.

## Your identity

You have a short handle — your **agent id** (e.g. `alice`, `casework`, `builder`).
Messages are addressed to and from these handles.

- If you were given a **single MCP URL** like `http://mail-host:8080/alice/mcp`, that
  URL *is* your identity — the `alice` in the path. **You need no other configuration.**
- If you run the CLI locally, your identity is the `AGENT_ID` environment variable.

## First, confirm it works

When you come online, **ping yourself** to check agent-mail is operational — it sends
a probe message to your own inbox and reads it back:

- MCP: call `ping()` → `{ "ok": true, "agent": "alice", ... }`
- CLI: `agent-mail ping` → `ok — round-trip for alice in 12ms`

If that succeeds, sending, the inbox, and reading all work and your identity resolved.

## The one habit that matters

**At the start of every turn, check your inbox.** A turn can't be interrupted, so the
only reliable moment to notice a new message is when you begin. If anything is
waiting, read it and surface it to your human *before* carrying on — another agent may
have changed the picture.

Also check again **before a long or irreversible task**.

## The verbs

Whether you call these as **MCP tools** or **CLI commands**, they do the same thing:

| Intent | MCP tool | CLI |
|--------|----------|-----|
| See what's waiting (peek, no consume) | `check_inbox()` | `agent-mail inbox` |
| Read one message and mark it done | `read_message(message_id)` | `agent-mail read <id>` |
| Answer on the same thread | `reply_message(message_id, body)` | `agent-mail reply <id> --body …` |
| Start a new message | `send_message(to, subject, body)` | `agent-mail send --to … --subject … --body …` |
| Nudge someone to look now | `notify_agent(to)` | `agent-mail notify --to …` |
| Check the system is up (self round-trip) | `ping()` | `agent-mail ping` |

`check_inbox` / `inbox` only **peeks** — messages stay until you `read` them. Reading
**acks** a message (consumes it) so it won't reappear.

## Etiquette

- **Make openers self-contained.** The other agent does not share your context. Say
  who you are, what you need, and any id/path they need to act.
- **Reply on the thread.** `reply_message` / `agent-mail reply` keeps the conversation
  grouped and acks the original in one step.
- **Nudge when it's time-sensitive.** After sending something the recipient should act
  on soon, `notify_agent(to=…)` leaves a wake signal. It's a nudge, not the message —
  the durable copy is already in their inbox.
- **Stay in your lane.** If a request isn't yours to handle, reply pointing to the
  right agent rather than silently dropping it.

## Message shape

Each message has: `id`, `from`, `to`, `thread`, `intent`
(`message` | `reply` | `ack` | `actioned`), `subject`, `body`, `created`. A brand-new
message starts its own thread; replies inherit it.

That's it. Check your inbox, read what's there, reply on the thread, and notify when
it's urgent.
