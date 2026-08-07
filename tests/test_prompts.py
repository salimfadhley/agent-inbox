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

    def test_the_pasteable_block_is_safe_to_paste_whole(self) -> None:
        """`igor_laszlo`, 2026-08-05: a comment is the part a reader pastes past.

        The fetch briefly sat inside the block with a trailing "skip this if you already
        have 3.14". He pointed out that somebody mid-onboarding wants the commands to
        just work, and that the failure is silent and self-inflicted — nothing errors,
        they quietly own two interpreters.

        So the block looks and installs; it does not fetch. Most readers already have a
        3.14, and the one who does not is the one definitely reading.
        """
        from agent_inbox.prompts import _install, _python_floor

        for version in ("", "0.66.0"):
            # The block that installs the tool — not the first fenced block, which on
            # the versioned path is the `agent-inbox --version` check.
            block = next(
                part.split("```", 1)[0]
                for part in _install(version).split("```bash")[1:]
                if "uv tool install" in part.split("```", 1)[0]
            )
            lines = [
                line for line in block.splitlines() if line.strip().startswith("uv ")
            ]

            assert lines[0].startswith("uv python list"), lines
            assert lines[1].startswith("uv tool install --upgrade --python "), lines
            assert f"uv python install {_python_floor()}" not in block, (
                f"the fetch is inside the pasteable block (version={version!r})"
            )

    def test_the_fetch_is_still_offered_to_whoever_needs_it(self) -> None:
        """The paired positive. Making the block safe must not strand the reader the
        step exists for — the one with no 3.14 at all, for whom the pin simply fails."""
        from agent_inbox.prompts import _install, _python_floor

        for version in ("", "0.66.0"):
            text = _install(version)

            assert f"uv python install {_python_floor()}" in text, version
            assert "Only if" in text or "only if" in text, version

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

        assert "Do not run that otherwise" in text, "the fetch is not marked optional"
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

        assert found.command[:6] == (
            "uv",
            "tool",
            "install",
            "--upgrade",
            "--python",
            "3.14",
        )


class TestTheVersionFloorIsCalibratedNotChosen:
    """`igor_laszlo`, 2026-08-05: *"the `>=0.17.1` floor sits BELOW 0.34.0, the version
    that caused the original silent-downgrade bug"*.

    He was right, and said plainly he might be wrong about the floor's purpose. He was
    not: the prompt states it is there so a resolver that cannot reach a current release
    **fails and tells you**. `0.34.0 >= 0.17.1` is comfortably true, so the exact
    resolution that produced the incident sailed through the guard.

    **The right value is readable from the index rather than picked.** Every release up
    to and including 0.34.0 declares `requires-python >=3.12`; 0.35.0 is the first to
    declare `>=3.14`. So 0.35.0 is precisely the lowest floor an old interpreter cannot
    satisfy — one version lower and the guard is decoration again.
    """

    #: The last release installable on an interpreter below our floor, confirmed against
    #: PyPI on 2026-08-05, and the version `igor_laszlo`'s machine actually landed on.
    LAST_OLD_PYTHON_RELEASE = (0, 34, 0)

    @staticmethod
    def _parts(version: str) -> tuple[int, ...]:
        return tuple(int(n) for n in version.split(".")[:3])

    def test_the_floor_excludes_the_version_the_incident_landed_on(self) -> None:
        from agent_inbox.staleness import INSTALL_FLOOR

        assert self._parts(INSTALL_FLOOR) > self.LAST_OLD_PYTHON_RELEASE, (
            f"{INSTALL_FLOOR} still admits 0.34.0 — the guard is decoration"
        )

    def test_it_is_not_merely_high(self) -> None:
        """The paired concern, and the reason not to 'fix' this by pinning to current.

        A floor near the newest release makes every publish briefly unsatisfiable,
        because the install index trails a publish by minutes. 0.35.0 is the boundary
        and nothing above it buys anything.
        """
        from agent_inbox.staleness import INSTALL_FLOOR

        assert self._parts(INSTALL_FLOOR) == (0, 35, 0)

    def test_the_floor_reaches_the_prompt(self) -> None:
        """It is a constant until something renders it."""
        from agent_inbox.prompts import _install
        from agent_inbox.staleness import INSTALL_FLOOR

        assert f">={INSTALL_FLOOR}" in _install("0.71.0")


class TestOneInstallCommandForEverySurface:
    """`igor_laszlo` again: `doctor` printed the **unpinned** command while the prompt
    gave the pinned, floored one — so an agent that ran `doctor` *because it was already
    confused* was handed the exact form that silently resolves to an old release.

    His proposed fix is this one: *"generated from one string, the same way you fixed
    the two prompt copies — otherwise this drifts again the next time the install advice
    changes, and it changed four times today."*
    """

    def test_the_notice_and_the_prompt_carry_the_same_command(self) -> None:
        from agent_inbox import staleness
        from agent_inbox.prompts import _install

        staleness.reset()
        staleness.note_hub_version("999.0.0")
        told = staleness.notice() or ""
        staleness.reset()

        command = staleness.upgrade_command()

        assert command in told, "doctor's advice is not the canonical command"
        assert command in _install("0.71.0"), "the prompt's is not either"

    def test_the_command_carries_every_flag_that_matters(self) -> None:
        """Each of these was added because its absence cost somebody real work: the pin
        (uv will not move a tool between interpreters), the floor (an old interpreter
        resolves to a pre-3.14 release), `--upgrade` (a plain install is a no-op when
        the tool exists) and `--refresh` (a cached index predates the release you need).

        `--upgrade` replaced `--force` on 2026-08-07, measured rather than assumed: it
        replaces an installed tool exactly as `--force` does — 0.85.0 to 0.90.0 in a
        scratch tool dir — while skipping the package reinstall `--force` performs even
        when nothing has changed. It does **not** avoid the Windows entrypoint lock;
        both write the launcher every run, and the prompt says so rather than implying
        a flag fixed it."""
        from agent_inbox.staleness import (
            INSTALL_FLOOR,
            interpreter_pin,
            upgrade_command,
        )

        command = upgrade_command()

        assert f"--python {interpreter_pin()}" in command
        assert f">={INSTALL_FLOOR}" in command
        assert "--upgrade" in command
        assert "--refresh" in command
