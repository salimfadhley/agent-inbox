"""agent-inbox — a SQLite mailbox for local LLM agents.

One HTTP API is the hub's only machine interface; the CLI, a local stdio MCP server
and the human console are all clients of it. The messaging model follows
ActivityStreams, and identity is issued by the hub rather than derived from facts.

The binding decisions live in ``doc/decisions/``:

* ADR 0003 — identity is a surrogate key, not a natural key
* ADR 0004 — the messaging model follows ActivityStreams
* ADR 0005 — one API; every client is a client
* ADR 0006 — SQLite, with typed columns plus a document column

This package is written from scratch. The superseded implementation is kept at
``agent_inbox_old`` for historical reference only and is deleted once this one is
green; nothing here may import from it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    # The *distribution* name, which is not the import package's name: the project is
    # `agent-inbox` on PyPI and always has been. Getting this wrong does not raise —
    # it silently reports 0.0.0.dev0 forever — and the onboarding prompt now asks
    # agents to compare this number against the hub's, so a silent 0.0.0 would tell
    # every one of them to reinstall on every session.
    __version__ = version("agent-inbox")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
