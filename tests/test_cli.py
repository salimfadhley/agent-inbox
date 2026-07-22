"""CLI tests with NATS faked — exercises arg parsing and output, no live server."""

from __future__ import annotations

import json
from types import TracebackType

import pytest
from click.testing import CliRunner

from agent_mail import cli as cli_module
from agent_mail.models import Intent, Message


class FakeMailbox:
    """Records calls and returns canned data in place of the real Mailbox."""

    calls: list[tuple[str, tuple[object, ...]]] = []
    peek_result: list[Message] = []
    read_result: Message | None = None

    def __init__(self, config: object) -> None:
        self.config = config

    async def __aenter__(self) -> FakeMailbox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def send(self, message: Message) -> Message:
        FakeMailbox.calls.append(("send", (message,)))
        return message

    async def peek(self, agent_id: str) -> list[Message]:
        FakeMailbox.calls.append(("peek", (agent_id,)))
        return FakeMailbox.peek_result

    async def read(self, agent_id: str, message_id: str) -> Message:
        FakeMailbox.calls.append(("read", (agent_id, message_id)))
        assert FakeMailbox.read_result is not None
        return FakeMailbox.read_result

    async def reply(
        self, agent_id: str, message_id: str, body: str, subject: str | None = None
    ) -> Message:
        FakeMailbox.calls.append(("reply", (agent_id, message_id, body, subject)))
        return Message(
            from_=agent_id,
            to="peer",
            subject=subject or "Re: x",
            body=body,
            intent=Intent.reply,
        )

    async def notify(self, recipient: str, thread: str | None = None) -> None:
        FakeMailbox.calls.append(("notify", (recipient, thread)))

    async def ping(self, agent_id: str) -> Message:
        FakeMailbox.calls.append(("ping", (agent_id,)))
        return Message(
            from_=agent_id, to=agent_id, subject="agent-mail ping", body="ping"
        )


@pytest.fixture(autouse=True)
def patch_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeMailbox.calls = []
    FakeMailbox.peek_result = []
    FakeMailbox.read_result = None
    monkeypatch.setattr(cli_module, "Mailbox", FakeMailbox)
    monkeypatch.setenv("AGENT_ID", "tester")


def run(*args: str) -> object:
    return CliRunner().invoke(cli_module.cli, list(args))


def test_send_happy_path() -> None:
    result = run("send", "--to", "peer", "--subject", "hi", "--body", "there")
    assert result.exit_code == 0, result.output
    assert "sent" in result.output
    kind, payload = FakeMailbox.calls[-1]
    assert kind == "send"
    sent = payload[0]
    assert isinstance(sent, Message)
    assert sent.to == "peer" and sent.from_ == "tester"


def test_send_json_output() -> None:
    result = run("--json", "send", "--to", "peer", "--subject", "hi", "--body", "b")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["from"] == "tester"
    assert data["to"] == "peer"


def test_send_rejects_bad_intent() -> None:
    result = run(
        "send", "--to", "p", "--subject", "s", "--body", "b", "--intent", "nope"
    )
    assert result.exit_code != 0
    assert "nope" in result.output or "Invalid value" in result.output


def test_send_requires_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    result = CliRunner().invoke(
        cli_module.cli, ["send", "--to", "p", "--subject", "s", "--body", "b"]
    )
    assert result.exit_code == 1
    assert "agent identity" in result.output


def test_inbox_empty() -> None:
    result = run("inbox")
    assert result.exit_code == 0, result.output
    assert "inbox empty" in result.output
    assert FakeMailbox.calls[-1] == ("peek", ("tester",))


def test_inbox_lists_messages() -> None:
    FakeMailbox.peek_result = [
        Message(from_="peer", to="tester", subject="s1", body="b1", id="id-1"),
    ]
    result = run("inbox")
    assert result.exit_code == 0, result.output
    assert "id-1" in result.output
    assert "1 unread" in result.output


def test_read_shows_and_acks() -> None:
    FakeMailbox.read_result = Message(
        from_="peer", to="tester", subject="s", body="hello world", id="abc"
    )
    result = run("read", "abc")
    assert result.exit_code == 0, result.output
    assert "hello world" in result.output
    assert FakeMailbox.calls[-1] == ("read", ("tester", "abc"))


def test_reply_threads() -> None:
    result = run("reply", "abc", "--body", "roger")
    assert result.exit_code == 0, result.output
    assert "replied" in result.output
    kind, payload = FakeMailbox.calls[-1]
    assert kind == "reply"
    assert payload[:3] == ("tester", "abc", "roger")


def test_notify() -> None:
    result = run("notify", "--to", "peer")
    assert result.exit_code == 0, result.output
    assert "notified peer" in result.output
    assert FakeMailbox.calls[-1] == ("notify", ("peer", None))


def test_ping_ok() -> None:
    result = run("ping")
    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert FakeMailbox.calls[-1] == ("ping", ("tester",))


def test_ping_json_reports_ok() -> None:
    result = run("--json", "ping")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["agent"] == "tester"


def test_from_flag_overrides_identity() -> None:
    result = run(
        "--from", "other", "send", "--to", "p", "--subject", "s", "--body", "b"
    )
    assert result.exit_code == 0, result.output
    sent = FakeMailbox.calls[-1][1][0]
    assert isinstance(sent, Message)
    assert sent.from_ == "other"
