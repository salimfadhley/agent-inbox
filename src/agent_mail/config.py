"""Runtime configuration for agent-mail, sourced from the environment.

All environment-specific settings flow through the single :class:`Config` object
(pydantic-settings), rather than being scattered as module-level constants. The only
module-level constants here are protocol invariants (stream name, subject prefixes)
that are the same on every deployment.
"""

from __future__ import annotations

import logging
import re

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_mail.exceptions import ConfigError

logger = logging.getLogger(__name__)

DEFAULT_NATS_URL = "nats://127.0.0.1:4222"
"""Default JetStream endpoint. Point ``NATS_URL`` at your own server to override."""

STREAM_NAME = "AGENT_MAIL"
"""JetStream stream that durably stores every mailbox message."""

MAIL_SUBJECT_PREFIX = "agent.mail"
"""Subjects are ``agent.mail.<recipient>``; the stream binds ``agent.mail.*``."""

NOTIFY_SUBJECT_PREFIX = "agent.notify"
"""Non-durable wake signals are published on ``agent.notify.<recipient>``."""

_VALID_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_agent_id(agent_id: str) -> str:
    """Return ``agent_id`` unchanged if it is a safe NATS subject token, else raise.

    Agent ids become part of a NATS subject and a JetStream durable name, so they
    must not contain dots, spaces or wildcards.
    """
    if not _VALID_AGENT_ID.match(agent_id):
        raise ConfigError(
            f"invalid agent id {agent_id!r}: use letters, digits, '-' or '_' "
            "(no dots, spaces or wildcards), max 64 chars"
        )
    return agent_id


def mail_subject(recipient: str) -> str:
    """Return the durable mailbox subject for ``recipient``."""
    return f"{MAIL_SUBJECT_PREFIX}.{validate_agent_id(recipient)}"


def notify_subject(recipient: str) -> str:
    """Return the ephemeral wake-signal subject for ``recipient``."""
    return f"{NOTIFY_SUBJECT_PREFIX}.{validate_agent_id(recipient)}"


def durable_name(agent_id: str) -> str:
    """Return the per-agent JetStream durable consumer name."""
    return f"mail-{validate_agent_id(agent_id)}"


class Config(BaseSettings):
    """Resolved connection, identity and server settings.

    Values are read from the environment (and an optional ``.env`` file) once, at
    construction. ``Config`` is frozen: to vary a field, build a copy with
    :meth:`~pydantic.BaseModel.model_copy`.
    """

    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    nats_url: str = Field(default=DEFAULT_NATS_URL, validation_alias="NATS_URL")
    agent_id: str | None = Field(default=None, validation_alias="AGENT_ID")

    # MCP server (only used by ``agent-mail mcp-serve``).
    transport: str = Field(default="stdio", validation_alias="AGENT_MAIL_TRANSPORT")
    host: str = Field(default="127.0.0.1", validation_alias="AGENT_MAIL_HOST")
    port: int = Field(default=8080, validation_alias="AGENT_MAIL_PORT")
    path: str = Field(default="/mcp", validation_alias="AGENT_MAIL_PATH")

    @classmethod
    def from_env(cls, agent_override: str | None = None) -> Config:
        """Build config from the environment, letting ``agent_override`` win."""
        config = cls()
        if agent_override:
            config = config.model_copy(update={"agent_id": agent_override})
        return config

    def require_identity(self) -> str:
        """Return the validated agent id, or raise if none was configured."""
        if not self.agent_id:
            raise ConfigError("no agent identity: set AGENT_ID or pass --from <agent>")
        return validate_agent_id(self.agent_id)
