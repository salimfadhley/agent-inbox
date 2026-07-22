"""Unit tests for configuration and subject helpers."""

from __future__ import annotations

import pytest

from agent_mail.config import (
    Config,
    ConfigError,
    durable_name,
    mail_subject,
    notify_subject,
    validate_agent_id,
)


def test_from_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NATS_URL", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)
    config = Config.from_env()
    assert config.nats_url == "nats://127.0.0.1:4222"
    assert config.agent_id is None


def test_from_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ID", "env-agent")
    config = Config.from_env(agent_override="cli-agent")
    assert config.agent_id == "cli-agent"


def test_require_identity_raises_without_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ID", raising=False)
    with pytest.raises(ConfigError):
        Config.from_env().require_identity()


@pytest.mark.parametrize("bad", ["a.b", "has space", "wild*", "", "x/y"])
def test_invalid_agent_ids_rejected(bad: str) -> None:
    with pytest.raises(ConfigError):
        validate_agent_id(bad)


def test_subject_helpers() -> None:
    assert mail_subject("casework") == "agent.mail.casework"
    assert notify_subject("casework") == "agent.notify.casework"
    assert durable_name("casework") == "mail-casework"
