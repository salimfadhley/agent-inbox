"""Batch inspection, batch replies with per-item outcomes, and safe retry (#67).

An agent with twelve pending messages read them in one call; the transport timed out
after the hub had consumed them; the agent wrote its own loop and delivery ledger to
reply one by one, and one reply ended in a state nobody could name. Every step used
advertised tools. What was missing was a bounded, recoverable batch shape — and a
retry that cannot send twice.

The retry is client-side by the owner's decision (2026-09-15): before sending, the MCP
looks on the thread for the caller's own reply to that original with that exact body.
A reply the hub stored whose receipt was lost is exactly what that finds.
"""

import json
from typing import Any

import anyio
import pytest
from fastmcp import Client

from agent_inbox import mcp_client
from agent_inbox.client import ClientError, Config

HUB = "https://hub.example"


class FakeHub:
    """A hub with a thread store, a per-id inbox, and a switch that loses a response
    *after* storing the reply — the lost-receipt case."""

    def __init__(self) -> None:
        self.config = Config(hub=HUB, name="nicole_ruzickova", role="agent")
        self.notes: dict[str, dict[str, Any]] = {}
        self.sent: list[dict[str, Any]] = []
        self.lose_next_receipt = False
        self.thread_fails = False
        self.peeked: list[str] = []
        for n in range(1, 4):
            oid = f"{HUB}/objects/orig{n}"
            self.notes[oid] = {
                "id": oid,
                "attributedTo": f"{HUB}/actors/trevor_mahmood",
                "to": [f"{HUB}/actors/nicole_ruzickova"],
                "summary": f"question {n}",
                "content": f"body {n}",
                "published": "2026-09-15T09:00:00+00:00",
                "inReplyTo": None,
            }

    def peek_message(self, object_id: str) -> dict[str, Any]:
        self.peeked.append(object_id)
        if object_id not in self.notes:
            raise ClientError(f"no such message {object_id}")
        return self.notes[object_id]

    def read_thread(self, object_id: str) -> dict[str, Any]:
        if self.thread_fails:
            raise ClientError("hub took the connection and went quiet")
        return {"items": list(self.notes.values()), "totalItems": len(self.notes)}

    def reply_message(
        self, object_id: str, body: str, subject: str | None = None
    ) -> dict[str, Any]:
        if object_id not in self.notes:
            raise ClientError(f"no such message {object_id}")
        rid = f"{HUB}/objects/reply{len(self.sent) + 1}"
        note = {
            "id": rid,
            "attributedTo": f"{HUB}/actors/nicole_ruzickova",
            "to": [self.notes[object_id]["attributedTo"]],
            "summary": f"Re: {self.notes[object_id]['summary']}",
            "content": body,
            "published": "2026-09-15T09:05:00+00:00",
            "inReplyTo": object_id,
        }
        self.notes[rid] = note
        self.sent.append(note)
        if self.lose_next_receipt:
            self.lose_next_receipt = False
            raise ClientError("timed out waiting for the hub")
        return note


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> FakeHub:
    fake = FakeHub()
    monkeypatch.setattr(mcp_client, "_client", lambda: fake)
    monkeypatch.setattr(mcp_client, "_roots_asked", True)
    monkeypatch.setattr(mcp_client, "_start_listening", lambda: None)
    return fake


