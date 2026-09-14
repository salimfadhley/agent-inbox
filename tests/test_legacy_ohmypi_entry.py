"""`[agents.ohmypi]` is read as `omp` — the older spelling of an engine key (#65).

Two agents joined as `ohmypi` before `omp` was chosen as the key. A client that then
looked only for `[agents.omp]` refused them — or, on `join`, wrote a second entry beside
the first, and two entries with one name share an inbox. The charter's rule for our own
renames is that the old spelling keeps working; an engine key is one of our names.

Read under the old spelling, written back under it, never duplicated, and never
migrated: the file is somebody's.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_inbox import client
from agent_inbox.client import CONFIG_NAME, entry_key, load_config


def _project(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / CONFIG_NAME).write_text(f'hub = "http://hub:8081"\n\n{body}')
    return tmp_path


class TestTheOlderSpellingIsRead:
    def test_omp_reads_an_ohmypi_entry(self, tmp_path: Path) -> None:
        root = _project(tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\n')

        config = load_config(start=root, env={}, engine="omp")

        assert config.name == "valentin_pop"

    def test_the_current_spelling_wins_when_both_exist(self, tmp_path: Path) -> None:
        """A project with both has two entries; the legacy one is just another
        engine's. Preferring it would silently swap identities."""
        root = _project(
            tmp_path,
            '[agents.omp]\nname = "espen_luo"\n\n'
            '[agents.ohmypi]\nname = "valentin_pop"\n',
        )

        assert load_config(start=root, env={}, engine="omp").name == "espen_luo"

    def test_no_other_engine_borrows_it(self, tmp_path: Path) -> None:
        """The alias is one-directional and one-pair. `claude` must not resolve to
        an `ohmypi` entry just because it is the only one there and a marker is set."""
        root = _project(tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\n')

        with pytest.raises(client.NotConfigured):
            load_config(start=root, env={}, engine="claude")

    def test_entry_key_names_where_it_was_found(self) -> None:
        assert entry_key({"ohmypi": {}}, "omp") == "ohmypi"
        assert entry_key({"omp": {}, "ohmypi": {}}, "omp") == "omp"
        assert entry_key({}, "omp") == "omp"
        assert entry_key({"ohmypi": {}}, "claude") == "claude"
        assert entry_key({"ohmypi": {}}, None) is None


class TestWritesKeepTheSpellingAndNeverDuplicate:
    def test_config_set_writes_into_the_existing_entry(self, tmp_path: Path) -> None:
        root = _project(tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\n')

        client.write_project({"role": "reviewer"}, start=root, env={}, engine="omp")

        text = (root / CONFIG_NAME).read_text()
        assert "[agents.omp]" not in text
        assert text.count("[agents.ohmypi]") == 1
        assert load_config(start=root, env={}, engine="omp").role == "reviewer"

    def test_unset_reaches_the_existing_entry(self, tmp_path: Path) -> None:
        root = _project(
            tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\nrole = "x"\n'
        )

        assert client.unset_project("role", start=root, env={}, engine="omp") is True
        text = (root / CONFIG_NAME).read_text()
        assert 'role = "x"' not in text
        assert "[agents.omp]" not in text

    def test_a_rejoin_refuses_rather_than_writing_a_second_identity(
        self, tmp_path: Path
    ) -> None:
        """The fault this exists to prevent: `join` as omp beside an `ohmypi` entry
        used to write `[agents.omp]` too — two entries, and if the hub issued the same
        name back, one inbox read by two engines."""
        root = _project(tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\n')

        with pytest.raises(client.ClientError, match="already 'valentin_pop'"):
            client.write_config("http://hub:8081", "valentin_pop", "omp", start=root)

        assert "[agents.omp]" not in (root / CONFIG_NAME).read_text()

    def test_a_forced_rejoin_replaces_in_place(self, tmp_path: Path) -> None:
        root = _project(tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\n')

        client.write_config(
            "http://hub:8081", "espen_luo", "omp", start=root, force=True
        )

        text = (root / CONFIG_NAME).read_text()
        assert "[agents.omp]" not in text
        assert "espen_luo" in text and "valentin_pop" not in text


class TestTheCliKnowsToo:
    def _configure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _project(tmp_path, '[agents.ohmypi]\nname = "valentin_pop"\ntoken = "t"\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("OMPCODE", "1")
        monkeypatch.setenv("CLAUDECODE", "1")
        for var in ("AGENT_INBOX_NAME", "AGENT_MAILBOX_NAME", "AGENT_INBOX_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    def test_whoami_under_omp_finds_the_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """The 2026-09-07 Windows case, on a fixed client: both markers set, an
        `ohmypi` entry, and `whoami` must answer valentin_pop without `--engine`."""
        from agent_inbox.cli import main

        self._configure(tmp_path, monkeypatch)

        class _Hub:
            def __init__(self, config: Any) -> None:
                pass

            def whois(self, name: str) -> dict[str, Any]:
                return {"profile": {}}

            def remote_doctor(self) -> dict[str, Any]:
                return {"you": {"token": "accepted"}, "verdict": "fine"}

        monkeypatch.setattr("agent_inbox.cli.HubClient", _Hub)

        assert main(["whoami"]) == 0

        assert '"name": "valentin_pop"' in capsys.readouterr().out

    def test_doctor_says_which_spelling_it_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        from agent_inbox.cli import main

        self._configure(tmp_path, monkeypatch)

        class _Hub:
            def __init__(self, config: Any) -> None:
                pass

            def hub_info(self) -> dict[str, Any]:
                return {"name": "hub", "version": "test", "authenticated": True}

            def remote_doctor(self) -> dict[str, Any]:
                return {"you": {"token": "accepted"}, "verdict": "fine"}

            def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
                return {"items": []}

            def ping(self) -> dict[str, Any]:
                return {"you": "valentin_pop"}

            def whois(self, name: str) -> dict[str, Any]:
                return {"profile": {"role": "x"}}

        monkeypatch.setattr("agent_inbox.cli.HubClient", _Hub)

        assert main(["doctor"]) == 0

        out = capsys.readouterr().out
        assert "identity        valentin_pop (agent, engine omp" in out
        assert "read from [agents.ohmypi], the older spelling" in out
