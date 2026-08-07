"""The new package's boundaries.

Small, but not vacuous: the clean-slate rule is a decision, and a decision nobody
checks is a decision that erodes. `agent_inbox_old` is deliberately still installed
and importable — which is exactly why an accidental dependency on it would be easy to
introduce and invisible until the old package is deleted.
"""

import pkgutil
from importlib.metadata import version
from pathlib import Path

import agent_inbox


def test_package_reports_a_version() -> None:
    assert agent_inbox.__version__


def test_the_version_is_read_from_the_real_distribution_name() -> None:
    """The distribution is `agent-inbox`; the import package is `agent_inbox`.

    Looking up the wrong one does not raise — `__version__` quietly becomes the
    `0.0.0.dev0` fallback and stays there. That matters more than it used to: the
    onboarding prompt asks every arriving agent to compare this number against the
    hub's, so a silent 0.0.0 would tell all of them to reinstall, every session,
    forever. Cheap to pin, invisible if it breaks.
    """
    assert agent_inbox.__version__ == version("agent-inbox")
    assert agent_inbox.__version__ != "0.0.0.dev0", "metadata lookup fell back"


def test_new_package_never_imports_the_superseded_one() -> None:
    """We are starting from scratch, not refactoring the old implementation.

    Checked by source text rather than by import, so it catches a reference even
    before it would fail at runtime.
    """
    root = Path(agent_inbox.__file__).parent
    offenders: list[str] = []
    for module in pkgutil.walk_packages([str(root)], prefix="agent_inbox."):
        source = Path(module.module_finder.path) / f"{module.name.split('.')[-1]}.py"  # type: ignore[union-attr]
        if source.is_file() and "agent_inbox_old" in source.read_text():
            offenders.append(module.name)
    assert not offenders, f"new code must not reference the old package: {offenders}"


class TestTheAdvertisedFloorIsObtainable:
    """The hub must not tell arriving agents to install something that does not exist.

    The floor used to be the hub's own version. PyPI's install index trails a publish by
    minutes, so every release opened a window where the prompt named a version no
    resolver could reach — hit by rowan_delacourt once and by ludmila_coe on three
    separate releases, at which point it was the rule rather than bad luck.

    It also demanded an upgrade nobody needed: a client several releases old talks to a
    current hub perfectly well.
    """

    def test_the_floor_is_not_the_current_version(self) -> None:
        """Both floors, since they were separated on 2026-08-05 — the reason to keep
        each off the current version is the same for either."""
        from agent_inbox import __version__
        from agent_inbox.prompts import MINIMUM_CLIENT
        from agent_inbox.staleness import INSTALL_FLOOR

        assert INSTALL_FLOOR != __version__, (
            "the install floor tracks the release again — every release will advertise "
            "a version the install index cannot yet satisfy"
        )
        assert MINIMUM_CLIENT != __version__, (
            "the floor tracks the release again — every release will advertise a "
            "version the install index cannot yet satisfy"
        )

    # Deliberately not asserted here: that the floor is *resolvable from PyPI*. That
    # is the property that matters and it cannot be checked offline — the local
    # `__version__` is a dev string from the working tree, not a released one, so a
    # comparison against it fails on a developer machine and passes in CI for reasons
    # unrelated to the floor. Checking a live index belongs in the release gate
    # (release-prompt-package-verification-01KYG9MS), which resolves the exact command
    # this prompt prints, against the surface an agent actually installs from.

    def test_the_prompt_advertises_the_floor_not_the_hub_version(self) -> None:
        from agent_inbox.prompts import onboarding
        from agent_inbox.staleness import INSTALL_FLOOR

        prompt = onboarding("http://hub.invalid", version="99.99.99")
        assert f'"agent-inbox[clients]>={INSTALL_FLOOR}"' in prompt
        assert "clients]>=99.99.99" not in prompt, (
            "the install command still pins the hub's own version"
        )
        assert "99.99.99" in prompt, "the reader should still be told what the hub runs"


class TestTheOldCommandNameIsGone:
    """Owner, 2026-08-05: delete the `agent-mailbox` console script.

    **This is the one old name that has been removed**, and the distinction matters
    because the charter promises a great deal about the others. `import agent_mailbox`
    still resolves to the same module objects; `agent-mailbox.toml` is still read; the
    `AGENT_MAILBOX_*` variables are still honoured. This removes a *command*, not a
    promise about data or imports — and an install made before the removal keeps its own
    entry point until it is upgraded, so nothing breaks the day it ships.

    It survived this long because it was wired into deployments and hooks. It is not any
    more: the wake hook has installed `agent-inbox wake-check` for many releases, and
    the onboarding prompt names `agent-inbox` throughout.
    """

    def _scripts(self) -> dict[str, str]:
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        return tomllib.loads((root / "pyproject.toml").read_text())["project"][
            "scripts"
        ]

    def test_the_removed_alias_has_not_come_back(self) -> None:
        assert "agent-mailbox" not in self._scripts()

    def test_every_command_is_the_same_program(self) -> None:
        """**Rewritten on 2026-08-07, when `aiai` was added** (owner) as a short name
        for a human at a terminal.

        This used to assert `set(scripts) == {"agent-inbox"}`, and its message said "the
        removed alias is back, or a new one appeared" — so it was guarding two things at
        once and could not tell them apart. The first still matters and is asserted
        above. The second was never the real rule: what makes an extra name harmless is
        that it is an *alias*, not a second program that can drift.

        So that is what is checked. A new entry pointing somewhere else fails here, and
        `agent-mailbox` returning fails above, which is strictly more than counting.
        """
        scripts = self._scripts()

        assert scripts, "precondition: some console script is declared"
        assert set(scripts.values()) == {"agent_inbox.cli:main"}, (
            f"a console script points somewhere else: {scripts}"
        )
        assert "agent-inbox" in scripts, (
            "the documented command must stay: removing it breaks every existing "
            "install, hook and deployment"
        )

    def test_the_import_alias_is_untouched(self) -> None:
        """The paired positive, and the promise that has *not* changed. Removing the
        command must not be read as licence to drop the module alias — that one is a
        real alias, not a copy, and something already installed depends on it."""
        import agent_inbox
        import agent_mailbox

        assert agent_mailbox.__version__ is agent_inbox.__version__
