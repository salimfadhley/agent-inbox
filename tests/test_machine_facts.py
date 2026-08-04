"""What a machine says about itself, and — more importantly — what it does not.

The whole point of this module is a *narrowing*: the client knows the absolute path of
the checkout and deliberately sends two segments of it, because the head of that path
names a person. A test that only checked "root is present" would pass just as happily
if the trimming were deleted, so the tests here are written against the thing that must
not regress rather than against the thing that must appear.
"""

from pathlib import Path

import pytest

from agent_inbox.machine import (
    FACT_KEYS,
    OPT_OUT_VARS,
    ROOT_SEGMENTS,
    checkout,
    machine_facts,
    merged_into,
    opted_out,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout several directories below an account-shaped path."""
    root = tmp_path / "Users" / "someone" / "workspace" / "billing"
    (root / ".git").mkdir(parents=True)
    return root


def test_checkout_is_the_tail_and_nothing_above_it(repo: Path) -> None:
    assert checkout(repo) == "workspace/billing"


def test_checkout_never_discloses_the_account_the_project_sits_under(
    repo: Path,
) -> None:
    # The removal proof for ROOT_SEGMENTS. Widen the trim and this fails: "someone" is
    # a person's account name, and it is one path segment away from being published to
    # every operator signed in to the hub.
    disclosed = checkout(repo)
    assert "someone" not in disclosed
    assert str(repo) not in disclosed
    assert not Path(disclosed).is_absolute()
    assert len(disclosed.split("/")) == ROOT_SEGMENTS


def test_a_checkout_directly_in_the_home_directory_still_hides_the_account(
    tmp_path: Path,
) -> None:
    """The case a segment count gets wrong, and the reason the home anchor exists.

    `/home/sal/agent-inbox` has the account name in its last two segments, so trimming
    to two would have published `sal/agent-inbox`. Cloning a project straight into a
    home directory is an ordinary thing to do, not an edge case.
    """
    home = tmp_path / "home" / "sal"
    root = home / "agent-inbox"
    (root / ".git").mkdir(parents=True)
    disclosed = checkout(root, home=home)
    assert disclosed == "agent-inbox"
    assert "sal" not in disclosed


def test_the_home_directory_itself_has_nothing_below_it_to_name(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home" / "sal"
    (home / ".git").mkdir(parents=True)
    assert checkout(home, home=home) == ""


def test_a_deep_checkout_under_home_is_still_capped(tmp_path: Path) -> None:
    """The anchor removes the account; the cap keeps the rest from being a site map."""
    home = tmp_path / "home" / "sal"
    root = home / "clients" / "acme" / "work" / "billing"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "work/billing"


@pytest.mark.parametrize(
    "layout",
    [
        # Every one of these was reported by an outside reviewer against the version
        # that only anchored on home. None of them is under home, and all five put the
        # account name in the second-to-last segment — so all five published it.
        "Volumes/Work/{user}/agent-inbox",
        "srv/checkouts/{user}/agent-inbox",
        "home/shared/{user}/agent-inbox",
        "drive-d/{user}/agent-inbox",
        "work/{user}/agent-inbox",
    ],
)
def test_no_layout_outside_home_discloses_the_account_either(
    tmp_path: Path, layout: str
) -> None:
    user = "wilhelmina"
    home = tmp_path / "elsewhere" / user
    home.mkdir(parents=True)
    root = tmp_path / layout.format(user=user)
    (root / ".git").mkdir(parents=True)
    disclosed = checkout(root, home=home)
    assert user not in disclosed, f"{layout} published the account name"
    # The paired positive: the redaction must leave the checkout named, not erase it.
    assert disclosed == "agent-inbox"


def test_the_deepest_mention_of_the_account_is_the_one_that_counts(
    tmp_path: Path,
) -> None:
    user = "wilhelmina"
    home = tmp_path / "elsewhere" / user
    home.mkdir(parents=True)
    root = tmp_path / user / "backups" / user / "billing"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "billing"


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        # Round two from the same outside reviewer: whole-segment matching left the
        # account name sitting inside a longer directory name, which is how people
        # actually name checkouts and scratch directories.
        ("workspace/{user}-agent-inbox", ""),
        ("{user}_projects/billing", "billing"),
        ("srv/{user}-work/agent-inbox", "agent-inbox"),
    ],
)
def test_the_account_name_inside_a_longer_segment_is_redacted_too(
    tmp_path: Path, layout: str, expected: str
) -> None:
    user = "wilhelmina"
    home = tmp_path / "elsewhere" / user
    home.mkdir(parents=True)
    root = tmp_path / layout.format(user=user)
    (root / ".git").mkdir(parents=True)
    disclosed = checkout(root, home=home)
    assert user not in disclosed
    # Pinned exactly, not just "does not contain": redacting the segment must take what
    # is *above* it and leave what is below, and "" is the honest answer when the
    # offending segment was the deepest one.
    assert disclosed == expected


def test_a_very_short_account_name_matches_only_whole_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a two-letter login redacts most of the English language.

    A login of `jo` would find itself inside `projects`, `major`, `job-runner` — and
    the result would be blank far more often than it was ever a disclosure.
    """
    monkeypatch.setattr("agent_inbox.machine.getpass.getuser", lambda: "jo")
    home = tmp_path / "var" / "jo"
    home.mkdir(parents=True)
    root = tmp_path / "srv" / "projects" / "billing"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "projects/billing"


def test_the_short_name_exception_is_real_and_is_the_documented_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hole we chose, pinned so nobody has to rediscover it.

    An outside reviewer found this on the third pass. It is left open deliberately —
    closing it means substring-matching two characters, which blanks most paths — but
    `checkout` must not be allowed to drift into claiming otherwise. If this test ever
    starts failing because the redaction got stricter, that is good news: delete it and
    delete the exception from the docstring in the same commit.
    """
    monkeypatch.setattr("agent_inbox.machine.getpass.getuser", lambda: "jo")
    home = tmp_path / "home" / "jo"
    root = home / "jo-agent-inbox"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "jo-agent-inbox"


def test_the_account_match_ignores_case(tmp_path: Path) -> None:
    """macOS and Windows both hand back paths whose case is not the one on disk."""
    home = tmp_path / "elsewhere" / "wilhelmina"
    home.mkdir(parents=True)
    root = tmp_path / "srv" / "WilhelMina" / "billing"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "billing"


def test_the_login_name_redacts_even_when_home_is_named_differently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two sources of the account name are not the same source.

    A home directory at `/var/lib/svc-home` and a login of `buildbot` is an ordinary
    service-account arrangement, and only `getpass` knows the second. Without this the
    whole account-redaction rule would rest on a home directory whose name happens to
    match — which on this very machine it does, quietly making the other tests here
    pass for the wrong reason until they were pinned to a fictitious name.
    """
    monkeypatch.setattr("agent_inbox.machine.getpass.getuser", lambda: "buildbot")
    home = tmp_path / "var" / "lib" / "svc-home"
    home.mkdir(parents=True)
    root = tmp_path / "srv" / "buildbot" / "billing"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "billing"


def test_a_root_outside_home_falls_back_to_the_cap(tmp_path: Path) -> None:
    home = tmp_path / "home" / "sal"
    home.mkdir(parents=True)
    root = tmp_path / "srv" / "checkouts" / "billing"
    (root / ".git").mkdir(parents=True)
    assert checkout(root, home=home) == "checkouts/billing"


def test_checkout_of_a_shallow_root_says_what_it_can(tmp_path: Path) -> None:
    root = tmp_path / "solo"
    (root / ".git").mkdir(parents=True)
    assert checkout(root).endswith("solo")


def test_facts_carry_only_the_two_keys_promised(repo: Path) -> None:
    facts = machine_facts(start=repo, env={})
    assert set(facts) <= FACT_KEYS
    # The paired positive: without this the disclosure assertions above would pass on
    # an implementation that had simply stopped producing anything at all.
    assert facts["root"] == "workspace/billing"


def test_a_blank_fact_is_omitted_rather_than_written_empty(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_inbox.machine.hostname", lambda: "")
    facts = machine_facts(start=repo, env={})
    assert "host" not in facts, "an empty key reads as 'asked and got nothing'"
    assert facts["root"] == "workspace/billing"


@pytest.mark.parametrize("var", OPT_OUT_VARS)
def test_opting_out_suppresses_everything(repo: Path, var: str) -> None:
    assert opted_out({var: "1"}) is True
    assert machine_facts(start=repo, env={var: "1"}) == {}


def test_an_empty_opt_out_variable_does_not_count(repo: Path) -> None:
    assert opted_out({OPT_OUT_VARS[0]: "  "}) is False
    assert machine_facts(start=repo, env={OPT_OUT_VARS[0]: "  "}) != {}


def test_the_agents_own_word_wins(repo: Path) -> None:
    # A live profile on the reference hub reads {"host": "SFadhley Hartree
    # workstation"} — a human description somebody chose. Overwriting that with a
    # hostname would replace a decision with a guess.
    stated = {"host": "SFadhley Hartree workstation"}
    addition = merged_into(stated, machine_facts(start=repo, env={}))
    assert "host" not in addition
    assert addition["root"] == "workspace/billing"


def test_a_blank_existing_value_is_a_gap_not_a_statement(repo: Path) -> None:
    addition = merged_into(
        {"host": "   ", "root": ""}, machine_facts(start=repo, env={})
    )
    assert set(addition) == {"host", "root"}
