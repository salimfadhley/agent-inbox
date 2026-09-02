"""Waking, for omp (oh-my-pi) (issue #65, part B).

The opencode plugin's shape (#64), on a harness with a stronger primitive. omp's
`pi.sendMessage(text, { deliverAs: "followUp", triggerTurn: true })` starts a turn on an
*idle* session, so an omp agent whose human has walked away is actually woken — which
Claude Code's blocking `Stop` hook cannot do.

The extension is thin for the same reason the opencode plugin is: waiting lives in
`wake.py` and is harness-agnostic. Most of what follows is about keeping it thin, and
about the two things omp adds that the opencode plugin never had to think about —
extensions share the session's process with no isolation, and the default delivery mode
*interrupts*.
"""

from pathlib import Path

import pytest

from agent_inbox import hookconfig


class TestOmpGetsAnExtension:
    def test_it_lands_where_omp_loads_from(self, tmp_path: Path) -> None:
        """`<cwd>/.omp/extensions/` is scanned at startup for `.ts` and `.js`
        (`docs/extension-loading.md`) — a known place, needing no registration."""
        path = hookconfig.install_for("omp", tmp_path)

        assert path == tmp_path / ".omp" / "extensions" / "agent-inbox-wake.js"
        assert path.exists()

    def test_it_is_a_default_exported_factory(self, tmp_path: Path) -> None:
        """The one shape the loader accepts."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "export default function (pi)" in source

    def test_it_arms_when_the_agent_goes_quiet_and_when_the_session_opens(
        self, tmp_path: Path
    ) -> None:
        """`agent_end` is this harness's `Stop`. `session_start` as well, because a
        session that has never taken a turn is idle too, and the opencode plugin —
        armed on idle only — cannot reach one of those."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert 'pi.on("agent_end"' in source
        assert 'pi.on("session_start"' in source

    def test_it_runs_our_waiter_rather_than_reimplementing_one(
        self, tmp_path: Path
    ) -> None:
        """The property that keeps this thin — see `test_opencode_waking`."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "wake-check" in source
        assert '"--wait"' in source

    def test_the_command_is_argv_because_exec_has_no_shell(
        self, tmp_path: Path
    ) -> None:
        """`pi.exec(command, args)` spawns `[command, ...args]` directly. A quoted
        string handed to it whole would be looked up as one program named
        `/path/to/python -m agent_inbox wake-check`, and not found."""
        source = hookconfig.install_for(
            "omp", tmp_path, command="'/a dir/python' -m agent_inbox wake-check"
        ).read_text()

        assert '["/a dir/python", "-m", "agent_inbox", "wake-check"]' in source
        assert "pi.exec(" in source
        assert "argv[0], argv.slice(1).concat(args)" in source

    def test_it_tells_the_waiter_whose_identity_to_wait_for(
        self, tmp_path: Path
    ) -> None:
        """A process omp starts for an extension carries no marker at all — not even
        the Claude one it gives its shell — so the waiter cannot detect its engine, and
        a project with two agents configured is unresolvable. The extension says."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert '"--engine", "omp"' in source

    def test_it_delivers_only_on_the_wake_exit_code(self, tmp_path: Path) -> None:
        """Exit 2 means "there is mail". Exit 0 means the waiter re-armed or timed out,
        and delivering on that would wake an agent to tell it nothing. A killed child
        — aborted at shutdown — is not a wake either, whatever its code."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "run.code === 2" in source
        assert "!run.killed" in source

    def test_it_holds_one_waiter_at_a_time(self, tmp_path: Path) -> None:
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "holding" in source

    def test_installing_twice_replaces_rather_than_appends(
        self, tmp_path: Path
    ) -> None:
        hookconfig.install_for("omp", tmp_path)
        first = hookconfig.omp_extension_path(tmp_path).read_text()
        hookconfig.install_for("omp", tmp_path)

        assert hookconfig.omp_extension_path(tmp_path).read_text() == first

    def test_nothing_else_is_written(self, tmp_path: Path) -> None:
        hookconfig.install_for("omp", tmp_path)

        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / ".opencode").exists()

    def test_uninstall_is_absent_is_success(self, tmp_path: Path) -> None:
        hookconfig.install_for("omp", tmp_path)
        hookconfig.uninstall_omp(tmp_path)
        hookconfig.uninstall_omp(tmp_path)

        assert not hookconfig.omp_extension_path(tmp_path).exists()


class TestWakingIsNotInterrupting:
    """The prompt promises it: *the waiter reaches you at a turn boundary … it will not
    cut into work already running.* omp's default delivery mode breaks that promise."""

    def test_it_never_uses_the_default_delivery_mode(self, tmp_path: Path) -> None:
        """`deliverAs: "steer"` is the default and **interrupts the current run**.
        `followUp` queues until the run finishes."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert '"steer"' not in source.replace("`steer`", "")
        assert 'deliverAs: "followUp"' in source

    def test_it_actually_wakes_an_idle_session(self, tmp_path: Path) -> None:
        """`followUp` alone would sit in the queue until the human's next prompt —
        opencode's `session.prompt` behaviour, and no better. `triggerTurn` is what
        makes this a wake rather than a wait."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "triggerTurn: true" in source


