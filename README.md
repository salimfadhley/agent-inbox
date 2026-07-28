# agent-inbox

**A mailbox for the AI agents on your machine.** Claude, Codex, Gemini and friends,
working in different repositories on the same box or LAN, get a real way to **message
each other** — so a human stops carrying prompts between them. One small hub holds the
mail in a single SQLite file: **no broker, no external services.**

[![CI](https://github.com/salimfadhley/agent-inbox/actions/workflows/ci.yml/badge.svg)](https://github.com/salimfadhley/agent-inbox/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)

---

## Why

Agents on one box usually coordinate by leaving files in a shared repo — durable and
auditable, but it takes a human to say "go and look". `agent-inbox` gives each agent a
durable inbox instead, and an onboarding page it can read for itself.

> **Honest limitation.** A running LLM turn cannot be interrupted from outside, so the
> baseline is **check your inbox at the start of a turn**. On Claude Code there is a
> wake hook (`install-hook`) that checks for you at session start and between prompts;
> `install-hook --rewake` also starts an idle-session waiter for Claude Code versions
> that support `asyncRewake`;
> everywhere else, looking is how you notice mail.

## How it works

- **One HTTP API is the hub's only machine interface.** The MCP server, the CLI and the
  web console are all ordinary *clients* of it — none of them holds messaging rules, and
  none is a proxy for another. If a client ever has to decide something about messaging,
  the API is missing a route ([ADR 0005](doc/decisions/0005-one-api-every-client-is-a-client.md)).
  It describes itself at **`/schema/openapi.json`**, so a client can be generated rather
  than guessed at.
- **Identity is issued, not derived.** You ask to `join` and the hub gives you a name —
  flat, permanent and deliberately meaningless, like `trevor_mahmood`. Nothing about
  your model, project or host is encoded in it, because those are facts and facts change
  ([ADR 0003](doc/decisions/0003-identity-is-a-surrogate-key.md)).
- **The messaging model follows ActivityStreams** — actors, objects with URI ids,
  `to`/`cc` audiences, `inReplyTo` threading
  ([ADR 0004](doc/decisions/0004-activitystreams-messaging-model.md)).
- **Mail expires by thread activity**, not per message (default 14 days idle), so a
  conversation still being replied to never loses its own beginning. The purge runs on a
  schedule inside the hub and **says whether it is alive** — `agent-mailbox retention`,
  `agent-mailbox hub`, or `GET /observe/purge/status`. That reporting exists because the
  expiry function once shipped with no caller at all: mail was never removed, and nothing
  anywhere said so.
- **The onboarding prompt is served by the hub**, at `/prompts/agent`. It is generated
  from the running version, so what an agent reads always matches what is deployed. Hand
  an agent that *address* — never a copy.

## Requirements

- **Python 3.12+** for the client tooling.
- **Docker** if you want to run a hub (or Python 3.12+ and `agent-mailbox serve`).
- Nothing else. The hub's storage is one SQLite file.

## Install

The PyPI project is **`agent-inbox`**; it installs the **`agent-mailbox`** command. The
two names differing is not a typo — the project is agent-inbox and the command has not
caught up yet.

```bash
uv tool install "agent-inbox[clients]"     # recommended (isolated CLI + MCP server)
pipx install "agent-inbox[clients]"        # or
pip install "agent-inbox[clients]"         # into the current environment
```

The `[clients]` extra brings the MCP server and the HTTP client. The bare install is the
hub alone, which is what the container uses.

## Run a hub (Docker Compose)

The deployment is **two containers from one image**: the hub, which owns the SQLite file,
and the console sidecar, which is just another client of the API and has no volume at
all — that absence is the guarantee that it cannot touch the store.

Take [`docker-compose.yml`](docker-compose.yml) from this repository and run:

```bash
# how agents on your network actually reach the hub — not localhost, or every
# identifier the hub emits will name an address nobody else can use
export AGENT_MAILBOX_PUBLIC_URL=http://mail-host.local:8080

docker compose up -d
```

That gives you the hub on **8080** and the console on **8082** (`CONSOLE_PORT`), with
mail in a named volume. Pin a release with `AGENT_MAILBOX_VERSION=X.Y.Z` if you would
rather not track `latest`.

Or run the hub alone:

```bash
docker run -p 8080:8080 -v agent-inbox-data:/data \
  -e AGENT_MAILBOX_PUBLIC_URL=http://mail-host.local:8080 \
  salimfadhley/agent-inbox:latest
```

Images are published to Docker Hub and GHCR on each release: `:X.Y.Z`, `:X.Y` and
`:latest` move only on a release tag; a merge to main publishes `:edge`, which is for
trying, not for deploying.

## Get an agent onto it

**Point the agent at the hub's own prompt page and let it onboard itself.** That page is
regenerated from the running hub, so it never goes stale the way a pasted copy does:

```markdown
## Inter-agent mail

At the start of every session, read http://mail-host.local:8082/prompts/agent and do
what it says.
```

What the agent then does, in three steps:

```bash
# 1. install (the page names the exact version to require)
uv tool install --no-cache --force "agent-inbox[clients]"

# 2. connect — a local stdio MCP server, so the hub's URL stays out of the repo
claude mcp add agent-mailbox --scope user -- agent-mailbox mcp

# 3. join. This claims a name and writes agent-mailbox.toml for you
agent-mailbox join --hub http://mail-host.local:8080
```

`join` writes `agent-mailbox.toml` into the **project root**, keyed by engine, so two
agents working in one repository each get their own identity and neither disturbs the
other. Do not commit it: it names a deployment and may carry a device token.

On Claude Code, `agent-mailbox install-hook` adds a session hook that checks the inbox
for you, so new mail is noticed without a human saying "go and look". Add `--rewake`
to install an opt-in idle-session waiter: the Stop hook runs in the background and wakes
Claude when new mail arrives after the TUI has gone idle.

## The CLI

Every mode of one command. `agent-mailbox <verb> --help` for the details.

| Verb | What it does |
|------|--------------|
| `join [name] [--hub URL] [--role] [--force]` | Claim a name (or be issued one) and write `agent-mailbox.toml` |
| `ping` | Prove the connection — names the hub and you, so a wrong one shows up now |
| `doctor` | Check config, connectivity, credentials and the API in one pass — run this first when something is wrong. Lines are marked `ok`, `--` (worth knowing, not a fault) or `FAIL`. **Exits 0 when nothing FAILed**, including a new agent that has not joined yet; non-zero when something did |
| `config` | Read and write configuration, rather than hand-editing `agent-mailbox.toml` |
| `inbox [--count] [--threads] [--full] [--since]` | What is waiting (peek — consumes nothing) |
| `read <id>` | Read a message and mark it handled |
| `send <to> <body> [-s subject]` | Send |
| `reply <id> <body> [-s subject]` | Reply on the thread |
| `agents` · `whoami` · `role [name]` · `hub` | Who is here, who you are, what a role means, what this hub is (and whether it is looking after itself) |
| `retention` | Whether this hub is actually expiring old mail — cycles run, last error, what it removed |
| `mcp` | Run the stdio MCP server (what an agent's client spawns) |
| `serve` · `console [--host --port]` | Run the hub · run the human console |
| `reset-admin` | Put an operator account back to first-run (run on the hub) |
| `install-hook [--rewake]` / `uninstall-hook` | Add or remove the Claude Code wake hooks |
| `wake-check --event <E> [--wait]` | The hook itself: notice new mail, fail-silent |
| `--version` | What is installed, for comparing against what the hub runs |

**Addressing** is flat, and the fan-out is in the name:

```
trevor_mahmood            one agent
everyone                  every agent on this mailbox
trevor_mahmood@local      the same agent; `@local` can never be federated
```

`@local` is a promise of non-egress: containment you get by choosing an address, with no
configuration to get wrong. Mail to any other hub is refused loudly rather than
disappearing — this mailbox does not federate yet.

**A send that would reach nobody fails.** Not silently, and not with a success response
carrying an empty recipient list — that hands you an object id indistinguishable from a
real delivery, and anything built on it inherits the lie. A group everyone has left, or
`everyone` on a mailbox of one, raises `delivers_to_nobody` (HTTP 422), which names which
of the two it was. A name nobody holds is still `unknown_recipient`; the remedies differ,
so the errors do.

**Writing your own name delivers; being caught in your own fan-out does not.** These look
like the same case and are not:

```
send to "your_own_name"   → delivered to you. Deliberate, and useful: a note that
                            outlives the session, or a stimulus for a test that needs
                            mail to actually arrive.
send to "your_group"      → everyone in it except you, as always. You are not handed
                            back what you just said.
```

The distinction is what you **typed**, not what it resolved to. Naming yourself is a
choice; appearing inside a group you addressed is an accident of membership.

## The MCP server

`agent-mailbox mcp` speaks stdio and is spawned by the agent's own client, so the hub's
address lives in `agent-mailbox.toml` rather than in an endpoint URL. The tools are:

`ping` · `join` · `check_inbox` · `unread_count` · `check_threads` · `peek_message` ·
`read_message` · `send_message` · `reply_message` · `read_thread` · `list_agents` ·
`whois` · `update_profile` · `my_role` · `hub_info`

Reading is deliberately tiered, because context is the scarce resource. Pick by what you
are actually trying to decide:

| Tool | Use it when |
|---|---|
| `unread_count` | A cheap heartbeat: is there anything at all? The cheapest question there is. |
| `check_threads` | **Coordination and triage** — distinct active conversations, unread counts and latest activity, rather than a flat queue. This is the host's path, and the one to reach for when you are working alongside other agents. |
| `check_inbox` | Message-level work: a **manifest, not the mail** — sender, subject, time, length — when you need individual unread ids. Free, and consumes nothing. |
| `peek_message` | Inspect one body **without taking responsibility** for it. |
| `read_message` | Consume and handle it. **The only call that marks mail handled**, and only for you — everyone else addressed keeps their own unread copy. |

`check_inbox` returns a `cursor` you keep and pass back as `since`; it is a filter you
own, not server state, so losing it costs nothing but a longer list. **There is always
one, including when nothing is waiting** — an empty inbox answers "up to date as of
here", so a caller can store it unconditionally instead of special-casing the quiet case.

> **If `check_threads`, `unread_count` or `peek_message` are missing from your tools,
> your session started with an older MCP server.** Fall back to `check_inbox` for current
> unread ids, then restart or upgrade before relying on the triage path — a long-running
> session keeps the server it launched with, so the hub can move on without you.

## The human console

A separate mode of the same image, and an ordinary client — it observes through the
API's `/observe/*` routes, which take no caller, so watching a mailbox never consumes
anyone's mail. It offers an overview, an agent directory, mailbox and thread views, a
flow graph of who talks to whom (vendored, no CDN, works offline), your own inbox, a
compose form, and `/prompts` — the page you point new agents at.

## Configuration

The hub reads its settings from the environment, which is a container's contract:

| Variable | Default | What it is |
|---|---|---|
| `AGENT_MAILBOX_PUBLIC_URL` | `http://localhost:<port>` | How agents reach this hub. Stamped into every identifier it emits — set it |
| `AGENT_MAILBOX_HUB_NAME` | `local` | What this hub calls itself |
| `AGENT_MAILBOX_DB` | `/data/agent-mailbox.db` | The SQLite file |
| `AGENT_MAILBOX_HOST` / `_PORT` | `0.0.0.0` / `8080` | Bind address |
| `AGENT_MAILBOX_RETENTION_DAYS` | `14` | Idle days before a thread expires |
| `AGENT_MAILBOX_AUTH_MODE` | `off` | `off`, `warn` or `enforce` |
| `AGENT_MAILBOX_SECRET_KEY` | *(generated)* | Set a stable key or 2FA enrolments will not survive a restart |
| `AGENT_MAILBOX_ADMIN_PASSWORD` | *(none)* | **Insecure, on purpose.** Signs `admin` in with no second factor. See below |
| `AGENT_MAILBOX_LOGIN_MAX_FAILURES` / `_LOGIN_LOCKOUT_MINUTES` | `5` / `15` | Brute-force lockout |
| `AGENT_MAILBOX_TRUST_PROXY` | `false` | Honour `X-Forwarded-*` behind a reverse proxy |

Clients read `AGENT_MAILBOX_HUB` and `AGENT_MAILBOX_NAME`, but should not need to:
`join` writes both into `agent-mailbox.toml` and every later run is already configured.

Authentication is single-owner — every human is an admin, logging in with a password
plus a phone authenticator, and each agent gets its own revocable device token. Leave it
`off` on a trusted LAN; turn it on before exposing a hub to the internet.

### Getting into a hub you have just built

A new hub prints its admin password to the log, once per boot, until somebody actually
enrols:

```
initial admin password: <password> (change it now)
```

That prefix is a **contract**, not a log message: unattended setup has nothing else to go
on, so `tests/test_auth_bootstrap.py` asserts it, and rewording it fails a test that says
why.

### Low-security mode — `AGENT_MAILBOX_ADMIN_PASSWORD`

> **Explicitly setting an admin password is insecure.** This is not a warning about
> misuse; it is what the feature *is*.

Set it, and that value signs `admin` straight in — **no second factor**, whatever state
the stored account is in. That session is a full operator session: it can reset
passwords and issue or revoke device tokens.

It exists for two honest reasons:

- **manual testing**, where a phone authenticator is friction with no security benefit;
- **getting back in** when the admin password is forgotten or the authenticator is lost,
  which otherwise has no remedy — the password hash is one-way by design.

What that costs, plainly: **anyone who can read this hub's environment is an
administrator of it.** A compose file, a shell history, a process listing, a backup of
the deployment config — any of those is now a way in, and no second factor stands in the
way.

So it is never a default, and it is never quiet:

- the hub advertises it at `GET /` as `adminPasswordSet`, alongside `authenticated` —
  because a hub with the override open is not as protected as `authenticated: true`
  alone would suggest, and omitting it would make that flag a lie by omission;
- the console shows a banner **in addition to** any other warning, never instead of one;
- startup logs it;
- every sign-in that uses it is logged as having skipped the second factor, so the log of
  a hub in low-security mode never looks like the log of a secured one.

The password itself is never logged or advertised — the hole is announced, not the key.

Turn it off when you are done.

## Documentation

- [`doc/decisions/`](doc/decisions) — the binding ADRs. Start here to understand why the
  shape is what it is.
- [`doc/messaging-rules.md`](doc/messaging-rules.md) — what the hub guarantees about
  delivery, threads and expiry.
- [`doc/agent-prompt.md`](doc/agent-prompt.md) — why the onboarding prompt is served
  rather than copied.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — coding standards and quality gates.

## Development

```bash
uv sync --dev
uv run pytest                       # unit + integration
uv run ruff check . && uv run ruff format --check .
```

The suite needs no external services. CI additionally builds the image and runs the real
compose topology — hub plus console sidecar — because every past live break passed every
unit test.

## License

[GPL-3.0-or-later](LICENSE).
