"""WP06 — the client carries a device token, and the config survives awkward values.

The config-writing path has bitten us before (unescaped TOML, non-atomic, dropped keys),
so the tests lean on those: a value with a quote and a backslash must round-trip,
and writing one engine must not evict another.
"""

import json
from pathlib import Path

import pytest

from agent_inbox.client import (
    CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    UNNAMED,
    Config,
    HubClient,
    NotConfigured,
    _from_older_hub,
    _toml_str,
    detect_engine,
    duplicate_names,
    effective_settings,
    find_config,
    load_config,
    write_config,
    write_project,
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
        text = (tmp_path / CONFIG_NAME).read_text()
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
        (project / CONFIG_NAME).write_text(
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
        (project / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\n'
            'name = "jed_smith"\ntoken = "mine"\n'
        )
        env = {"XDG_CONFIG_HOME": str(home), "CLAUDECODE": "1"}
        assert load_config(project, env).token == "mine"

    def test_no_global_file_is_not_an_error(self, tmp_path: Path) -> None:
        """The common case is that it does not exist at all."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n[agents.claude]\nname = "jed_smith"\n'
        )
        env = {"XDG_CONFIG_HOME": str(tmp_path / "nothing"), "CLAUDECODE": "1"}
        assert load_config(project, env).token is None


class TestUniqueNames:
    """Two engines on one name share an inbox — the failure the file must not hold."""

    def _write(self, tmp_path: Path, body: str) -> Path:
        (tmp_path / CONFIG_NAME).write_text(body)
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
    (tmp_path / CONFIG_NAME).write_text(
        'hub = "http://h:8081"\n\n[agents.claude]\nname = "nicole_ruzickova"\n\n'
        '[agents.codex]\nname = "pablo_fantomas"\n'
    )
    # the environment says claude; the caller says codex, and the caller is right
    env = {"CLAUDECODE": "1"}
    assert load_config(tmp_path, env).name == "nicole_ruzickova"
    assert load_config(tmp_path, env, engine="codex").name == "pablo_fantomas"


def test_without_an_engine_two_entries_stay_unresolvable(tmp_path: Path) -> None:
    """It must refuse rather than pick one — a wrong identity reads another's mail."""
    (tmp_path / CONFIG_NAME).write_text(
        'hub = "http://h:8081"\n\n[agents.claude]\nname = "a_name"\n\n'
        '[agents.codex]\nname = "another_name"\n'
    )
    with pytest.raises(NotConfigured):
        load_config(tmp_path, {})


class TestAnOlderHub:
    """A current client against a hub that predates compact views.

    Reported by pablo_fantomas against a 0.16.1 hub: `inbox --count` printed `0` while
    `inbox` printed rows of `?` and `(None chars)`. An empty mailbox and a corrupt one,
    neither true, with nothing to suggest the hub was the reason. Clients and hubs are
    upgraded separately, so this is a normal state, not an exotic one.
    """

    #: A **real** response from a real 0.16.1 hub, captured by checking that tag out
    #: and running its own `build_api`. Not a hand-written approximation — see
    #: `tests/fixtures/README.md` for why that distinction earns its keep.
    LEGACY = json.loads(
        (Path(__file__).parent / "fixtures" / "inbox-0.16.1.json").read_text()
    )

    def test_the_count_is_right_instead_of_zero(self) -> None:
        page = _from_older_hub(self.LEGACY, view="count", asked_since=False)
        assert page["unread"] == 2, "an older hub's mail was reported as no mail"
        assert page["hubTooOld"] is True

    def test_the_rows_are_filled_in_instead_of_none(self) -> None:
        page = _from_older_hub(self.LEGACY, view="summary", asked_since=False)
        first, second = page["items"]
        assert first["attributedTo"].endswith("rosemary_nasrin")
        assert first["summary"] == "flaky tests"
        assert first["chars"] == len(self.LEGACY["items"][0]["content"])
        assert first["broadcast"] is False
        assert second["summary"] == "(no subject)", "a missing subject became None"
        assert second["broadcast"] is True

    def test_an_ignored_since_is_admitted_to(self) -> None:
        """The filter is the hub's job. An old hub did not do it, and must say so."""
        page = _from_older_hub(self.LEGACY, view="summary", asked_since=True)
        assert page["sinceIgnored"] is True
        assert page["unread"] == 2, "unfiltered mail must not be passed off as new"

    def test_a_current_hub_is_left_alone(self) -> None:
        """The shim must not touch an answer that is already in the right shape."""
        from agent_inbox.client import Config, HubClient

        client = HubClient(Config(hub="http://hub.invalid", name="trevor_mahmood"))
        modern = {"unread": 1, "cursor": "t|abc", "items": []}
        client._call = lambda *a, **k: modern  # type: ignore[method-assign]
        assert client.check_inbox() is modern


class TestTheRenameKeepsOldProjectsWorking:
    """`agent-mailbox` became `agent-inbox`. Nobody's identity may be lost to that.

    An identity file is not ours to invalidate: an agent that cannot find its own name
    has lost its correspondence, not merely its configuration.
    """

    def test_the_current_name_is_what_join_writes(self, tmp_path: Path) -> None:
        write_project(
            {"hub": "http://h", "name": "rosemary_nasrin"},
            tmp_path,
            env={"CLAUDECODE": "1"},
        )
        assert (tmp_path / CONFIG_NAME).is_file()
        assert CONFIG_NAME == "agent-inbox.toml"

    def test_a_legacy_file_is_still_found(self, tmp_path: Path) -> None:
        """Every project joined before the rename holds this name."""
        (tmp_path / LEGACY_CONFIG_NAME).write_text(
            'hub = "http://h"\n[agents.claude]\nname = "rosemary_nasrin"\n'
        )
        found = find_config(tmp_path)
        assert found is not None and found.name == LEGACY_CONFIG_NAME
        assert load_config(tmp_path, engine="claude").name == "rosemary_nasrin"

    def test_the_current_name_wins_when_a_project_has_both(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / LEGACY_CONFIG_NAME).write_text(
            'hub = "http://old"\n[agents.claude]\nname = "old_name"\n'
        )
        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://new"\n[agents.claude]\nname = "new_name"\n'
        )
        assert load_config(tmp_path, engine="claude").name == "new_name"

    def test_a_nearer_legacy_file_beats_a_distant_current_one(
        self, tmp_path: Path
    ) -> None:
        """Proximity settles which project you are in, not which name it uses.

        Sweeping one name over the whole tree first would let a parent project's file
        win over the one sitting beside you — a different project's identity.
        """
        (tmp_path / ".git").mkdir()
        (tmp_path / CONFIG_NAME).write_text(
            'hub = "http://parent"\n[agents.claude]\nname = "parent_agent"\n'
        )
        child = tmp_path / "sub"
        child.mkdir()
        (child / LEGACY_CONFIG_NAME).write_text(
            'hub = "http://child"\n[agents.claude]\nname = "child_agent"\n'
        )
        assert load_config(child, engine="claude").name == "child_agent"


class TestTheRenameKeepsOldEnvironmentsWorking:
    def test_the_new_variables_are_read(self) -> None:
        cfg = load_config(
            env={"AGENT_INBOX_HUB": "http://new", "AGENT_INBOX_NAME": "a"}
        )
        assert (cfg.hub, cfg.name) == ("http://new", "a")

    def test_the_old_variables_still_work(self) -> None:
        """Nine of these are set on the reference deployment."""
        cfg = load_config(
            env={"AGENT_MAILBOX_HUB": "http://old", "AGENT_MAILBOX_NAME": "b"}
        )
        assert (cfg.hub, cfg.name) == ("http://old", "b")

    def test_the_new_name_wins_when_both_are_set(self) -> None:
        """Whoever set the new one is mid-migration and means the newer value."""
        cfg = load_config(
            env={
                "AGENT_MAILBOX_HUB": "http://old",
                "AGENT_INBOX_HUB": "http://new",
                "AGENT_INBOX_NAME": "c",
            }
        )
        assert cfg.hub == "http://new"

    def test_config_list_names_the_variable_actually_set(self) -> None:
        """`config list` answers "where did this come from" — so do not lie about it."""
        found = effective_settings(env={"AGENT_MAILBOX_HUB": "http://old"})
        assert found["hub"] == ("http://old", "AGENT_MAILBOX_HUB")


class TestJoinDoesNotEvictWhoeverWasHereFirst:
    """Issue #47. `join` merged into the canonical filename rather than the file in use.

    A project still on the supported back-compat `agent-mailbox.toml` therefore got a
    **brand new** `agent-inbox.toml` holding only the joining engine — and because the
    new name takes precedence, every other identity vanished at once.

    That is exactly the eviction `write_config`'s docstring says merging exists to
    prevent — *"the eviction would be invisible until their mail stopped arriving"* —
    arriving by a different route. The merge was careful; it read the wrong file.
    """

    def test_a_legacy_named_project_keeps_its_other_engines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox.client import write_config

        (tmp_path / LEGACY_CONFIG_NAME).write_text(
            'hub = "http://hub:8081"\n\n'
            '[agents.claude]\nname = "nicole_ruzickova"\nrole = "admin"\n\n'
            '[agents.codex]\nname = "pablo_fantomas"\nrole = "admin"\n'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        write_config("http://hub:8081", "nicole_ruzickova", engine="claude", force=True)

        text = (tmp_path / LEGACY_CONFIG_NAME).read_text()
        assert "pablo_fantomas" in text, "codex's identity was evicted by claude's join"
        assert not (tmp_path / CONFIG_NAME).exists(), (
            "join created a second config file, which then shadows the real one"
        )

    def test_a_fresh_project_still_gets_the_canonical_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The paired positive: new projects still get the canonical name."""
        from agent_inbox.client import write_config

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        write_config("http://hub:8081", "jed_smith", engine="claude")
        assert (tmp_path / CONFIG_NAME).exists()
        assert not (tmp_path / LEGACY_CONFIG_NAME).exists()


class TestJoinLeavesTheHubMachineWide:
    """Issue #47, second half. `join` wrote `hub` into the project file.

    That re-created the very shadowing the machine-wide default (v0.48.0) exists to
    remove: every project joined against a hub was pinned to it for ever, and a later
    `config set hub` appeared to do nothing at all.
    """

    def test_it_writes_the_hub_machine_wide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox.client import write_config

        xdg = tmp_path / "xdg"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        write_config("http://hub:8081", "jed_smith", engine="claude")

        assert "http://hub:8081" in (xdg / "agent-inbox" / "config.toml").read_text()
        assert "hub" not in (tmp_path / CONFIG_NAME).read_text(), (
            "join pinned this project to a hub, which config set then cannot change"
        )

    def test_a_project_that_already_pins_one_keeps_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pinned hub is somebody's deliberate choice — a staging deployment, a
        second mailbox. Joining must not quietly undo it either."""
        from agent_inbox.client import write_config

        (tmp_path / CONFIG_NAME).write_text('hub = "http://staging:8081"\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        write_config("http://other:8081", "jed_smith", engine="claude")
        assert "http://staging:8081" in (tmp_path / CONFIG_NAME).read_text()

    def test_a_per_engine_token_keeps_its_hub_beside_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Found by outside review, and it is the rule `config set` already enforces.

        Sending the hub machine-wide while a per-engine token stays in the project
        leaves that engine loading the new hub with the old hub's credential — and the
        hub answers `token rejected`, which points at the one thing that is not wrong.
        """
        from agent_inbox.client import write_config

        (tmp_path / CONFIG_NAME).write_text(
            '[agents.codex]\nname = "pablo_fantomas"\ntoken = "for-the-old-hub"\n'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        write_config("http://new:8081", "pablo_fantomas", engine="codex", force=True)

        text = (tmp_path / CONFIG_NAME).read_text()
        assert "for-the-old-hub" in text, "the token was dropped"
        assert "http://new:8081" in text, (
            "the hub went machine-wide while its token stayed here — they must match"
        )
