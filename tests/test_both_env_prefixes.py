"""Advice names the current variable; both variables still work (issue #63).

Found because `aurelia_saahaa`, the first agent here on opencode, followed our own
error message and it sent them to the **deprecated** name. They had tried
`AGENT_INBOX_NAME` first — correctly — and our text talked them out of it.

Two properties, and they pull in opposite directions, which is why both are held here:

**What we accept must not narrow.** `AGENT_MAILBOX_*` is honoured, `agent-mailbox.toml`
is read, `import agent_mailbox` resolves. The charter promises all of it and a
deployment configured entirely under the old names must keep working. This changes what
we *advise*, never what we *accept*.

**What we advise must be current.** A message naming the deprecated variable is worse
than one naming none, because a reader who follows it ends up on a name we are trying to
retire — and believes they were told to.

The direct reads are the substantive half. `hub_settings.env_with_source` already knew
how to try both prefixes; four call sites read the environment a second way and saw only
the legacy name, which is how the two came apart.
"""

import os
from pathlib import Path

import pytest


class TestBothPrefixesAreHonoured:
    """The four reads that bypassed the helper. Each failed for the current name."""

    def test_the_current_token_variable_is_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug. An operator who set `AGENT_INBOX_TOKEN` with no config file got
        nothing, and no explanation of why."""
        from agent_inbox.cli import _env_token

        monkeypatch.delenv("AGENT_MAILBOX_TOKEN", raising=False)
        monkeypatch.setenv("AGENT_INBOX_TOKEN", "current-name")

        assert _env_token() == "current-name"

    def test_the_legacy_token_variable_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**The paired positive, and the one that matters most.** Without it, a fix
        that simply renamed the string would pass the test above and break every
        deployment configured before the rename — which the charter forbids outright."""
        from agent_inbox.cli import _env_token

        monkeypatch.delenv("AGENT_INBOX_TOKEN", raising=False)
        monkeypatch.setenv("AGENT_MAILBOX_TOKEN", "legacy-name")

        assert _env_token() == "legacy-name"

    def test_the_current_name_wins_when_both_are_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox.cli import _env_token

        monkeypatch.setenv("AGENT_MAILBOX_TOKEN", "legacy-name")
        monkeypatch.setenv("AGENT_INBOX_TOKEN", "current-name")

        assert _env_token() == "current-name"

    def test_doctor_reports_the_variable_actually_in_effect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`env_with_source` returns the name alongside the value for this reason. A
        deployment running on the legacy variable must be told to edit *that* one —
        pointing it at the name we prefer sends somebody to a variable that is not
        governing anything, and they conclude the tool is broken."""
        from agent_inbox.cli import _env_token_source

        monkeypatch.delenv("AGENT_INBOX_TOKEN", raising=False)
        monkeypatch.setenv("AGENT_MAILBOX_TOKEN", "legacy-name")

        assert _env_token_source() == "AGENT_MAILBOX_TOKEN"

    def test_nothing_set_is_not_a_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The paired negative: an empty environment must not produce a credential."""
        from agent_inbox.cli import _env_token, _env_token_source

        monkeypatch.delenv("AGENT_INBOX_TOKEN", raising=False)
        monkeypatch.delenv("AGENT_MAILBOX_TOKEN", raising=False)

        assert _env_token() == ""
        assert _env_token_source() == ""

    def test_the_console_url_override_honours_the_current_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same defect in the console: a deployment setting
        `AGENT_INBOX_CONSOLE_URL` had it silently ignored."""
        from agent_inbox.hub_settings import env_with_source

        monkeypatch.delenv("AGENT_MAILBOX_CONSOLE_URL", raising=False)
        monkeypatch.setenv("AGENT_INBOX_CONSOLE_URL", "https://console.example")

        found = env_with_source("CONSOLE_URL", os.environ)
        assert found is not None and found[0] == "https://console.example"


class TestAdviceNamesTheCurrentVariable:
    """The half `aurelia_saahaa` actually hit."""

    def _sources(self) -> str:
        root = Path(__file__).resolve().parents[1] / "src" / "agent_inbox"
        return "\n".join(
            p.read_text()
            for p in sorted(root.rglob("*.py"))
            if p.name != "hub_settings.py"
        )

    def test_no_advice_string_names_the_deprecated_variable(self) -> None:
        """Asserted as an absence across the whole package.

        Excluded: `hub_settings.py`, which defines `LEGACY_ENV_PREFIX` and is the one
        place the old name is load-bearing rather than advisory.

        Any remaining mention must be prose *about* the legacy name — history, or a
        docstring explaining compatibility — never an instruction to set one.
        """
        import re

        offenders = []
        for line in self._sources().splitlines():
            named = set(re.findall(r"AGENT_MAILBOX_([A-Z_]+)", line))
            # A line naming *both* forms is a declaration of the pair, not advice —
            # `client.py`'s precedence table is exactly that and must stay.
            unpaired = {n for n in named if f"AGENT_INBOX_{n}" not in line}
            if unpaired and "legacy" not in line.lower():
                offenders.append(line.strip())

        assert not offenders, (
            "these name the deprecated variable outside a legacy note:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_mcp_server_now_names_the_current_one(self) -> None:
        """The exact three strings that misled the first opencode agent."""
        from pathlib import Path as P

        text = (
            P(__file__).resolve().parents[1] / "src" / "agent_inbox" / "mcp_client.py"
        ).read_text()

        assert "AGENT_INBOX_NAME" in text
        assert "AGENT_MAILBOX_NAME" not in text


class TestTheCompatibilitySurfaceIsUntouched:
    """The charter's promise, and the thing this change must not have broken."""

    def test_the_import_alias_still_resolves(self) -> None:
        import agent_inbox
        import agent_mailbox

        assert agent_mailbox.__version__ is agent_inbox.__version__

    def test_the_legacy_config_filename_is_still_read(self) -> None:
        from agent_inbox.client import CONFIG_NAMES, LEGACY_CONFIG_NAME

        assert LEGACY_CONFIG_NAME in CONFIG_NAMES

    def test_the_legacy_prefix_is_still_declared(self) -> None:
        from agent_inbox.hub_settings import ENV_PREFIX, LEGACY_ENV_PREFIX

        assert LEGACY_ENV_PREFIX == "AGENT_MAILBOX_"
        assert ENV_PREFIX == "AGENT_INBOX_"
