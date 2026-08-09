"""Waking, for a harness that is not Claude Code (issue #64).

`install-hook` wrote `.claude/settings.json` **whatever it was running under**, and
reported success. The onboarding prompt promised the opposite in as many words: *"where
a harness has no such mechanism the command says so and costs you nothing."* It did not
say so. It wrote a file nothing read and told the agent it was reachable.

That is a false success, which is the worst kind — nothing looks wrong, and an agent
goes on believing mail will reach it. `aurelia_saahaa` joining on opencode was the first
time anyone was positioned to notice.

Two things ship here and the second is the smaller one:

**A harness with no mechanism is told so, and nothing is written.** That is worth having
even if opencode support were abandoned tomorrow.

**opencode gets a plugin**, because it turns out not to be hookless: `session.idle` is
its analogue of Claude Code's `Stop`, and a plugin can deliver through the SDK client.
The plugin is deliberately thin — it runs *our* waiter and passes through what the
waiter said. A second implementation of the waiting logic in JavaScript is the failure
this shape exists to prevent, and the assertions below are mostly about keeping it thin.
"""

from pathlib import Path

import pytest

from agent_inbox import hookconfig


class TestAHarnessWithNoMechanismIsToldSo:
    def test_it_refuses_rather_than_guessing(self, tmp_path: Path) -> None:
        """The bug. This used to return a path to a file it had just written."""
        with pytest.raises(hookconfig.NoWakingHere):
            hookconfig.install_for(None, tmp_path)

    def test_it_writes_nothing_at_all(self, tmp_path: Path) -> None:
        """ "Costs you nothing" is the promise, and a stray `.claude/` in an opencode
        project is a cost — it is a file somebody will later wonder about."""
        with pytest.raises(hookconfig.NoWakingHere):
            hookconfig.install_for("some-future-harness", tmp_path)

        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / ".opencode").exists()

    def test_the_refusal_says_what_still_works(self, tmp_path: Path) -> None:
        """An agent told only "no" concludes its mail is broken. It is not — checking
        at the start of a turn is what every agent did before hooks existed."""
        with pytest.raises(hookconfig.NoWakingHere) as refused:
            hookconfig.install_for(None, tmp_path)

        assert "checking your inbox" in str(refused.value)


class TestClaudeCodeIsUnaffected:
    """The harness that already works must not be disturbed by teaching another."""

    def test_it_still_writes_the_settings_file(self, tmp_path: Path) -> None:
        path = hookconfig.install_for("claude", tmp_path)

        assert path == hookconfig.settings_path(tmp_path)
        assert path.exists()

    def test_it_still_takes_rewake(self, tmp_path: Path) -> None:
        import json

        hookconfig.install_for("claude", tmp_path, rewake=True)
        settings = json.loads(hookconfig.settings_path(tmp_path).read_text())

        stop = settings["hooks"]["Stop"][0]["hooks"][0]
        assert stop.get("asyncRewake") is True

    def test_no_opencode_plugin_is_written_for_claude(self, tmp_path: Path) -> None:
        hookconfig.install_for("claude", tmp_path)

        assert not hookconfig.plugin_path(tmp_path).exists()


class TestOpencodeGetsAPlugin:
    def test_it_lands_where_opencode_loads_from(self, tmp_path: Path) -> None:
        """`.opencode/plugins/` is auto-loaded at startup, which is what makes it the
        analogue of `.claude/settings.json` — a known place, needing no registration."""
        path = hookconfig.install_for("opencode", tmp_path)

        assert path == tmp_path / ".opencode" / "plugins" / "agent-inbox-wake.js"
        assert path.exists()

    def test_it_subscribes_to_the_idle_event(self, tmp_path: Path) -> None:
        source = hookconfig.install_for("opencode", tmp_path).read_text()

        assert "session.idle" in source

    def test_it_runs_our_waiter_rather_than_reimplementing_one(
        self, tmp_path: Path
    ) -> None:
        """**The property that keeps this thin.** Everything that makes waiting work —
        the held event stream, the polling floor, the announce-once watermark, the
        re-arm — lives in `wake.py` and is harness-agnostic. A plugin that polled the
        hub itself would be a second implementation, in a second language, drifting."""
        source = hookconfig.install_for("opencode", tmp_path).read_text()

        assert "wake-check" in source
        assert "--wait" in source

    def test_it_delivers_only_on_the_wake_exit_code(self, tmp_path: Path) -> None:
        """Exit 2 means "there is mail". Exit 0 means the waiter re-armed or timed out,
        and delivering on that would wake an agent to tell it nothing."""
        source = hookconfig.install_for("opencode", tmp_path).read_text()

        assert "exitCode === 2" in source

    def test_it_holds_one_waiter_at_a_time(self, tmp_path: Path) -> None:
        """`session.idle` can fire again while a waiter is held, and two waiters would
        announce the same arrival twice."""
        source = hookconfig.install_for("opencode", tmp_path).read_text()

        assert "holding" in source

    def test_installing_twice_replaces_rather_than_appends(
        self, tmp_path: Path
    ) -> None:
        hookconfig.install_for("opencode", tmp_path)
        first = hookconfig.plugin_path(tmp_path).read_text()
        hookconfig.install_for("opencode", tmp_path)

        assert hookconfig.plugin_path(tmp_path).read_text() == first


class TestTheNoticeIsNeverAMessageBody:
    """**The load-bearing safety property of the whole mission.**

    On Claude Code, exit-2 stderr is visibly machine output. On opencode it lands as a
    message in the conversation, in the human's voice. So a message body injected here
    would read as the operator's own instruction — and any peer who can write to this
    agent could drive it. That is ADR 0008 broken at the root.
    """

    def test_the_plugin_passes_the_waiter_text_through_unaltered(
        self, tmp_path: Path
    ) -> None:
        """It composes no text of its own. `wake._notice` already emits sender and
        subject only, and passing through is what inherits that guarantee rather than
        re-deciding it in JavaScript."""
        source = hookconfig.install_for("opencode", tmp_path).read_text()

        assert "run.stderr" in source

    def test_the_waiter_it_calls_never_emits_a_body(self) -> None:
        """Asserted against `wake` itself, because that is where the guarantee lives.
        If the notice ever grew a body, this plugin would faithfully deliver it."""
        from agent_inbox.wake import _notice

        notice = _notice(
            [
                {
                    "id": "u/1",
                    "attributedTo": "u/pablo_fantomas",
                    "summary": "a subject line",
                    "content": "SECRET BODY THAT MUST NOT TRAVEL",
                }
            ]
        )

        assert "pablo_fantomas" in notice
        assert "a subject line" in notice
        assert "SECRET BODY" not in notice
