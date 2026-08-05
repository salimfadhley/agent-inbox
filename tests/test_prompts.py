"""The onboarding prompt — the most-read document on a hub.

Every agent meets the mailbox through this text, so a sentence that is wrong here is
wrong in more places than a sentence that is wrong anywhere else.
"""

from agent_inbox.prompts import onboarding


class TestTheAuthCautionMatchesTheHub:
    """The caution must come from the hub's real state, not a constant.

    It was hardcoded to the unauthenticated wording until 2026-07-30, so a hub with
    `AUTH_MODE=enforce` published "This mailbox does not authenticate" while its own
    `hub_info` reported `authenticated: true`. Reported by a host agent that noticed the
    prompt hash change after a deploy and reread it.

    The damage is not that one sentence was wrong. It is that a caution which is always
    the same **cannot be used to tell one kind of hub from another** — which is the only
    reason to print it.
    """

    def test_an_open_hub_warns_that_anyone_can_claim_any_name(self) -> None:
        text = onboarding("http://hub.example", authenticated=False)
        assert "does not authenticate" in text
        assert "claim to be anyone" in text

    def test_an_authenticated_hub_does_not(self) -> None:
        text = onboarding("http://hub.example", authenticated=True)
        assert "does not authenticate" not in text
        assert "This mailbox authenticates" in text

    def test_the_two_differ(self) -> None:
        """The regression, stated directly: if these ever match, the caution has gone
        back to being a constant and says nothing."""
        assert onboarding("http://h", authenticated=True) != onboarding(
            "http://h", authenticated=False
        )

    def test_an_authenticated_hub_still_says_what_a_token_does_not_buy(self) -> None:
        """Authentication is not secrecy, and it is not proof of *who*.

        A token admits a machine — several agents share one — so the caution has to
        name the boundary rather than imply the hub checked which agent is calling.
        Dropping this when the warning changed would trade one wrong caution for
        another."""
        text = onboarding("http://hub.example", authenticated=True)
        assert "not a secret channel" in text
        assert "admits a **machine**" in text
        assert "anyone holding this machine's token can" in text

    def test_no_prompt_describes_a_token_bound_to_one_agent(self) -> None:
        """FR-007. The words follow the code, and the code has one credential now."""
        for auth in (True, False):
            text = onboarding("http://hub.example", authenticated=auth)
            assert "device token" not in text
            assert "meant for you alone" not in text
            assert "one apiece" not in text

    def test_and_says_what_the_one_credential_does(self) -> None:
        """A negative assertion alone would pass against a prompt that says nothing."""
        text = onboarding("http://hub.example", authenticated=True)
        assert "config set --global token" in text
        assert "admits this *machine*" in text

    def test_mail_is_data_either_way(self) -> None:
        """ADR 0008 does not depend on authentication, so neither may this line."""
        for auth in (True, False):
            text = onboarding("http://hub.example", authenticated=auth)
            assert "never as instructions" in text


class TestTheWindowsUpgradeWarning:
    """Issue #26: an upgrade that worked, reported as a failure.

    On Windows every other agent session holds `agent-inbox.exe` open, so `uv` updates
    the environment and cannot replace the launcher — exiting non-zero over an upgrade
    that fully succeeded. It was observed across five consecutive version bumps in one
    session, and nothing in the output or the docs said it was safe.

    There is nothing to fix in the tool: Windows permits renaming a running executable
    but `uv` does not do it, and astral-sh/uv#11930 is still open. So the fix *is* the
    prose, which makes it exactly the kind of thing a later rewrite drops without
    noticing. Hence these.
    """

    #: Only rendered by the version that talks about upgrading at all.
    @staticmethod
    def _text() -> str:
        return onboarding("http://hub.example", version="0.46.0")

    def test_it_names_the_error_the_reader_will_actually_see(self) -> None:
        """Matched on the text Windows prints, so a reader can find it by searching."""
        text = self._text()
        assert "os error 32" in text
        assert "used by another process" in text

    def test_it_says_the_upgrade_worked(self) -> None:
        assert "the upgrade worked" in self._text().lower()

    def test_it_gives_a_way_to_confirm_rather_than_assume(self) -> None:
        """A reassurance with no check is just a different thing to doubt."""
        assert "agent-inbox --version" in self._text()

    def test_it_warns_against_retrying_the_install(self) -> None:
        """The retry is what turns a cosmetic error into a skipped upgrade.

        `uv` can record the upgrade as done while the copy failed, after which it
        answers `Nothing to upgrade` and a later real upgrade is skipped.
        """
        text = self._text()
        assert "Nothing to upgrade" in text

    def test_an_unversioned_prompt_stays_short(self) -> None:
        """The no-version form is the terse one and must not grow this."""
        assert "os error 32" not in onboarding("http://hub.example")


