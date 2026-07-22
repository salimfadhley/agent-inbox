"""Pydantic message model for the agent mailbox."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _new_id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Intent(StrEnum):
    """Why a message was sent — drives how a recipient should treat it."""

    message = "message"
    reply = "reply"
    ack = "ack"
    actioned = "actioned"


class Message(BaseModel):
    """A single mailbox message.

    Serialised to JSON with the ``from`` alias so the wire format reads naturally;
    ``populate_by_name`` means callers may construct it with either ``from_`` or
    ``from``. Every message carries a ``thread`` — a brand-new message threads on
    its own id so replies have something to group on.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=_new_id)
    from_: str = Field(alias="from")
    to: str
    thread: str | None = None
    intent: Intent = Intent.message
    subject: str
    body: str
    created: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _default_thread_to_id(self) -> Message:
        if self.thread is None:
            # object is frozen? no — mutate directly.
            object.__setattr__(self, "thread", self.id)
        return self

    def to_json_bytes(self) -> bytes:
        """Serialise for publishing onto NATS (uses the ``from`` alias)."""
        return self.model_dump_json(by_alias=True).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: bytes) -> Message:
        """Parse a message off the wire."""
        return cls.model_validate_json(data)