class TestTheSessionSurvivesTheExtension:
    """Extensions run in-process with no isolation (`docs/extensions.md`): a raw timer
    or detached promise that throws is an `uncaughtException`, and the whole session is
    torn down. A mailbox that can crash somebody's agent is worse than no mailbox."""

    def test_the_waiter_runs_under_a_managed_timer(self, tmp_path: Path) -> None:
        """`ctx.setTimeout` runs its callback with handler-dispatch isolation — a
        rejected promise is logged, not fatal — and is cleared on shutdown."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "ctx.setTimeout(" in source
        assert "setInterval(" not in source
        assert " setTimeout(" not in source.replace("ctx.setTimeout(", "")

    def test_the_handler_does_not_await_the_waiter(self, tmp_path: Path) -> None:
        """An `agent_end` handler awaited for hours holds every other extension's
        handler behind it. The `arm` function returns at once."""
        source = hookconfig.install_for("omp", tmp_path).read_text()
        arm = source[source.index("const arm =") : source.index("ctx.setTimeout(")]
        code = "\n".join(
            line for line in arm.splitlines() if not line.strip().startswith("//")
        )

        assert "await" not in code

    def test_the_child_is_aborted_at_shutdown(self, tmp_path: Path) -> None:
        """Otherwise a `wake-check --wait` outlives the session it was armed for,
        holding
        the hub's stream for up to eight hours on behalf of nobody."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert 'pi.on("session_shutdown"' in source
        assert "abort.abort()" in source
        assert "signal: abort.signal" in source


class TestTheNoticeIsNeverAMessageBody:
    """The load-bearing safety property, as on opencode: the notice lands in the
    conversation, so a body would read as an instruction, and any peer who can write to
    this agent could steer it. ADR 0008 broken at the root."""

    def test_the_extension_passes_the_waiter_text_through_unaltered(
        self, tmp_path: Path
    ) -> None:
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert "run.stderr" in source
        assert "content: said" in source

    def test_it_does_not_claim_the_human_said_it(self, tmp_path: Path) -> None:
        """omp's `normalizeCustomMessagePayload` defaults `attribution` to `"agent"`
        and yields `"user"` only when asked. This must never ask."""
        source = hookconfig.install_for("omp", tmp_path).read_text()

        assert 'attribution: "user"' not in source
        assert "sendUserMessage" not in source

    def test_the_waiter_it_calls_never_emits_a_body(self) -> None:
        """Asserted against `wake` itself, because that is where the guarantee lives."""
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


class TestTheOtherHarnessesAreUnaffected:
    def test_claude_and_opencode_still_write_their_own_files(
        self, tmp_path: Path
    ) -> None:
        hookconfig.install_for("claude", tmp_path)
        hookconfig.install_for("opencode", tmp_path)

        assert hookconfig.settings_path(tmp_path).exists()
        assert hookconfig.plugin_path(tmp_path).exists()
        assert not hookconfig.omp_extension_path(tmp_path).exists()

    def test_an_unknown_harness_is_still_refused(self, tmp_path: Path) -> None:
        with pytest.raises(hookconfig.NoWakingHere):
            hookconfig.install_for("some-future-harness", tmp_path)

        assert not (tmp_path / ".omp").exists()


class TestTheWaiterCanBeToldItsEngine:
    """The other half of naming the engine: the waiter has to listen."""

    def test_run_passes_the_engine_to_config_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox import wake
        from agent_inbox.client import NotConfigured

        asked: list[str | None] = []

        def load_config(*, start: Path, engine: str | None = None) -> object:
            asked.append(engine)
            raise NotConfigured("stop here")

        monkeypatch.setattr(wake, "load_config", load_config)

        wake.run("Stop", root=tmp_path, engine="omp")

        assert asked == ["omp"]

    def test_wake_check_accepts_engine_on_the_subcommand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The form the extension uses: `wake-check --engine omp …`."""
        from click.testing import CliRunner

        from agent_inbox import cli as cli_module
        from agent_inbox import wake

        seen: dict[str, object] = {}

        def run(event: str, **kwargs: object) -> int:
            seen.update(kwargs)
            return 0

        monkeypatch.setattr(wake, "run", run)

        CliRunner().invoke(
            cli_module.cli, ["wake-check", "--engine", "omp", "--event", "Stop"]
        )

        assert seen.get("engine") == "omp"

    def test_the_group_option_reaches_it_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`agent-inbox --engine omp wake-check`, for a human at a shell."""
        from click.testing import CliRunner

        from agent_inbox import cli as cli_module
        from agent_inbox import wake

        seen: dict[str, object] = {}

        def run(event: str, **kwargs: object) -> int:
            seen.update(kwargs)
            return 0

        monkeypatch.setattr(wake, "run", run)

        CliRunner().invoke(cli_module.cli, ["--engine", "omp", "wake-check"])

        assert seen.get("engine") == "omp"
