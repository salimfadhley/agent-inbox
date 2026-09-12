"""`doctor` puts the name this machine sends beside the name the hub says it is (#68).

The two halves already existed and neither was shown as a pair: `identity` printed the
configured name, and the hub's own diagnosis returned `you.claimed` and `you.verified`
of which only the one-sentence verdict was printed. So when they disagreed, nothing
said so — and they have disagreed twice in a week: a name set by an imported config
(2026-09-03) and a pre-1.2.0 client picking another engine's entry (2026-09-07, #65).

What settles a disagreement is the hub's rule, quoted from its own source: a token bound
to an actor is served *as that actor whatever the header says*. So the mismatch line
says what that means — every message goes out under the token's name — and fails the
command, because the API answered, and it answered as somebody else.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_inbox.cli import main
from agent_inbox.client import CONFIG_NAME, Config


def _hub_answering(you: dict[str, Any]) -> type:
    class _Hub:
        def __init__(self, config: Config) -> None:
            self.config = config

        def hub_info(self) -> dict[str, Any]:
            return {"name": "hub", "version": "test", "authenticated": True}

        def remote_doctor(self) -> dict[str, Any]:
            return {"you": {"token": "accepted", **you}, "verdict": "fine"}

        def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
            return {"items": []}

        def ping(self) -> dict[str, Any]:
            return {"you": self.config.name}

        def whois(self, name: str) -> dict[str, Any]:
            return {"profile": {"role": "tester"}}

    return _Hub


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hub: type) -> None:
    (tmp_path / CONFIG_NAME).write_text(
        'hub = "http://hub:8081"\n\n[agents.claude]\nname = "nicole_ruzickova"\n'
        'token = "t"\n'
    )
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("CLAUDECODE", "1")
    for var in ("AGENT_INBOX_NAME", "AGENT_MAILBOX_NAME", "AGENT_INBOX_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("agent_inbox.cli.HubClient", hub)


class TestDoctorSaysWhoTheHubThinksYouAre:
    def test_a_token_that_settles_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _configure(
            tmp_path,
            monkeypatch,
            _hub_answering(
                {"claimed": "nicole_ruzickova", "verified": "nicole_ruzickova"}
            ),
        )

        assert main(["doctor"]) == 0

        out = capsys.readouterr().out
        assert "hub says        you are nicole_ruzickova — settled by your token" in out

    def test_a_name_the_hub_overrides_is_a_failure_that_names_both(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """**The finding this exists for.** Two names, the hub's rule spelled out,
        and where the wrong one came from — and a non-zero exit, because the API
        answered as somebody else."""
        _configure(
            tmp_path,
            monkeypatch,
            _hub_answering({"claimed": "nicole_ruzickova", "verified": "valentin_pop"}),
        )

        assert main(["doctor"]) == 1

        captured = capsys.readouterr()
        said = captured.out + captured.err
        assert "hub says" in said
        assert "you send 'nicole_ruzickova'" in said
        assert "belongs to 'valentin_pop'" in said
        assert "every message goes out in that name" in said
        assert CONFIG_NAME in said

    def test_the_mismatch_names_the_variable_that_set_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """The 2026-09-03 case: an imported config set `AGENT_INBOX_NAME` to another
        agent's name. Pointing at the file would have sent the reader to the wrong
        place; the variable in effect is the thing to name."""
        _configure(
            tmp_path,
            monkeypatch,
            _hub_answering({"claimed": "aurelia_saahaa", "verified": "espen_luo"}),
        )
        monkeypatch.setenv("AGENT_INBOX_NAME", "aurelia_saahaa")

        assert main(["doctor"]) == 1

        captured = capsys.readouterr()
        assert "comes from AGENT_INBOX_NAME" in captured.out + captured.err

    def test_a_shared_token_takes_the_header_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _configure(
            tmp_path,
            monkeypatch,
            _hub_answering({"claimed": "nicole_ruzickova", "verified": "*"}),
        )

        assert main(["doctor"]) == 0

        out = capsys.readouterr().out
        assert "you are nicole_ruzickova — shared token" in out

    def test_an_unverified_name_is_said_to_be_taken_on_trust(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _configure(
            tmp_path,
            monkeypatch,
            _hub_answering({"claimed": "nicole_ruzickova", "verified": None}),
        )

        assert main(["doctor"]) == 0

        out = capsys.readouterr().out
        assert "you are nicole_ruzickova — taken at your word" in out

    def test_an_older_hub_gets_no_line_rather_than_a_guess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """A hub that returns neither field has not answered. Filling the line in
        from the config would be the client asserting what only the hub knows — the
        rule from #50 and #60, kept."""
        _configure(tmp_path, monkeypatch, _hub_answering({}))

        assert main(["doctor"]) == 0

        out = capsys.readouterr().out
        # The premise: the rest of the diagnosis ran, so an absent line is a choice.
        assert "hub check       fine" in out
        assert "hub says" not in out


class TestWhoamiCarriesTheSameAnswer:
    def test_whoami_reports_what_the_hub_says(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _configure(
            tmp_path,
            monkeypatch,
            _hub_answering({"claimed": "nicole_ruzickova", "verified": "valentin_pop"}),
        )

        assert main(["whoami"]) == 0

        out = json.loads(capsys.readouterr().out)
        assert out["name"] == "nicole_ruzickova"
        assert "belongs to 'valentin_pop'" in out["hub_says"]

    def test_whoami_omits_it_when_the_hub_cannot_say(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _configure(tmp_path, monkeypatch, _hub_answering({}))

        assert main(["whoami"]) == 0

        assert "hub_says" not in json.loads(capsys.readouterr().out)
