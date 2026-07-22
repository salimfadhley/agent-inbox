# Connecting MCP clients

`agent-mail mcp-serve` exposes five tools — `check_inbox`, `read_message`,
`reply_message`, `send_message`, `notify_agent` — over either transport.

## Hosted HTTP server (recommended for multiple agents)

One server, and **each agent is configured with a single URL** that ends in its own
name. That URL is the entire configuration — no environment variables, no headers.

```
http://<host>:<port>/<agent>/mcp
```

### Claude Code

```bash
# 'alice' is this agent's identity — it's in the URL, nowhere else.
claude mcp add --transport http agent-mail https://mail-host/alice/mcp
```

### Generic MCP client config

```json
{
  "mcpServers": {
    "agent-mail": {
      "type": "http",
      "url": "https://mail-host/alice/mcp"
    }
  }
}
```

Give each agent its own URL (`/alice/mcp`, `/casework/mcp`, …). Programmatic clients
that can't vary the path may instead use `…/mcp?agent=alice` or send an
`X-Agent-Id: alice` header.

## Local stdio server (single agent per client)

The client launches `agent-mail` as a subprocess; identity comes from `AGENT_ID`.

### Claude Code

```bash
claude mcp add agent-mail \
  --env AGENT_ID=alice \
  --env NATS_URL=nats://127.0.0.1:4222 \
  -- agent-mail mcp-serve
```

### Generic MCP client config

```json
{
  "mcpServers": {
    "agent-mail": {
      "command": "agent-mail",
      "args": ["mcp-serve"],
      "env": {
        "AGENT_ID": "alice",
        "NATS_URL": "nats://127.0.0.1:4222"
      }
    }
  }
}
```

## Verify the connection

Once the tools are wired in, have the agent call the **`ping`** tool once — it sends a
message to itself and reads it back, confirming connectivity, identity, and that the
whole mailbox path works before it relies on it.

## Make the agent actually use it

Configuring the tools isn't enough — tell the agent to check its inbox each turn.
Paste the block from [inbox-check-snippet.md](inbox-check-snippet.md) into the agent's
`CLAUDE.md` / `AGENTS.md`, and hand a new agent
[agent-onboarding.md](agent-onboarding.md).
