# syntax=docker/dockerfile:1
#
# agent-inbox — the hub.
#
# One HTTP API in ActivityStreams, over a SQLite file. Every other surface — the CLI,
# a local MCP server, the web console — is a client of this, not part of it, so none of
# them is in this image.
#
# Storage is a single file at /data/agent-mailbox.db; mount a volume at /data so mail
# survives restarts. No external services.
#
# Build:  docker build -t agent-inbox .
# Run:    docker run -p 8080:8080 -v agent-mailbox-data:/data \
#           -e AGENT_INBOX_PUBLIC_URL=http://<host>:8080 agent-inbox

FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# hatch-vcs takes the version from git, and there is no .git in the build context.
ARG VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# No extras. The `clients` extra pulls in mcp, and with it pydantic and starlette —
# which the API deliberately does not use (ADR 0009). The hub ships four dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable


FROM python:3.14-slim AS runtime

RUN useradd --create-home --uid 10001 agentmailbox
COPY --from=build --chown=agentmailbox:agentmailbox /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    AGENT_INBOX_HOST=0.0.0.0 \
    AGENT_INBOX_PORT=8080 \
    AGENT_INBOX_DB=/data/agent-mailbox.db

# AGENT_INBOX_PUBLIC_URL is deliberately not defaulted here: the hub cannot guess how
# it is reached, and a wrong answer would be baked into every identifier it emits.
# Left unset it falls back to localhost, which is at least honest.

RUN mkdir -p /data && chown agentmailbox:agentmailbox /data
VOLUME ["/data"]

USER agentmailbox
EXPOSE 8080

# Health does not touch the database on purpose, so a wedged store is reported by the
# routes that need it rather than hidden behind a check that hangs too.
#
# The port is read at runtime rather than baked in, because this image runs in two modes
# and they do not listen on the same port. Hardcoding 8080 left the console sidecar
# permanently `unhealthy` — it serves fine on 8090, and nothing was ever wrong with it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('AGENT_INBOX_HEALTH_PORT') or os.environ.get('AGENT_INBOX_PORT') or '8080'; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/health').status==200 else 1)"

# One command, several modes. This must track [project.scripts]: unifying the entry
# points once broke the image because this line still named a console script that no
# longer existed, and the container could be created but never started.
#
# The mode is CMD, not part of ENTRYPOINT, so `docker run <image> console --host 0.0.0.0`
# selects a different mode instead of being appended to `serve` and rejected. That is
# what makes the console sidecar work from this same image without an --entrypoint
# override — which is the point being made: it is the same program, run elsewhere.
ENTRYPOINT ["agent-inbox"]
CMD ["serve"]
