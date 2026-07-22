"""The JetStream-backed mailbox — the single core all surfaces (CLI, MCP) share."""

from __future__ import annotations

import json
import logging
from types import TracebackType

import nats
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.errors import NoServersError
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, StreamConfig
from nats.js.errors import NotFoundError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent_mail.config import (
    MAIL_SUBJECT_PREFIX,
    STREAM_NAME,
    Config,
    durable_name,
    mail_subject,
    notify_subject,
)
from agent_mail.exceptions import MailboxError
from agent_mail.models import Intent, Message

logger = logging.getLogger(__name__)

# How many messages a single fetch round asks for, and the overall ceiling when
# draining a mailbox. Comfortably above any realistic local agent backlog.
_FETCH_BATCH = 64
_FETCH_MAX = 1024
_FETCH_TIMEOUT = 1.0


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
    retry=retry_if_exception_type((NoServersError, OSError)),
    reraise=True,
)
async def _connect(nats_url: str) -> NatsClient:
    """Open a NATS connection, retrying transient failures (server still booting)."""
    return await nats.connect(nats_url)


class Mailbox:
    """Durable inbox + wake signals over NATS JetStream.

    Use as an async context manager::

        async with Mailbox(config) as mb:
            await mb.send(msg)

    Connection and stream creation are idempotent; opening a second mailbox against
    the same NATS server reuses the existing ``AGENT_MAIL`` stream and per-agent
    durable consumers.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._nc: NatsClient | None = None
        self._js: JetStreamContext | None = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        """Open the NATS connection and ensure the mailbox stream exists."""
        if self._nc is not None:
            return
        logger.debug("connecting to NATS at %s", self._config.nats_url)
        self._nc = await _connect(self._config.nats_url)
        self._js = self._nc.jetstream()
        await self._ensure_stream()

    async def close(self) -> None:
        """Close the NATS connection.

        Tries a graceful drain first, but falls back to a hard close if draining a
        pull subscription hangs (which JetStream can do) — either way the socket is
        released.
        """
        nc = self._nc
        if nc is not None:
            try:
                await nc.drain()
            except Exception:
                if not nc.is_closed:
                    await nc.close()
            self._nc = None
            self._js = None

    async def __aenter__(self) -> Mailbox:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    # -- internals ---------------------------------------------------------

    @property
    def _stream(self) -> JetStreamContext:
        if self._js is None:
            raise MailboxError("mailbox is not connected; call connect() first")
        return self._js

    @property
    def _conn(self) -> NatsClient:
        if self._nc is None:
            raise MailboxError("mailbox is not connected; call connect() first")
        return self._nc

    async def _ensure_stream(self) -> None:
        """Create the ``AGENT_MAIL`` stream if it does not already exist."""
        js = self._stream
        try:
            await js.stream_info(STREAM_NAME)
        except NotFoundError:
            logger.info("creating JetStream stream %s", STREAM_NAME)
            await js.add_stream(
                StreamConfig(
                    name=STREAM_NAME,
                    subjects=[f"{MAIL_SUBJECT_PREFIX}.*"],
                )
            )

    async def _subscribe(self, agent_id: str) -> JetStreamContext.PullSubscription:
        """Bind (creating if needed) the per-agent durable pull consumer."""
        js = self._stream
        durable = durable_name(agent_id)
        return await js.pull_subscribe(
            subject=mail_subject(agent_id),
            durable=durable,
            config=ConsumerConfig(durable_name=durable),
        )

    @staticmethod
    async def _drain_pending(
        sub: JetStreamContext.PullSubscription,
    ) -> list[Msg]:
        """Fetch every currently-pending message without acking it.

        Returned objects are live JetStream messages, held in-flight (ack-pending)
        until the caller acks or naks each one.
        """
        collected: list[Msg] = []
        while len(collected) < _FETCH_MAX:
            try:
                batch = await sub.fetch(batch=_FETCH_BATCH, timeout=_FETCH_TIMEOUT)
            except NatsTimeoutError:
                break
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < _FETCH_BATCH:
                break
        return collected

    # -- verbs -------------------------------------------------------------

    async def send(self, message: Message) -> Message:
        """Publish ``message`` to its recipient's durable mailbox."""
        js = self._stream
        await js.publish(mail_subject(message.to), message.to_json_bytes())
        logger.debug("sent %s -> %s (%s)", message.from_, message.to, message.id)
        return message

    async def peek(self, agent_id: str) -> list[Message]:
        """Return unread messages for ``agent_id`` without consuming them.

        Every fetched message is nak'd so it remains unread and is redelivered on the
        next peek/read.
        """
        sub = await self._subscribe(agent_id)
        raw = await self._drain_pending(sub)
        messages: list[Message] = []
        for msg in raw:
            messages.append(Message.from_json_bytes(msg.data))
            await msg.nak()
        messages.sort(key=lambda m: m.created)
        return messages

    async def read(self, agent_id: str, message_id: str) -> Message:
        """Return the message with ``message_id`` and ack (consume) it.

        Other pending messages are nak'd so they stay unread. Raises
        :class:`MailboxError` if no unread message matches.
        """
        sub = await self._subscribe(agent_id)
        raw = await self._drain_pending(sub)
        found: Message | None = None
        for msg in raw:
            parsed = Message.from_json_bytes(msg.data)
            if found is None and parsed.id == message_id:
                found = parsed
                await msg.ack()
            else:
                await msg.nak()
        if found is None:
            raise MailboxError(
                f"no unread message with id {message_id!r} in {agent_id}'s inbox"
            )
        logger.debug("read %s from %s inbox", message_id, agent_id)
        return found

    async def reply(
        self,
        agent_id: str,
        message_id: str,
        body: str,
        subject: str | None = None,
    ) -> Message:
        """Consume message ``message_id`` and send a threaded reply to its sender."""
        original = await self.read(agent_id, message_id)
        reply_subject = subject or _reply_subject(original.subject)
        reply = Message(
            from_=agent_id,
            to=original.from_,
            thread=original.thread or original.id,
            intent=Intent.reply,
            subject=reply_subject,
            body=body,
        )
        return await self.send(reply)

    async def notify(self, recipient: str, thread: str | None = None) -> None:
        """Publish a lightweight, non-durable 'you have mail' wake for ``recipient``."""
        payload = json.dumps({} if thread is None else {"thread": thread}).encode()
        await self._conn.publish(notify_subject(recipient), payload)
        await self._conn.flush()
        logger.debug("notified %s", recipient)


def _reply_subject(subject: str) -> str:
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"
