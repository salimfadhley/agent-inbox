"""An empty profile and a deliberately quiet one must not read the same (issue #61).

`igor_laszlo` had `{}` from the day he joined until the day he noticed, and nothing
ever said so — while the roster and the console overview, built from that profile, made
him a blank line to every agent deciding whether to write to him.

Two things are asserted here and they pull in opposite directions, which is the point:
`doctor` must **say something** when a profile describes nothing, and must **not** be
satisfied by a profile that is technically non-empty. `join` writes machine facts, so a
check that only asked "is this dict empty" would have passed for Igor the moment he ran
`join` — reporting a description that does not exist, which is worse than not checking.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_inbox import machine, profiles
from agent_inbox.cli import main
from agent_inbox.client import CONFIG_NAME, Config

QUIET = "igor_laszlo"


class TestWhatCountsAsSayingSomething:
    def test_an_empty_profile_describes_nothing(self) -> None:
        assert not profiles.describes_itself({})

    def test_machine_facts_alone_describe_nothing(self) -> None:
        """The case that makes this worth a module. Every joined agent has these; a
        naive emptiness test would call each of them well described."""
        facts = {key: "something" for key in machine.FACT_KEYS}

        assert not profiles.describes_itself(facts)
        assert profiles.self_reported(facts) == frozenset()

    def test_a_visibility_setting_is_not_a_description(self) -> None:
        """Setting a level says who may read the profile, not what is in it — and an
        agent that set `local` has said, if anything, that it wants less said."""
        assert not profiles.describes_itself({"visibility": "local"})

    def test_group_membership_is_not_a_description(self) -> None:
        assert not profiles.describes_itself({"groups": ["reviewers"]})

    def test_a_blank_value_is_not_a_description(self) -> None:
        """`{"purpose": ""}` renders exactly as `{}` does to a reader."""
        assert not profiles.describes_itself({"purpose": "   "})

    def test_one_real_field_is_enough(self) -> None:
        """The paired positive. Without it, a function returning False always would
        satisfy every test above."""
        said = {"purpose": "keeping the CLI honest", "host": "a-box"}

        assert profiles.describes_itself(said)
        assert profiles.self_reported(said) == frozenset({"purpose"})

    def test_the_excluded_set_still_covers_every_machine_fact(self) -> None:
        """The two lists are in different modules and would drift silently. A fact key
        added to `machine` and forgotten here would start counting as a description,
        which is the exact bug this module exists to prevent."""
        assert machine.FACT_KEYS <= profiles.NOT_A_DESCRIPTION


class _Hub:
    """A client answering only what `_report_profile` asks of it."""

    def __init__(self, profile: object) -> None:
        self._profile = profile
        self.asked: list[str] = []

    def whois(self, name: str) -> dict[str, object]:
        self.asked.append(name)
        return {"preferredUsername": name, "profile": self._profile}


class TestDoctorSaysSo:
    def test_an_undescribed_agent_is_told(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agent_inbox.cli import _report_profile

        _report_profile(_Hub({}), QUIET, "ok", "note")  # type: ignore[arg-type]

        out = capsys.readouterr().out
        assert "note" in out and "profile" in out
        assert "profile edit" in out, "a finding with no remedy is a complaint"

    def test_a_profile_of_only_machine_facts_is_told_too(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Igor's actual state. `join` had filled these in; nothing else ever had."""
        facts = {key: "x" for key in machine.FACT_KEYS}

        from agent_inbox.cli import _report_profile

        _report_profile(_Hub(facts), QUIET, "ok", "note")  # type: ignore[arg-type]

        assert "have not described yourself" in capsys.readouterr().out

    def test_a_described_agent_is_not_nagged(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The paired positive, and the reason it matters: a note printed to everybody
        every run is furniture, and a reader learns to skip the line — including on the
        run where it was true."""
        from agent_inbox.cli import _report_profile

        _report_profile(
            _Hub({"purpose": "reviewing things", "host": "a-box"}),
            QUIET,
            "ok",
            "note",
        )  # type: ignore[arg-type]

        out = capsys.readouterr().out
        assert "have not described yourself" not in out
        assert "purpose" in out, "it should say what it found, not merely approve"
        assert "host" not in out, "a machine fact is not one of your description fields"

    def test_a_hub_that_omits_the_profile_is_not_guessed_at(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An older hub renders an actor with no `profile` key. Absent is not empty,
        and reporting a guess as a finding is how a check starts lying."""
        from agent_inbox.cli import _report_profile

        _report_profile(_Hub(None), QUIET, "ok", "note")  # type: ignore[arg-type]

        assert capsys.readouterr().out == ""


class TestDoctorActuallyRunsTheCheck:
    """The wiring, not the function.

    Every test above calls `_report_profile` directly, so all of them would still pass
    with its one call site deleted from `doctor` — a check that has nothing to look at,
    which is the failure shape this project keeps meeting. This walks the whole command.
    """

    class _Hub:
        """Answers as a live hub would, far enough for `doctor` to reach the end."""

        profile: dict[str, object] = {}

        def __init__(self, config: Config) -> None:
            self.config = config

        def hub_info(self) -> dict[str, Any]:
            return {"name": "hub", "version": "test", "authenticated": False}

        def remote_doctor(self) -> dict[str, Any]:
            return {"you": {"token": "not needed"}, "verdict": "fine"}

        def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
            return {"items": []}

        def ping(self) -> dict[str, Any]:
            return {"you": QUIET}

        def whois(self, name: str) -> dict[str, Any]:
            return {"preferredUsername": name, "profile": dict(self.profile)}

    def _joined(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        profile: dict[str, object],
    ) -> None:
        (tmp_path / CONFIG_NAME).write_text(
            f'hub = "http://hub:8081"\n\n[agents.claude]\nname = "{QUIET}"\n'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("CLAUDECODE", "1")
        for var in ("AGENT_MAILBOX_HUB", "AGENT_MAILBOX_NAME", "AGENT_INBOX_HUB"):
            monkeypatch.delenv(var, raising=False)
        hub = type(self._Hub.__name__, (self._Hub,), {"profile": profile})
        monkeypatch.setattr("agent_inbox.cli.HubClient", hub)

    def test_a_joined_agent_with_nothing_to_say_hears_about_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._joined(tmp_path, monkeypatch, {})

        code = main(["doctor"])

        out = capsys.readouterr()
        assert "have not described yourself" in out.out
        assert code == 0, "a note is not a failure; saying nothing is allowed"

    def test_a_joined_agent_that_has_spoken_is_left_alone(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The paired positive for the wiring: a call site that always warned would
        satisfy the test above and make the line furniture within a week."""
        self._joined(tmp_path, monkeypatch, {"purpose": "keeping the CLI honest"})

        assert main(["doctor"]) == 0
        out = capsys.readouterr().out
        assert "have not described yourself" not in out
        assert "purpose" in out
