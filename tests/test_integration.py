"""Live round-trip against real JetStream. Gated behind AGENT_MAIL_INTEGRATION=1.

Run with::

    AGENT_MAIL_INTEGRATION=1 uv run pytest tests/test_integration.py
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from agent_mail.config import Config
from agent_mail.mailbox import Mailbox
from agent_mail.models import Intent, Message

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENT_MAIL_INTEGRATION") != "1",
    reason="set AGENT_MAIL_INTEGRATION=1 to run live JetStream tests",
)


async def test_send_peek_read_reply_roundtrip() -> None:
    # Unique agent ids per run so the durable consumers start empty.
    suffix = uuid4().hex[:8]
    alice = f"itest-alice-{suffix}"
    bob = f"itest-bob-{suffix}"
    config = Config.from_env()

    async with Mailbox(config) as mailbox:
        original = Message(
            from_=alice,
            to=bob,
            subject="ping",
            body="are you there?",
        )
        await mailbox.send(original)

        # peek does not consume: bob still sees it twice
        first_peek = await mailbox.peek(bob)
        assert any(m.id == original.id for m in first_peek)
        second_peek = await mailbox.peek(bob)
        assert any(m.id == original.id for m in second_peek)

        # read consumes it
        read_back = await mailbox.read(bob, original.id)
        assert read_back.body == "are you there?"
        assert await mailbox.peek(bob) == []

        # send again and reply — reply should land in alice's inbox, threaded
        second = Message(from_=alice, to=bob, subject="ping2", body="q")
        await mailbox.send(second)
        reply = await mailbox.reply(bob, second.id, "yes, here")
        assert reply.intent is Intent.reply
        assert reply.thread == second.thread

        alice_inbox = await mailbox.peek(alice)
        assert any(m.id == reply.id and m.body == "yes, here" for m in alice_inbox)
        # clean up alice's inbox
        await mailbox.read(alice, reply.id)


async def test_notify_publishes() -> None:
    config = Config.from_env()
    async with Mailbox(config) as mailbox:
        # notify is fire-and-forget; success is simply not raising.
        await mailbox.notify(f"itest-{uuid4().hex[:8]}")
