# AGENTS.md — governance for agent-mail

This file is the project charter for any human or AI agent working on `agent-mail`.

## Coding standards (the baseline)

`agent-mail` adopts the canonical coding standards in
[`docs/coding-standards.md`](docs/coding-standards.md). Read them before contributing.
The points that shape this codebase:

- **Type annotations everywhere**, modern syntax (`str | None`, `list[str]`).
- **Absolute imports** (`from agent_mail.x import y`), except re-exports in
  `__init__.py`.
- **Specific exceptions.** A project hierarchy lives in
  [`src/agent_mail/exceptions.py`](src/agent_mail/exceptions.py) (`AgentMailError`
  base). Throw the most specific type; catch narrowly. `except Exception:` only at
  process boundaries.
- **Logging, not `print`.** Module loggers (`logging.getLogger(__name__)`). CLI
  user-facing output uses `click.echo`, and also logs.
- **Config through one object** — `agent_mail.config.Config` (pydantic-settings).
  No scattered environment-specific module constants.
- **Retries via `tenacity`** for transient IO (e.g. the NATS connect).
- **Immutable data** where practical (frozen `Config`).
- **pytest** in `/tests`; **ruff** for lint+format; **pyright** for types; **uv** for
  everything.

Project-specific overrides to the baseline, if any, are recorded here. (None today.)

## Quality gates

Work is not done until all of these pass — CI enforces them:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Project-specific rules

- **Generic only.** `agent-mail` is releasable, general-purpose infrastructure. No
  deployment-specific hostnames, IPs, tokens, or organisation names in code, docs, or
  tests. Agent names are configuration.
- **One core.** The CLI and the MCP server must both delegate to
  `agent_mail.mailbox.Mailbox`. No logic duplication across surfaces.
- **Durability is JetStream's job.** Rely on JetStream acks for persistence and
  idempotency; a redelivered message must not be double-processed.

## Using agent-mail while building agent-mail

If you are an agent participating in inter-agent mail, see
[`docs/agent-onboarding.md`](docs/agent-onboarding.md).
