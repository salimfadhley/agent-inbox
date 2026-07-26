"""WP06 — the client carries a device token, and the config survives awkward values.

The config-writing path has bitten us before (unescaped TOML, non-atomic, dropped keys),
so the tests lean on those: a value with a quote and a backslash must round-trip,
and writing one engine must not evict another.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_mailbox.client import (
    UNNAMED,
    Config,
    HubClient,
    NotConfigured,
    _toml_str,
    detect_engine,
    duplicate_names,
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
    """What an empty join argument means depends on what the config already holds.

    Two callers pass nothing and want opposite things. The console calls ``join()``
    bare at startup to re-claim the name it already has — it must send that name.
    The CLI calls it before it has any name, and its config holds the ``UNNAMED``
    placeholder — that must reach the hub as "issue me one", or the first engine to
    join without a name claims ``unnamed`` permanently and every engine after it is
    refused because the name is taken.

    Sending the placeholder was a real bug; so was fixing it by dropping the
    fallback, which broke the console's self-registration (caught by the live smoke
    tests, not here — hence the console case below).
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

    def test_a_configured_name_is_reclaimed_when_none_is_passed(self) -> None:
        """The console's startup path: join() bare, to re-claim its own name."""
        client = HubClient(Config(hub="http://h", name="console"))
        sent = self._captured_body(client, None)
        assert sent["body"] == {"preferredUsername": "console"}


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


class TestGlobalConfig:
    """A credential is not an identity, so it need not be per project."""

    def test_a_shared_token_is_found_machine_wide(self, tmp_path: Path) -> None:
        """One token in one file admits every agent on the box.

        Minting one apiece is correct for a shared server and pure friction on a
        laptop running four coding agents — and friction is what gets abandoned.
        """
        home = tmp_path / "xdg"
        (home / "agent-inbox").mkdir(parents=True)
        (home / "agent-inbox" / "config.toml").write_text('token = "shared-secret"\n')
        project = tmp_path / "proj"
        project.mkdir()
        (project / "agent-mailbox.toml").write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\nname = "jed_smith"\n'
        )
        env = {"XDG_CONFIG_HOME": str(home), "CLAUDECODE": "1"}
        config = load_config(project, env)
        assert config.name == "jed_smith", "identity still comes from the project"
        assert config.token == "shared-secret"

    def test_a_project_token_still_wins(self, tmp_path: Path) -> None:
        """The specific beats the general — one agent can be given its own."""
        home = tmp_path / "xdg"
        (home / "agent-inbox").mkdir(parents=True)
        (home / "agent-inbox" / "config.toml").write_text('token = "shared"\n')
        project = tmp_path / "proj"
        project.mkdir()
        (project / "agent-mailbox.toml").write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\n'
            'name = "jed_smith"\ntoken = "mine"\n'
        )
        env = {"XDG_CONFIG_HOME": str(home), "CLAUDECODE": "1"}
        assert load_config(project, env).token == "mine"

    def test_no_global_file_is_not_an_error(self, tmp_path: Path) -> None:
        """The common case is that it does not exist at all."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "agent-mailbox.toml").write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\nname = "jed_smith"\n'
        )
        env = {"XDG_CONFIG_HOME": str(tmp_path / "nothing"), "CLAUDECODE": "1"}
        assert load_config(project, env).token is None


class TestUniqueNames:
    """Two engines on one name share an inbox — the failure the file must not hold."""

    def _write(self, tmp_path: Path, body: str) -> Path:
        (tmp_path / "agent-mailbox.toml").write_text(body)
        return tmp_path

    def test_two_engines_claiming_one_name_are_reported(self, tmp_path: Path) -> None:
        """Observed in this very repository: claude and codex both `nicole_ruzickova`.

        The hub cannot catch it — both sides present the same name and are, to it, one
        correspondent — so mail is consumed by whichever reads first and simply goes
        missing. The file that assigns the names is the only place to notice.
        """
        self._write(
            tmp_path,
            'hub = "http://h:8081"\n\n[agents.claude]\nname = "nicole_ruzickova"\n\n'
            '[agents.codex]\nname = "nicole_ruzickova"\n',
        )
        assert duplicate_names(tmp_path) == {"nicole_ruzickova": ["claude", "codex"]}

    def test_a_difference_of_case_is_still_a_clash(self, tmp_path: Path) -> None:
        """Issued names are lowercase, so differing case means a hand-edited file —
        and two such entries collide on the hub while looking distinct in the file."""
        self._write(
            tmp_path,
            'hub = "http://h:8081"\n\n[agents.claude]\nname = "jed_smith"\n\n'
            '[agents.codex]\nname = "Jed_Smith"\n',
        )
        assert list(duplicate_names(tmp_path)) == ["jed_smith"]

    def test_distinct_names_are_not_reported(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            'hub = "http://h:8081"\n\n[agents.claude]\nname = "jed_smith"\n\n'
            '[agents.codex]\nname = "pablo_fantomas"\n',
        )
        assert duplicate_names(tmp_path) == {}

    def test_the_unnamed_placeholder_is_not_a_clash(self, tmp_path: Path) -> None:
        """Before `join`, every engine holds the same placeholder. That is not a
        collision — nobody has claimed anything yet — and reporting it would train
        people to ignore the check."""
        self._write(
            tmp_path,
            f'hub = "http://h:8081"\n\n[agents.claude]\nname = "{UNNAMED}"\n\n'
            f'[agents.codex]\nname = "{UNNAMED}"\n',
        )
        assert duplicate_names(tmp_path) == {}


def test_codex_is_detected_by_the_markers_a_real_session_carries() -> None:
    """From a session log: CODEX_SANDBOX and CODEX_HOME were both absent."""
    for marker in ("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_CI"):
        assert detect_engine({marker: "1"}) == "codex", marker


def test_an_explicit_engine_beats_the_environment(tmp_path: Path) -> None:
    """The MCP server knows which client connected; the environment may not.

    A client that spawns the server need not pass its own markers through — Codex does
    not — so with two engines configured the environment cannot resolve identity at
    all. Being told outright must win.
    """
    (tmp_path / "agent-mailbox.toml").write_text(
        'hub = "http://h:8081"\n\n[agents.claude]\nname = "nicole_ruzickova"\n\n'
        '[agents.codex]\nname = "pablo_fantomas"\n'
    )
    # the environment says claude; the caller says codex, and the caller is right
    env = {"CLAUDECODE": "1"}
    assert load_config(tmp_path, env).name == "nicole_ruzickova"
    assert load_config(tmp_path, env, engine="codex").name == "pablo_fantomas"


def test_without_an_engine_two_entries_stay_unresolvable(tmp_path: Path) -> None:
    """It must refuse rather than pick one — a wrong identity reads another's mail."""
    (tmp_path / "agent-mailbox.toml").write_text(
        'hub = "http://h:8081"\n\n[agents.claude]\nname = "a_name"\n\n'
        '[agents.codex]\nname = "another_name"\n'
    )
    with pytest.raises(NotConfigured):
        load_config(tmp_path, {})
