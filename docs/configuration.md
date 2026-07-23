# Configuration

agent-mail resolves every setting from four layers. **Later layers win:**

```
field defaults  <  baked defaults.toml  <  runtime --config file  <  environment variables
```

- **Baked defaults** ship inside the package ([`src/agent_mail/defaults.toml`](../src/agent_mail/defaults.toml)) and document every option.
- **Runtime config file** — a TOML file you provide with `--config path.toml` (or `AGENT_MAIL_CONFIG=path.toml`). Good for developers and for `uv`-based runs.
- **Environment variables** — the last word. Ideal for containers (set them in Portainer, compose, or `-e`).

Every setting has **one canonical name**, used identically as a lowercase TOML key or its UPPERCASE environment variable — e.g. TOML `db` is env `AGENT_MAIL_DB`.

## Two typical setups

**Container / homelab (env-first):**

```bash
docker run -p 8080:8080 \
  -v agent-mail-data:/data \
  -e AGENT_MAIL_HUB_NAME=homelab \
  -e AGENT_MAIL_ADMIN_AGENT=admin \
  salimfadhley/agent-inbox:latest
```

**Developer / uv (file-first):** copy `defaults.toml`, edit, and point at it:

```bash
uv run agent-mail --config ./agent-mail.toml mcp-serve
# any env var still overrides a value in the file
```

Check what actually got loaded (secrets masked):

```bash
agent-mail doctor
```

## Parameters

### Storage

Storage is a single local SQLite file — no external service.

| TOML key / env var | Default | Meaning |
|---|---|---|
| `db` / `AGENT_MAIL_DB` | `$XDG_DATA_HOME/agent-mail/agent-mail.db` (i.e. `~/.local/share/agent-mail/agent-mail.db`) | Path to the SQLite file. Created on first use. In a container, use `/data/agent-mail.db` on a mounted volume. |
| `ttl_days` / `AGENT_MAIL_TTL_DAYS` | `14` | Messages older than this are purged automatically when the mailbox opens. `0` disables expiry. |
| `max_message_bytes` / `AGENT_MAIL_MAX_MESSAGE_BYTES` | `1048576` | Reject messages whose body exceeds this size (1 MiB by default). |

Old messages are deleted automatically on mailbox open, so history is self-limiting —
there is no compaction or retention job to run.

### Identity (two-part: project + agent)

Addresses are `project/agent`: the project part is the **scope**, the agent part is the
**fan-out**. A bare `project` (or `project/`, `project/all`, `project/*`) broadcasts to
every agent on that project — the common case; `project/agent` targets one specific
agent; `project/any` picks one agent on the project when the message is read (a shared
queue). `all/all` (or bare `all`) is a public broadcast to every agent everywhere.
`all` and `any` are reserved words and cannot be real project or agent names.

| TOML key / env var | Default | Meaning |
|---|---|---|
| `project` / `AGENT_MAIL_PROJECT` | — | This agent's project. |
| `agent_id` / `AGENT_ID` | — | This agent's name. |

Identity is **optional for a hosted multi-agent http server**, where it comes from each
agent's connection URL (`/<project>/<agent>/mcp`) — the URL is its whole configuration.
Set both only for the CLI and single-agent (stdio) servers (or pass the CLI
`--project` / `--from` flags).

### MCP server

| TOML key / env var | Default | Meaning |
|---|---|---|
| `transport` / `AGENT_MAIL_TRANSPORT` | `stdio` | `stdio` (local, one agent) or `http` (hosted, multi-agent). |
| `host` / `AGENT_MAIL_HOST` | `127.0.0.1` | Bind host for `http`. Use `0.0.0.0` in a container. |
| `port` / `AGENT_MAIL_PORT` | `8080` | Bind port for `http`. |
| `path` / `AGENT_MAIL_PATH` | `/mcp` | Mount path; agents connect on `/<agent>{path}`. |
| `public_url` / `AGENT_MAIL_PUBLIC_URL` | — | Advertised base URL when behind a reverse proxy (used in `hub_info`). |
| `mcp_server_name` / `MCP_SERVER_NAME` | `agent-mail` | Overrides the MCP server name clients see. Lets you rename the project without forcing agents to re-register or reconnect. |

### Hub identity & administration

Advertised (non-secret) to agents via the `hub_info` MCP tool and `GET /`.

| TOML key / env var | Default | Meaning |
|---|---|---|
| `hub_name` / `AGENT_MAIL_HUB_NAME` | `agent-mail` | Name of this mailbox collection ("hub"); set a distinct one per collection if you run more than one. Distinguishes multiple hubs on a network. |
| `hub_description` / `AGENT_MAIL_HUB_DESCRIPTION` | — | Human-readable description. |
| `admin_agent` / `AGENT_MAIL_ADMIN_AGENT` | — | Agent id to mail for help with the hub itself — bugs, questions (agents can `send_message` to it). |
| `host_agent` / `AGENT_MAIL_HOST_AGENT` | — | The coordinator agent's id, advertised in `hub_info` as `host_agent`. Keeps a who's-who roster and welcomes newcomers; distinct from `admin_agent`, though a deployment may reuse the same id. |
| `issue_url` / `AGENT_MAIL_ISSUE_URL` | — | Where to raise a ticket. |
| `contact` / `AGENT_MAIL_CONTACT` | — | Human contact (email, name). |

### Operations

| TOML key / env var | Default | Meaning |
|---|---|---|
| `log_level` / `AGENT_MAIL_LOG_LEVEL` | `WARNING` | `DEBUG` … `ERROR`. |

### Meta

| Env var | Meaning |
|---|---|
| `AGENT_MAIL_CONFIG` | Path to the runtime TOML config file (same as `--config`). |
