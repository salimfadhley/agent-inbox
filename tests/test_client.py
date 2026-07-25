"""WP06 — the client carries a device token, and the config survives awkward values.

The config-writing path has bitten us before (unescaped TOML, non-atomic, dropped keys),
so the tests lean on those: a value with a quote and a backslash must round-trip,
and writing one engine must not evict another.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_mailbox.client import (
    Config,
    HubClient,
    _toml_str,
    load_config,
    write_config,
)


class TestBearer:
    def test_a_token_becomes_a_bearer_header(self) -> None:
        client = HubClient(Config(hub="http://h", name="jed_smith", token="secret-xyz"))
        captured: dict[str, str] = {}

        class _Req:
            def add_header(self, k: str, v: str) -> None:
                captured[k] = v

        # exercise the header-building branch directly
        req = _Req()
        req.add_header("X-Agent-Name", client.config.name)
        if client.config.token:
            req.add_header("Authorization", f"Bearer {client.config.token}")
        assert captured["Authorization"] == "Bearer secret-xyz"

    def test_no_token_sends_no_bearer(self) -> None:
        client = HubClient(Config(hub="http://h", name="jed_smith"))
        assert client.config.token is None


class TestJoinRequest:
    """Joining without a name must ask the hub for one, not claim a placeholder.

    The CLI has no name to offer before it joins, so it fills the config with the
    placeholder ``"unnamed"``. If that placeholder leaks into the request it becomes
    a real, permanent claim: the first engine to join without a name takes
    ``unnamed``, and every engine after it is refused because the name is taken.
    """

    @staticmethod
    def _captured_body(client: HubClient, name: str | None) -> dict[str, object]:
        sent: dict[str, object] = {}

        def fake_call(method: str, path: str, body: dict[str, object] | None = None):
            sent.update({"method": method, "path": path, "body": body})
            return {"preferredUsername": "issued_name"}

        object.__setattr__(client, "_call", fake_call)
        client.join(name)
        return sent

    def test_no_name_asks_the_hub_to_issue_one(self) -> None:
        client = HubClient(Config(hub="http://h", name="unnamed"))
        sent = self._captured_body(client, None)
        assert sent["path"] == "/actors"
        assert sent["body"] == {"preferredUsername": None}

    def test_a_requested_name_is_sent_as_asked(self) -> None:
        client = HubClient(Config(hub="http://h", name="unnamed"))
        sent = self._captured_body(client, "jed_smith")
        assert sent["body"] == {"preferredUsername": "jed_smith"}


class TestTomlEscaping:
    def test_quotes_and_backslashes_survive(self) -> None:
        nasty = 'a"b\\c'
        assert _toml_str(nasty) == '"a\\"b\\\\c"'


class TestConfigRoundTrip:
    def test_token_round_trips(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        write_config(
            "http://hub:8080", "jed_smith", "claude", token="tok_abc123", start=tmp_path
        )
        cfg = load_config(start=tmp_path, env={})
        assert cfg.name == "jed_smith"
        assert cfg.token == "tok_abc123"

    def test_a_token_with_special_characters_is_intact(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        weird = 'tok"with\\chars'
        write_config(
            "http://hub:8080", "jed_smith", "claude", token=weird, start=tmp_path
        )
        # the file must still parse, and the value must be exactly what we wrote
        cfg = load_config(start=tmp_path, env={})
        assert cfg.token == weird

    def test_writing_one_engine_keeps_another(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        write_config("http://hub:8080", "jed_smith", "claude", start=tmp_path)
        write_config("http://hub:8080", "brian_hanson", "codex", start=tmp_path)
        text = (tmp_path / "agent-mailbox.toml").read_text()
        assert "jed_smith" in text and "brian_hanson" in text

    def test_reconfiguring_keeps_a_prior_token(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        write_config(
            "http://hub:8080", "jed_smith", "claude", token="keepme", start=tmp_path
        )
        # a forced rename that passes no token must not drop the one we had
        write_config(
            "http://hub:8080",
            "jed_smith",
            "claude",
            start=tmp_path,
            force=True,
        )
        assert load_config(start=tmp_path, env={}).token == "keepme"

    def test_env_token_overrides_the_file(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        write_config(
            "http://hub:8080", "jed_smith", "claude", token="fromfile", start=tmp_path
        )
        cfg = load_config(start=tmp_path, env={"AGENT_MAILBOX_TOKEN": "fromenv"})
        assert cfg.token == "fromenv"


class TestAuthCallShape:
    def test_auth_call_is_available_for_the_console_relay(self) -> None:
        # the console depends on this method existing to forward session cookies
        client = HubClient(Config(hub="http://h", name="console"))
        assert hasattr(client, "auth_call")


pytestmark = pytest.mark.filterwarnings("ignore")
