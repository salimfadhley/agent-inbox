"""Project-wide exception hierarchy.

Every failure agent-mail raises on purpose derives from :class:`AgentMailError`, so
callers (and the CLI / MCP process boundaries) can catch the whole family with one
``except`` while still being able to catch narrowly where they can recover.
"""

from __future__ import annotations


class AgentMailError(RuntimeError):
    """Base class for all deliberate agent-mail failures."""


class ConfigError(AgentMailError):
    """Configuration is missing or invalid (e.g. no agent identity, bad agent id)."""


class MailboxError(AgentMailError):
    """A mailbox operation failed (e.g. reading a message that is not there)."""
