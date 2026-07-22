# agent-mail

**A NATS-backed mailbox for local LLM agents** — so AI coding agents (Claude, Codex,
Gemini, …) running on the same machine can **notify and message each other** with a
simple CLI and MCP tools, instead of a human hand-relaying prompts between them.

## Why

Agents on one box coordinate today by dropping files in a shared git repo — durable
and auditable, but **poll-only**: one agent can't get another's attention. `agent-mail`
uses **NATS JetStream** (a durable store + a wake signal + request-reply) to add the
missing piece: a real inbox each agent can read, and a "you have mail" nudge.

## Status

Early. The design brief is in [`.kittify/mission-brief.md`](.kittify/mission-brief.md);
built spec-driven with Spec Kitty.

## Planned surface

```bash
agent-mail send --to casework --subject "corpus stale?" --body "..."   # leave a message
agent-mail inbox                                                        # peek unread for me
agent-mail read <id>                                                    # read + ack
agent-mail reply <id> --body "..."                                      # reply on the thread
agent-mail notify --to casework                                         # "you have mail" wake
agent-mail mcp-serve                                                    # same verbs as MCP tools
```

Config: `NATS_URL` (default `nats://192.168.86.31:4222`), `AGENT_ID` (your agent name).

## Not this

Not legal/goldberg-specific — generic inter-agent infrastructure. Not a solution to
true mid-turn interruption (impossible); "periodic check" means *every turn*.
