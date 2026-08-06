"""The operator's federation commands — and the assertion that they decide nothing.

NFR-003 and C-006. Every command must go through the API; none may recompute policy.
**This is the one bug in this area nobody looks for**, because a client that evaluates
a blocklist looks like it is only displaying one — and the second implementation of a
trust decision is the one that eventually disagrees with the first.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_inbox.cli import main
from agent_inbox.client import CONFIG_NAME, ClientError, Config

SOURCE = Path(__file__).resolve().parents[1] / "src" / "agent_inbox"
PEER = "https://peer.example"


class Recorder:
    """A hub that records what it was asked, and answers plausibly."""

    def __init__(self, config: Config) -> None:
        self.config = config
        Recorder.calls = []

    calls: list[tuple[str, Any]] = []

    def _note(self, name: str, *args: Any) -> None:
        Recorder.calls.append((name, args))

    def hub_info(self) -> dict[str, Any]:
        return {"name": "here", "version": "1.0.0"}

    def hub_settings(self) -> dict[str, Any]:
        self._note("hub_settings")
        return {
            "settings": {
                "federation": {"value": "disabled", "source": "the environment"},
                "name": {"value": "us", "source": "the store"},
            }
        }

    def set_hub_settings(self, **settings: str) -> dict[str, Any]:
        self._note("set_hub_settings", settings)
        return {"ok": True}

    def peers(self) -> dict[str, Any]:
        self._note("peers")
        return {"items": [{"origin": PEER, "added": "2026-08-06"}]}

    def add_peer(self, origin: str, note: str = "") -> dict[str, Any]:
        self._note("add_peer", origin, note)
        return {"origin": origin, "trusted": True}

    def remove_peer(self, origin: str) -> dict[str, Any]:
        self._note("remove_peer", origin)
        return {"origin": origin}

    def blocks(self) -> dict[str, Any]:
        self._note("blocks")
        return {"items": [{"origin": PEER, "note": "spam"}]}

    def add_block(self, origin: str, note: str = "") -> dict[str, Any]:
        self._note("add_block", origin, note)
        return {"origin": origin, "blocked": True}

    def remove_block(self, origin: str) -> dict[str, Any]:
        self._note("remove_block", origin)
        return {"origin": origin, "blocked": False}


@pytest.fixture
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / CONFIG_NAME).write_text(
        'hub = "http://here:8080"\n\n[agents.claude]\nname = "nicole_ruzickova"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent_inbox.cli.HubClient", Recorder)


class TestEveryCommandAsksTheHub:
    def test_status_reports_each_setting_with_its_source(
        self, wired: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FR-019: the shape `config list` already uses, so an operator learns one way
        of being told what governs what."""
        assert main(["--engine", "claude", "federation", "status"]) == 0
        out = capsys.readouterr().out

        assert "federation" in out
        assert "the environment" in out, "the source is not reported"

    def test_enable_sends_the_setting_and_does_not_evaluate_the_rule(
        self, wired: None
    ) -> None:
        """FR-002: whether federation *may* be enabled is the hub's rule. The client
        asks; it does not check for a public URL or a hub called `local` itself."""
        assert main(["--engine", "claude", "federation", "enable"]) == 0

        assert ("set_hub_settings", ({"federation": "enabled"},)) in Recorder.calls

    def test_a_refusal_is_printed_as_the_hub_worded_it(
        self,
        wired: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A client paraphrasing a refusal is how the two come to disagree about what
        the rule was."""

        def refuse(**settings: str) -> dict[str, Any]:
            raise ClientError("this hub is called 'local' and cannot be told apart")

        monkeypatch.setattr(Recorder, "set_hub_settings", staticmethod(refuse))

        assert main(["--engine", "claude", "federation", "enable"]) == 1
        assert "called 'local'" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["peers", "list"], "peers"),
            (["peers", "add", PEER], "add_peer"),
            (["peers", "remove", PEER], "remove_peer"),
            (["blocklist", "list"], "blocks"),
            (["blocklist", "add", PEER], "add_block"),
            (["blocklist", "remove", PEER], "remove_block"),
        ],
    )
    def test_each_command_reaches_its_route(
        self, wired: None, argv: list[str], expected: str
    ) -> None:
        assert main(["--engine", "claude", *argv]) == 0

        assert expected in [name for name, _ in Recorder.calls]

    def test_unblocking_says_it_does_not_restore_trust(
        self, wired: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An operator who assumes otherwise has restored a peering they did not
        intend, and would not find out until mail reached somebody."""
        main(["--engine", "claude", "blocklist", "remove", PEER])

        assert "not trusted" in capsys.readouterr().out


class TestTheClientDecidesNothing:
    """T023. Otherwise C-006 is broken from the client side, which is the half nobody
    audits — the hub's decision function gets all the attention.

    **Parsed, not grepped.** The first version searched the text and flagged a
    *docstring* that named `check_may_enable_federation` while explaining that the
    client does not call it. A guard that cannot tell code from prose produces
    false positives, and a guard that produces false positives gets deleted.
    """

    #: Names that only appear in client code if the client is deciding something the
    #: hub owns: evaluating a mode, reading the blocklist, or re-running the hub's own
    #: rule about whether federation may be enabled.
    FORBIDDEN = frozenset(
        {
            "check_may_enable_federation",
            "FEDERATION_MODES",
            "Visibility",
            "may_exchange",
        }
    )

    @staticmethod
    def _referenced(path: Path) -> set[str]:
        """Every name the module actually *uses* — strings and comments excluded."""
        import ast

        tree = ast.parse(path.read_text())
        seen: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                seen.add(node.id)
            elif isinstance(node, ast.Attribute):
                seen.add(node.attr)
        return seen

    def test_the_client_does_not_evaluate_policy(self) -> None:
        offenders = {
            f"{name}: {sorted(self.FORBIDDEN & self._referenced(SOURCE / name))}"
            for name in ("client.py", "cli.py")
            if self.FORBIDDEN & self._referenced(SOURCE / name)
        }

        assert not offenders, (
            "the client evaluates a federation policy the hub owns — that is the "
            f"second implementation C-006 warns about: {sorted(offenders)}"
        )

    def test_the_guard_would_find_one(self, tmp_path: Path) -> None:
        """The premise. A check that matches nothing passes the test above for the worst
        possible reason, and this one is deliberately narrow enough to be worth doubting.
        """
        planted = tmp_path / "pretend_client.py"
        planted.write_text(
            "# check_may_enable_federation in a comment must NOT count\n"
            "def go(name):\n"
            '    """Nor may Visibility in a docstring."""\n'
            "    return check_may_enable_federation(name)\n"
        )

        found = self.FORBIDDEN & self._referenced(planted)

        assert found == {"check_may_enable_federation"}, (
            "the guard either missed a real call or counted prose"
        )
