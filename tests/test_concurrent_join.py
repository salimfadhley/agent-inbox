"""Two engines joining one project at the same moment (issue #49).

`write_config` merges rather than replaces, and the merge is careful: the docstring
explains at length that several agents share a repository and that evicting one would
be invisible until their mail stopped arriving. Then it renames the finished file over
the old one, atomically, so nobody can ever read a half-written config.

**None of that helps against a second writer.** Atomicity is about what a *reader*
sees. The failure here is between two writers: each reads a file without the other's
entry, each merges into what it read, and each renames a complete, well-formed,
perfectly atomic file over the top. The last one wins and the first one is gone — the
exact eviction the merge exists to prevent, arriving through the read instead of the
write. Nothing errors, nothing is corrupt, and the agent that lost simply stops
receiving mail.

**This is asserted with real processes, because the bug is between processes.** Two
threads would exercise the same code and prove almost nothing: the interesting
question is whether two independently-launched agents — a Claude session and a Codex
session started by the same `install-hook`, say — can tread on each other, and only
separate interpreters answer that.

The window is widened deliberately from the outside rather than left to chance. A
race that reproduces "usually" is a removal proof that passes sometimes, which is
worse than no proof at all: it would report the lock as unnecessary on the run that
happened to serialise. The child hooks `_render_project` — the last step, inside the
locked section — and sleeps there. With the lock, the second writer waits and both
identities survive. Without it, both children read an empty file and the second
rename discards the first. Deterministically, every run.
"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

HUB = "https://hub.example"

#: How long each child sits between reading the config and renaming its version over
#: the top. Long enough that a lock-less run cannot serialise by luck; short enough
#: that the suite does not notice.
WIDEN = 0.5

JOINER = '''
"""One agent joining a project, with the read-modify-write window held open."""

import os
import sys
import time
from pathlib import Path

from agent_inbox import client

project, engine, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
joiners, widen = int(sys.argv[4]), float(sys.argv[5])

# Rendezvous, so every child has certainly started before any of them reads. Without
# this the test would be measuring interpreter start-up jitter.
(project / f"ready-{engine}").write_text("")
deadline = time.monotonic() + 30
while len(list(project.glob("ready-*"))) < joiners:
    if time.monotonic() > deadline:
        raise SystemExit("the other joiners never arrived")
    time.sleep(0.01)

# Hold the window open at the last step before the rename. This is inside the locked
# section, so it delays a lock-holder rather than defeating the lock.
rendered = client._render_project


def slowly(target, hub, agents):
    time.sleep(widen)
    return rendered(target, hub, agents)


client._render_project = slowly
client.write_config("HUB_URL", name, engine=engine, start=project)
'''.replace("HUB_URL", HUB)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root, with a `.git` so the upward search stops here.

    Without it, `find_config` and `project_root` would walk out of the temporary
    directory and into whatever is above it — and the lock would be taken somewhere
    other than the file it protects.
    """
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


def join_together(project: Path, who: dict[str, str], home: Path) -> None:
    """Launch one process per engine and wait for all of them to finish."""
    script = project / "joiner.py"
    script.write_text(JOINER)
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(home),
        # Detection must not reach into the environment running the tests and label
        # every child `claude`; each is told which engine it is.
        "CLAUDECODE": "",
    }

    running = [
        subprocess.Popen(
            [
                sys.executable,
                str(script),
                str(project),
                engine,
                name,
                str(len(who)),
                str(WIDEN),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for engine, name in who.items()
    ]
    for child in running:
        _, complained = child.communicate(timeout=120)
        assert child.returncode == 0, f"a joiner failed:\n{complained}"


def identities(project: Path) -> dict[str, str]:
    written = project / "agent-inbox.toml"
    assert written.is_file(), "no config was written at all"
    agents = tomllib.loads(written.read_text()).get("agents") or {}
    return {engine: entry.get("name", "") for engine, entry in agents.items()}


class TestNobodyIsEvictedByAConcurrentJoin:
    def test_two_engines_joining_at_once_both_survive(
        self, project: Path, tmp_path: Path
    ) -> None:
        """**The regression.** Before the lock this left one entry, every time."""
        who = {"claude": "rosemary_nasrin", "codex": "pablo_fantomas"}

        join_together(project, who, tmp_path / "home")

        assert identities(project) == who

    def test_a_third_joining_with_them_survives_too(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Two is the shape in the issue; three is where a lock that merely narrowed
        the window rather than closing it would start showing through."""
        who = {
            "claude": "rosemary_nasrin",
            "codex": "pablo_fantomas",
            "gemini": "igor_laszlo",
        }

        join_together(project, who, tmp_path / "home")

        assert identities(project) == who

    def test_the_hub_survives_the_race_as_well(
        self, project: Path, tmp_path: Path
    ) -> None:
        """The other thing in the file. An engine with the right name and no hub is
        just as unreachable as one that was evicted outright."""
        join_together(
            project,
            {"claude": "rosemary_nasrin", "codex": "pablo_fantomas"},
            tmp_path / "home",
        )

        written = tomllib.loads((project / "agent-inbox.toml").read_text())
        # The hub goes machine-wide when the project does not pin one, so its absence
        # here is correct — what must not happen is a project pinned to something else.
        assert written.get("hub", "") in ("", HUB)

    def test_no_lock_is_left_behind(self, project: Path, tmp_path: Path) -> None:
        """A lock that outlived its writer would be invisible for thirty seconds and
        then reclaimed — survivable, but it would make every subsequent join pause for
        no reason, and the pause would be blamed on the hub."""
        join_together(
            project,
            {"claude": "rosemary_nasrin", "codex": "pablo_fantomas"},
            tmp_path / "home",
        )

        assert not (project / ".agent-inbox.lock").exists()


class TestALoneJoinIsUnchanged:
    """The paired positive. Everything above would also pass if `write_config` had
    simply been made to refuse — these say it still does its job."""

    def test_one_engine_joining_alone_is_written(
        self, project: Path, tmp_path: Path
    ) -> None:
        join_together(project, {"claude": "rosemary_nasrin"}, tmp_path / "home")

        assert identities(project) == {"claude": "rosemary_nasrin"}

    def test_a_later_join_still_merges_into_the_earlier_one(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Sequential joins were never the broken case, and must not become one: a
        lock left held between calls would deadlock the second."""
        home = tmp_path / "home"
        join_together(project, {"claude": "rosemary_nasrin"}, home)
        join_together(project, {"codex": "pablo_fantomas"}, home)

        assert identities(project) == {
            "claude": "rosemary_nasrin",
            "codex": "pablo_fantomas",
        }