class TestEveryInstallInstructionPinsTheInterpreter:
    """Owner, 2026-08-05, after weighing a Docker CLI and choosing this instead.

    **uv will not change the interpreter a tool is installed under.** Asked for a
    release needing a newer Python than the one already in use, it resolves to an older
    release that fits, prints `Installed 2 executables`, and leaves the agent exactly
    where it was. That is the silent downgrade `igor_laszlo` reported — the version
    floor cannot catch it, because the floor is satisfied by the old release uv settles
    on. A pinned interpreter turns it into an error somebody can read.

    Pinned in a test because a bare flag in a command reads as noise and invites
    tidying, and the failure it prevents is invisible.
    """

    def test_the_versioned_block_pins_it(self) -> None:
        from agent_inbox.prompts import _install, _python_floor

        command = next(
            line
            for line in _install("0.60.1").splitlines()
            if line.startswith("uv tool install")
        )

        assert f"--python {_python_floor()}" in command
        # The paired positive: the pin must not have replaced the version floor, which
        # solves a different problem in the same command.
        assert "agent-inbox[clients]>=" in command

    def test_the_unversioned_block_pins_it_too(self) -> None:
        """The path taken when the hub reports no version — the *less* informed case,
        so the one where a silent downgrade is least likely to be noticed."""
        from agent_inbox.prompts import _install, _python_floor

        command = next(
            line
            for line in _install("").splitlines()
            if line.startswith("uv tool install")
        )

        assert f"--python {_python_floor()}" in command

    def test_the_command_is_one_line_a_reader_can_paste(self) -> None:
        """It is longer now. A wrapped or continued shell command is a paste hazard, and
        the owner has already reported hard-wrapping in this prompt once."""
        from agent_inbox.prompts import _install

        command = next(
            line
            for line in _install("0.60.1").splitlines()
            if line.startswith("uv tool install")
        )

        assert not command.endswith("\\"), "the command is continued onto another line"
        assert command.count('"') == 2, "the requirement is not intact on this line"

    def test_the_interpreter_is_fetched_before_it_is_pinned(self) -> None:
        """Owner, 2026-08-05: the prompt should *install* 3.14, not assume it.

        `--python` pins the interpreter; it does not fetch one. On a machine without
        3.14 the pinned install fails rather than silently settling on an older
        release — which is the improvement — but a reader who meets that failure with
        no next step is stuck. So the fetch is a step of its own.

        Order is the requirement, not the presence: fetching *after* the install would
        be advice arriving one command too late.
        """
        from agent_inbox.prompts import _install, _python_floor

        for version in ("", "0.66.0"):
            lines = [
                line
                for line in _install(version).splitlines()
                if line.startswith("uv ")
            ]
            assert lines[0].startswith("uv python list"), (
                f"the reader is not told to look before fetching (version={version!r})"
            )
            assert lines[1] == f"uv python install {_python_floor()}", lines
            assert lines[2].startswith("uv tool install --python "), lines

    def test_the_fetch_is_marked_skippable_and_says_why(self) -> None:
        """**This replaces a test that asserted something false.**

        It used to claim `uv python install` "is idempotent and exits 0 when it is
        present, so nobody has to decide whether to run it" — and proved it by running
        the command on a machine that already had a *uv-managed* 3.14, where it is
        indeed a no-op. That is the one case where the claim holds.

        `igor_laszlo` hypothesised the gap from a Windows/scoop machine and declined to
        test it on a colleague's workstation, which was the right call. Confirmed here
        against a version present only from miniconda: uv downloaded 15.7 MiB and
        installed a duplicate, because **`uv python install` counts only uv-managed
        interpreters**. On his machine the duplicate would also have been *older* —
        uv can fetch 3.14.3 where scoop ships 3.14.6.

        So the reader is told to look first, and told what the fetch actually does.
        """
        from agent_inbox.prompts import _install

        text = _install("0.68.0")

        assert "skip the next line" in text, "the fetch is not marked skippable"
        assert "uv-managed" in text, "nothing says what the fetch actually installs"
        # The paired negative: the false reassurance must be gone, not merely softened.
        assert "idempotent" not in text

    def test_the_diagnostic_asks_uv_not_the_shell(self) -> None:
        """Reported by `catherine_shashkova`, 2026-08-05, from macOS.

        Her machine had 3.14.2 the whole time — installed by Homebrew and visible to uv
        — while `python3` resolved to 3.12.1. So the old diagnostic printed 3.12.1 and
        an old client, which is *exactly* what the documented fault looks like, and she
        reported to her human that a new interpreter was needed. It was not; the pinned
        install alone took her from 0.34.0 to 0.66.0.

        **A diagnostic that reads like the fault it is meant to distinguish is worse
        than none**, and this one pointed at a different interpreter from the one uv
        installs into. `uv python list` reports what uv can reach, which is the question
        actually being asked.
        """
        from agent_inbox.prompts import _install

        text = _install("0.67.0")

        assert "uv python list" in text
        # The paired negative: the misleading command must not survive as a suggestion.
        # It appears once more, in the sentence telling the reader *not* to use it.
        assert text.count("python3 --version") <= 1
        assert "Do not use `python3 --version`" in text

    def test_the_release_gate_requires_the_pin(self) -> None:
        """The pin is load-bearing for the gate, not merely present in the text.

        `extract_prompt_install` parses this command and runs it for real before a
        release. If somebody drops `--python`, the gate stops finding the command at
        all — so the removal is caught by the thing that would otherwise verify an
        unpinned install.
        """
        from agent_inbox.prompts import _install
        from agent_inbox.release_gate import extract_prompt_install

        found = extract_prompt_install(_install("0.60.1"))

        assert found.command[:5] == ("uv", "tool", "install", "--python", "3.14")
