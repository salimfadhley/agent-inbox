"""agent-inbox — a local SQLite mailbox for local LLM agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from agent_inbox.config import Config
from agent_inbox.exceptions import (
    AgentInboxError,
    AgentMailError,  # deprecated alias
    ConfigError,
    MailboxError,
)
from agent_inbox.mailbox import Mailbox
from agent_inbox.models import Intent, Message

try:
    __version__ = version("agent-inbox")
except PackageNotFoundError:  # pragma: no cover - source checkout without metadata
    __version__ = "0.0.0"


def main(argv: list[str] | None = None) -> None:
    """Console entry point (kept importable as ``agent_inbox.main``)."""
    from agent_inbox.cli import main as _main

    _main(argv)


__all__ = [
    "AgentInboxError",
    "AgentMailError",
    "Config",
    "ConfigError",
    "Intent",
    "Mailbox",
    "MailboxError",
    "Message",
    "__version__",
    "main",
]
