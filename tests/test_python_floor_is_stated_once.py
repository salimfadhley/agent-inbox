"""Every place that names the Python floor has to name the same one.

The floor is stated in six files that nothing connects: `pyproject.toml` says it four
times, `.python-version` picks the interpreter `uv` actually uses, the `Dockerfile`
picks the one the published image runs, and CI picks the one the gates run against.
They can disagree, and when they do **nothing fails** — every gate passes, because each
tool reads only its own line.

That failure has a specific shape and it is not hypothetical: raise `requires-python`
to 3.14 and leave the image on `python:3.12-slim`, and the build succeeds, the tests
pass, the release publishes, and the container refuses to install the package it was
built to run. The charter states the rule this pins ("the floor moves as one change:
`requires-python`, the classifiers, ruff's `target-version`, pyright's `pythonVersion`,
both `Dockerfile` stages and CI, or none of them"), and a rule stated in prose is a rule
until somebody is in a hurry.

`.python-version` is here for a second reason: it was missed when the floor moved, by a
search that filtered on file extension. It has none.
"""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: `major.minor`, which is the only precision every one of these files shares — the
#: image tag has no patch component and neither does ruff's `py314`.
FLOOR = "3.14"


def _pyproject() -> dict[str, object]:
    return tomllib.loads((REPO / "pyproject.toml").read_text())


def test_requires_python_states_the_floor() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    assert project["requires-python"] == f">={FLOOR}"


def test_the_classifiers_claim_the_floor_and_nothing_older() -> None:
    """A trove classifier is a claim installers act on, not decoration."""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    classifiers = project["classifiers"]
    assert isinstance(classifiers, list)
    versioned = [
        c.rsplit("::", 1)[-1].strip()
        for c in classifiers
        if isinstance(c, str) and c.startswith("Programming Language :: Python :: ")
    ]
    # "3" is the bare major-version classifier and is always fine; anything else must
    # be the floor, so a stale "3.12" left behind is a failure rather than a footnote.
    assert set(versioned) - {"3"} == {FLOOR}


def test_the_linter_and_the_type_checker_target_the_floor() -> None:
    """These two decide what the *tools* believe — how a floor moves in name only.

    Leave `pythonVersion` behind and pyright cheerfully type-checks the previous
    language against the new interpreter — green, and checking the wrong thing.
    """
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    ruff, pyright = tool["ruff"], tool["pyright"]
    assert isinstance(ruff, dict) and isinstance(pyright, dict)
    assert ruff["target-version"] == "py" + FLOOR.replace(".", "")
    assert pyright["pythonVersion"] == FLOOR


def test_the_interpreter_uv_picks_is_the_floor() -> None:
    """`.python-version` is what `uv sync` reads first, and it has no file extension."""
    assert (REPO / ".python-version").read_text().strip() == FLOOR


def test_both_dockerfile_stages_run_the_floor() -> None:
    """Two `FROM` lines. Changing one gives an image that builds and cannot run."""
    bases = re.findall(
        r"^FROM python:(\S+?)-slim", (REPO / "Dockerfile").read_text(), re.MULTILINE
    )
    assert bases, "no `FROM python:<version>-slim` stages found — has the base changed?"
    assert len(bases) == 2, f"expected a build and a runtime stage, found {len(bases)}"
    assert set(bases) == {FLOOR}


def test_ci_runs_the_gates_on_the_floor_and_only_the_floor() -> None:
    """One version, because this is an application and a matrix would test a fiction.

    Read as text rather than parsed YAML: what matters is that no *other* version is
    named anywhere in the file, including in a matrix this test does not know about.
    """
    ci = (REPO / ".github/workflows/ci.yml").read_text()
    mentioned = set(re.findall(r"\b3\.\d{1,2}\b", ci))
    assert mentioned <= {FLOOR}, f"CI also names {sorted(mentioned - {FLOOR})}"
    assert f"--python {FLOOR}" in ci