def call(tool: str, **args: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(mcp_client.mcp) as client:
            result = await client.call_tool(tool, args)
            data = getattr(result, "data", None)
            if isinstance(data, dict):
                return data
            return json.loads(result.content[0].text)  # type: ignore[union-attr]

    return anyio.run(go)


def orig(n: int) -> str:
    return f"{HUB}/objects/orig{n}"


class TestInspectingSeveralWithoutConsuming:
    def test_several_ids_come_back_as_items_with_completeness(
        self, hub: FakeHub
    ) -> None:
        out = call("peek_message", message_id=f"{orig(1)}, {orig(2)}")

        assert out["requested"] == 2 and out["returned"] == 2
        assert out["complete"] is True and out["failed"] == []
        assert [m["body"] for m in out["messages"]] == ["body 1", "body 2"]

    def test_a_bad_id_fails_alone(self, hub: FakeHub) -> None:
        out = call("peek_message", message_id=f"{orig(1)},{HUB}/objects/nope")

        assert out["returned"] == 1
        assert out["failed"] == [f"{HUB}/objects/nope"]
        assert out["messages"][1]["status"] == "failed"

    def test_past_the_cap_is_said_not_dropped(self, hub: FakeHub) -> None:
        ids = ",".join(f"{HUB}/objects/x{i}" for i in range(mcp_client.BATCH_CAP + 3))

        out = call("peek_message", message_id=ids)

        assert out["complete"] is False
        assert len(out["not_attempted"]) == 3
        # The premise: the cap actually bounded the calls made.
        assert len(hub.peeked) == mcp_client.BATCH_CAP

    def test_one_id_keeps_the_single_shape(self, hub: FakeHub) -> None:
        out = call("peek_message", message_id=orig(1))

        assert out["body"] == "body 1" and "requested" not in out


class TestBatchRepliesReportPerItem:
    def test_each_original_gets_its_own_outcome(self, hub: FakeHub) -> None:
        out = call(
            "reply_messages",
            replies=[
                {"message_id": orig(1), "body": "answer 1"},
                {"message_id": f"{HUB}/objects/nope", "body": "answer ?"},
                {"message_id": orig(2), "body": "answer 2"},
            ],
        )

        assert out["requested"] == 3
        assert out["delivered"] == 2 and out["failed"] == 1
        assert out["complete"] is True
        outcomes = [r["outcome"] for r in out["results"]]
        assert outcomes == ["delivered", "failed", "delivered"]
        assert out["results"][0]["receipt"]["in_reply_to"] == orig(1)
        assert len(hub.sent) == 2

    def test_the_same_id_twice_in_a_batch_is_sent_once(self, hub: FakeHub) -> None:
        out = call(
            "reply_messages",
            replies=[
                {"message_id": orig(1), "body": "a"},
                {"message_id": orig(1), "body": "b"},
            ],
        )

        assert [r["outcome"] for r in out["results"]] == ["delivered", "duplicate"]
        assert len(hub.sent) == 1

    def test_past_the_cap_is_not_attempted_and_the_batch_is_incomplete(
        self, hub: FakeHub
    ) -> None:
        replies = [
            {"message_id": f"{HUB}/objects/x{i}", "body": "x"}
            for i in range(mcp_client.BATCH_CAP + 2)
        ]

        out = call("reply_messages", replies=replies)

        assert out["not_attempted"] == 2 and out["complete"] is False

    def test_an_item_without_a_body_fails_alone(self, hub: FakeHub) -> None:
        out = call(
            "reply_messages",
            replies=[{"message_id": orig(1)}, {"message_id": orig(2), "body": "ok"}],
        )

        assert [r["outcome"] for r in out["results"]] == ["failed", "delivered"]


class TestRetryAfterALostResponseSendsNothingTwice:
    """**The load-bearing property.** A reply the hub stored, whose receipt was lost in
    transit, must be recovered by the retry — not sent again."""

    def test_the_stored_reply_is_found_and_nothing_is_resent(
        self, hub: FakeHub
    ) -> None:
        hub.lose_next_receipt = True
        first = call("reply_messages", replies=[{"message_id": orig(1), "body": "hi"}])
        assert first["results"][0]["outcome"] == "failed"  # the receipt was lost
        assert len(hub.sent) == 1  # …but the hub stored it

        second = call("reply_messages", replies=[{"message_id": orig(1), "body": "hi"}])

        assert second["results"][0]["outcome"] == "duplicate"
        assert second["results"][0]["receipt"]["id"] == hub.sent[0]["id"]
        assert len(hub.sent) == 1

    def test_a_hundred_retries_produce_one_message(self, hub: FakeHub) -> None:
        hub.lose_next_receipt = True
        for _ in range(100):
            call("reply_messages", replies=[{"message_id": orig(1), "body": "hi"}])

        assert len(hub.sent) == 1

    def test_a_different_body_is_a_new_turn_and_goes(self, hub: FakeHub) -> None:
        call("reply_message", message_id=orig(1), body="doing it")

        out = call("reply_message", message_id=orig(1), body="done now")

        assert out.get("outcome") != "duplicate"
        assert [n["content"] for n in hub.sent] == ["doing it", "done now"]

    def test_the_single_tool_is_safe_to_retry_too(self, hub: FakeHub) -> None:
        hub.lose_next_receipt = True
        call("reply_message", message_id=orig(2), body="once")

        out = call("reply_message", message_id=orig(2), body="once")

        assert out["outcome"] == "duplicate"
        assert out["id"] == hub.sent[0]["id"]
        assert len(hub.sent) == 1

    def test_when_the_thread_cannot_be_checked_nothing_is_sent(
        self, hub: FakeHub
    ) -> None:
        """Unknown means not sent. Guessing in the direction of sending is the one
        thing a retry must never do."""
        hub.thread_fails = True

        out = call("reply_messages", replies=[{"message_id": orig(1), "body": "hi"}])

        assert out["results"][0]["outcome"] == "unknown"
        assert out["unknown"] == 1
        assert hub.sent == []


class TestTheSingleToolKeepsItsShape:
    def test_a_delivered_reply_returns_the_receipt_as_before(
        self, hub: FakeHub
    ) -> None:
        out = call("reply_message", message_id=orig(1), body="hello")

        assert out["in_reply_to"] == orig(1)
        assert out["body"] == "hello"
        assert "outcome" not in out

    def test_guidance_separates_unread_from_unanswered(self) -> None:
        doc = mcp_client.reply_message.__doc__ or ""

        assert "Unread is not unanswered" in doc
        assert "needs no" in doc and "acknowledgement" in doc
        assert "Safe to retry" in doc
