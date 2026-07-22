# agent-mail

**A NATS-backed mailbox for local LLM agents.** AI coding agents (Claude, Codex,
Gemini, …) running on the same machine or LAN get a simple, standard way to
**message and notify each other** — a small **CLI** plus a **hostable MCP server**
over the same verbs — instead of a human hand-relaying prompts between them.

[![CI](https://github.com/salimfadhley/agent-mail/actions/workflows/ci.yml/badge.svg)](https://github.com/salimfadhley/agent-mail/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)

---

## Why

Agents on one box usually coordinate by dropping files in a shared git repo — durable
and auditable, but **poll-only**: one agent can't get another's attention. `agent-mail`
uses **NATS JetStream** (a durable store + a wake signal + request/reply) to add the
missing piece: a real inbox each agent reads, and a "you have mail" nudge.

> **Honest limitation.** A running LLM turn can't be interrupted or poll on a timer.
> So "check periodically" means **check every turn** — at natural decision points. You
> get a durable inbox to read and a `notify` wake to leave; not mid-turn preemption.

## How it works

- A JetStream stream `AGENT_MAIL` binds `agent.mail.*`. Each agent's inbox is the
  subject `agent.mail.<agent>`, drained by a **durable per-agent consumer**, so
  messages persist until that agent acks them.
- `notify` is a lightweight non-durable publish on `agent.notify.<agent>` — a nudge
  to go read the durable inbox.
- The CLI and the MCP server share one core (`agent_mail.mailbox.Mailbox`) — no logic
  duplication.

See [docs/decisions/0001-nats-jetstream-mailbox.md](docs/decisions/0001-nats-jetstream-mailbox.md)
for the design rationale (and the Claim-Check option for large payloads).

## Requirements

- **Python 3.12+**
- **A NATS server with JetStream enabled.** This is a prerequisite — `agent-mail`
  does not bundle one. Point `NATS_URL` at it. (For a throwaway local one:
  `docker run -p 4222:4222 nats -js`.)

## Install

```bash
uv tool install agent-mail      # recommended (isolated CLI)
pipx install agent-mail         # or
pip install agent-mail          # into the current environment
```

Or run the MCP server as a container — see [Hosting](docs/hosting.md):

```bash
docker run -p 8080:8080 -e NATS_URL=nats://your-nats:4222 \
  ghcr.io/salimfadhley/agent-mail:latest
```

## Quickstart (CLI)

Identity comes from `AGENT_ID` (or `--from`); the server from `NATS_URL`.

```bash
export NATS_URL=nats://127.0.0.1:4222
export AGENT_ID=alice

# leave a message for bob
agent-mail send --to bob --subject "corpus stale?" --body "please reindex"

# bob peeks his inbox (does not consume)
AGENT_ID=bob agent-mail inbox

# bob reads + acks a specific message, then replies on the thread
AGENT_ID=bob agent-mail read <id>
AGENT_ID=bob agent-mail reply <id> --body "on it"

# nudge bob's listener to look now
agent-mail notify --to bob
```

Add `--json` to any command for machine-readable output.

| Verb | What it does |
|------|--------------|
| `send --to --subject --body [--thread] [--intent]` | Publish to a recipient's durable inbox |
| `inbox` | List my unread messages (peek — does **not** ack) |
| `read <id>` | Show a message and **ack** it (consume) |
| `reply <id> --body` | Reply on the same thread and ack the original |
| `notify --to [--thread]` | Publish a non-durable "you have mail" wake |
| `mcp-serve` | Run the MCP server (see below) |

## MCP server

The same verbs are exposed as MCP tools (`send_message`, `check_inbox`,
`read_message`, `reply_message`, `notify_agent`). Two ways to run it:

**Local, per-agent (stdio).** The client spawns it; identity is `AGENT_ID`.

```bash
AGENT_ID=alice NATS_URL=nats://127.0.0.1:4222 agent-mail mcp-serve
```

**Hosted, multi-agent (http).** One server serves everyone. **Each agent connects on
its own address — the URL *is* its identity:**

```
http://mail-host:8080/alice/mcp      → identity = alice
http://mail-host:8080/casework/mcp   → identity = casework
```

```bash
NATS_URL=nats://your-nats:4222 agent-mail mcp-serve --transport http --host 0.0.0.0
```

That personalized URL is an agent's **entire configuration** — no `AGENT_ID`, no
headers. (`?agent=<name>` and an `X-Agent-Id` header also work for programmatic
clients.) See [docs/mcp-clients.md](docs/mcp-clients.md) to wire it into Claude Code,
Codex, and other clients, and [docs/hosting.md](docs/hosting.md) to deploy it.

## The "check your inbox" convention

An agent only benefits from mail if it looks. Paste the ready-made block from
[docs/inbox-check-snippet.md](docs/inbox-check-snippet.md) into your agents'
`CLAUDE.md` / `AGENTS.md`, and hand a new agent
[docs/agent-onboarding.md](docs/agent-onboarding.md) to get it participating.

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `NATS_URL` | `nats://127.0.0.1:4222` | NATS (JetStream) server |
| `AGENT_ID` | — | This agent's identity (CLI / stdio server) |
| `AGENT_MAIL_TRANSPORT` | `stdio` | `stdio` or `http` |
| `AGENT_MAIL_HOST` | `127.0.0.1` | Bind host for `http` |
| `AGENT_MAIL_PORT` | `8080` | Bind port for `http` |
| `AGENT_MAIL_PATH` | `/mcp` | Mount path for `http` |
| `AGENT_MAIL_LOG_LEVEL` | `WARNING` | `DEBUG` … `ERROR` |

## Development

```bash
uv sync --dev
uv run pytest                       # unit tests
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

Live round-trip against a real JetStream (opt-in):

```bash
AGENT_MAIL_INTEGRATION=1 NATS_URL=nats://your-nats:4222 uv run pytest tests/test_integration.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the coding standards and quality gates.

## License

[GPL-3.0-or-later](LICENSE).
