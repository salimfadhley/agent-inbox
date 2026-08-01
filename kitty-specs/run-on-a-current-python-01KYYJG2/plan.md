# Implementation Plan: Run on a current Python

**Branch**: `kitty/mission-current-python` | **Date**: 2026-08-01
**Spec**: `kitty-specs/run-on-a-current-python-01KYYJG2/spec.md`
**Supersedes**: issue #13 ("migrate to Python 3.13")

## Summary

Move the floor from 3.12 to 3.14, remove the `from __future__ import annotations` line
PEP 649 makes redundant, and update every place that states a version.

**Phase 0 was run before this plan was written, and it changed what the plan says.** The
migration was rehearsed end to end on 3.14.2 in a scratch environment. The headline: the
risky part of this mission — dependencies — is not risky at all, and the part nobody
listed is where the only real finding is.

## Technical Context

**Language/Version**: Python 3.14.2 (from 3.12.1; floor moves `>=3.12` → `>=3.14`)
**Primary Dependencies**: unchanged — aiosqlite, click, argon2-cffi, cryptography, litestar,
msgspec, pyotp, segno, uvicorn, plus the `clients` and `ui` extras
**Storage**: unaffected — SQLite via aiosqlite
**Testing**: the existing pytest suite, unchanged (NFR-001)
**Target Platform**: Linux container (`python:3.14-slim`) and local developer machines
**Project Type**: single package, `src/agent_inbox`
**Performance Goals**: none — this is a floor move, not an optimisation
**Constraints**: no pinned exception may be introduced (FR-006); the four gates must pass
inside the container, not only on a laptop (FR-003)
**Scale/Scope**: 92 Python files, `pyproject.toml`, `Dockerfile`, `ci.yml`, three docs, the
charter

## Charter Check

**Resolved 2026-08-01, before implementation and outside this mission** (`main`, commit
`6393e2b`).

The charter previously stated the stack as "Python 3.12+ only", which FR-001 contradicted
directly. It now says the floor is **3.14+** and that **the ambition is to run the latest
Python** — falling behind is a defect to fix, not a state to maintain — together with the
matching rule for libraries: do not knowingly adopt or hold an old version.

**The amendment was deliberately not made inside this mission.** A mission that resolves a
charter conflict by editing the charter is a mission where the charter stopped governing
anything. So there is no charter subtask; the mission now implements a policy that already
exists.

Three things had to be corrected to make the amendment stick, and they are worth knowing
because the second one is a trap for anyone amending the charter again:

- `interview/answers.yaml` still described the **pre-rebuild system** — a NATS JetStream
  mailbox called `agent-mail`, published to GHCR. `charter.md` had been hand-refreshed three
  times since; that file never was.
- The charter's own Amendment Process said *"edit answers.yaml, regenerate, commit"* — which
  would have **rebuilt the charter from a description of a system deleted in July**. It now
  says what is actually done: `charter.md` is the source, edit it, run `charter sync`, and do
  not regenerate.
- The library list named **pydantic and pydantic-settings**, which this project does not
  depend on and never imports, and Directive 1 told implementers to configure through a
  pydantic-settings object that does not exist. Config is a frozen dataclass over the
  `AGENT_INBOX_*` prefix (`hub_settings`). litestar, msgspec, argon2-cffi, cryptography,
  pyotp and segno were all missing from the list.

Otherwise:

- **Directive 6 (repay debt completely)** — FR-004 is the whole reason this directive is
  quoted in the spec. Ninety files carry a line; leaving ten of them is worse than leaving
  all ninety, because then the convention is unreadable.
- **Directive 1 (risk boundaries)** — low. No behaviour changes; the suite is the proof.
- **Directive 4 (outside model review before close)** — applies as always.

## Phase 0 — research, already carried out

Run 2026-08-01 against a scratch environment at Python 3.14.2, built with
`uv sync --python 3.14 --dev --all-extras` into a throwaway `UV_PROJECT_ENVIRONMENT` so the
project's own `.venv` was never touched.

### FR-006 is already satisfied, and this was the mission's biggest assumed risk

The spec named dependency wheels as the thing most likely to bite: "litestar, msgspec,
aiosqlite, cryptography, argon2-cffi, mcp/FastMCP, pyotp. Native builds are where this
bites."

**They do not bite.** The full dev + `clients` + `ui` set resolved and installed on 3.14.2
with **no pinned exception and no source build failure**. `cryptography`, `msgspec`,
`argon2-cffi` and `pydantic-core` (transitive, via mcp) — the four with native code — all had
wheels.

This removes the main reason the mission was scheduled as "unhurried". It is smaller than
it looked.

### Three of the four gates already pass on 3.14

| Gate | Result on 3.14.2 |
|---|---|
| `ruff check` | All checks passed |
| `ruff format --check` | 93 files already formatted |
| `pyright` | 0 errors, 0 warnings — **but see below** |
| `pytest` | 961 passed, 18 skipped — **with one intermittent failure, see below** |

**The pyright result is not yet the real answer.** `pyproject.toml` sets
`pythonVersion = "3.12"`, so pyright analysed 3.12 semantics while running on a 3.14
interpreter. The genuine test is a clean run *after* that setting moves to 3.14, and the
spec is right to expect churn. Treat the current zero as unproven, not as reassurance.

### The one real finding: an intermittent failure that only appears on 3.14

`tests/test_operators.py::TestRemoval::test_any_operator_can_be_removed` fails
**intermittently** on 3.14 — twice in four full-suite runs — and never on 3.12.

```
self = <contextlib._GeneratorContextManager object at 0x...>, typ = None
    def __exit__(self, typ, value, traceback):
        if typ is None:
            try:
>               next(self.gen)
E               UnicodeDecodeError: 'utf-8' codec can't decode byte 0x94 in position 0
  .../python3.14/contextlib.py:148: UnicodeDecodeError
```

What is known:

- It passes **every time in isolation** (`pytest tests/test_operators.py`), so it is an
  interaction with the rest of the suite, not with the test.
- It is in **capture teardown**, not in the assertion — the test's own body has already
  succeeded.
- `0x94` at position 0 is a continuation byte with no lead byte: the signature of a
  **buffer split mid-character**, not of genuinely non-UTF-8 data.

What is not known, and must be established before this mission closes: whether it is a
pytest-capture bug on 3.14, an interaction with our logging configuration, or a latent
defect in our own code that 3.12 happened to hide.

**Do not silence it.** The spec's rule for pyright — "treat any new complaint as a real
finding rather than noise to silence" — applies with more force here, because an
intermittent failure that is marked flaky and skipped is how a real defect gets a permanent
home. If it turns out to be an upstream bug, the outcome is a link to the upstream issue
and a narrowly-scoped test-side workaround, not a blanket skip on a green suite.

### PEP 765: nothing to do

Zero occurrences of `return`, `break` or `continue` in a `finally` block across `src` and
`tests`. The spec listed this as a risk; it is closed.

### Nothing else is pinned to 3.12

Every statement of the version, exhaustively:

| File | What |
|---|---|
| `pyproject.toml:12` | `requires-python = ">=3.12"` |
| `pyproject.toml:33-34` | two `Programming Language :: Python ::` classifiers |
| `pyproject.toml:111` | `target-version = "py312"` (ruff) |
| `pyproject.toml:127` | `pythonVersion = "3.12"` (pyright) |
| `Dockerfile:16,37` | `FROM python:3.12-slim` — build **and** runtime stage |
| `.github/workflows/ci.yml:35` | `uv sync --python 3.12` |
| `.github/workflows/ci.yml:53` | `python-version: ["3.12", "3.13"]` matrix |
| `README.md:9,54,55` | badge and two prose statements |
| `CONTRIBUTING.md:13` | "Python 3.12+ and nothing else" |
| `.kittify/charter/charter.md:50` | "Python 3.12+ only" — the charter conflict above |
| `.kittify/metadata.yaml:16` | `python_version: 3.12.1` |

Open question 3 from the spec — *"Is anything actually pinned to 3.12?"* — is answered:
**no.** Every occurrence is a declaration, not a constraint. There is no code branching on
version and no dependency capping it.

## Phase 1 — design

### The CI matrix should collapse to one version

`ci.yml:53` runs a `["3.12", "3.13"]` matrix. FR-002 says "CI runs the four gates on 3.14"
— singular — and the spec's own argument is that this is an application which "owes nobody
multi-version support".

**A two-version matrix on an application tests a configuration nobody ships.** It costs
double the minutes and, worse, it invites the next reader to conclude the floor is really
3.12. The matrix becomes `3.14` alone.

This is a consequence of the spec rather than a new decision, but it is worth stating,
because "update the version in CI" and "delete the matrix" are different edits and only one
of them is right.

### `from __future__ import annotations` — all or none, and not a no-op

90 of 92 files carry it. Under PEP 649 the behaviour it requests is the default in 3.14.

**Correction to an earlier draft of this plan, which called the removal "mechanical".** It is
not. `from __future__ import annotations` is **PEP 563** — it stringifies annotations. PEP 649
gives back real objects, lazily. Removing the import changes what `__annotations__` yields at
runtime, and this project hands annotated types to **litestar, msgspec, click and mcp**, all
of which introspect them. Usually that is an improvement; occasionally it is a behaviour
change, most often around forward references and `TYPE_CHECKING`-only imports.

**Phase 0 does not cover this.** The 961/18 baseline below was measured with the imports still
in place. It proves the interpreter move and says nothing about the removal, which is why
WP02 carries a separate proof (T006).

The removal is mechanical and must be complete in a single change. FR-004 is explicit and
the reason bears repeating: a codebase where some modules opt in and others rely on the
default cannot be read, because the reader cannot tell which files were considered and
which were missed.

**Verify by count, not by eye**: after the change,
`grep -rl 'from __future__ import annotations' src tests` returns nothing. That is a
one-line proof and it is not optional.

### `copy.replace()` and `typing.TypeIs` stay out

The spec already rules these separable, and this plan holds that line. NFR-001 says no
behaviour change; adopting new idioms in the same change makes the suite's verdict
ambiguous — a failure could be the interpreter or the rewrite, and telling them apart costs
more than doing them separately.

They deserve their own mission. They do not deserve to make this one hard to review.

## Work, in order

0. **Amend the charter** — *done, outside this mission*. See Charter Check.
1. **The floor.** `pyproject.toml`: `requires-python`, classifiers, ruff `target-version`,
   pyright `pythonVersion`. Then run the four gates and deal with whatever pyright says at
   3.14 semantics — this is the step with real, unpredictable work in it.
2. **`from __future__ import annotations`, all 90 files**, with the grep proof.
3. **CI and the image.** Collapse the matrix to 3.14; both `Dockerfile` stages; prove the
   gates inside the container (FR-003).
4. **The words.** README, CONTRIBUTING, `.kittify/metadata.yaml`, and any doc stating a
   version.
5. **The intermittent failure.** Characterise it, then fix or upstream it. Not first —
   nothing else waits on it — but this mission does not close with it unexplained.
6. **The Directive 4 review**, with one narrow question. The obvious one is the annotation
   question above, which is this mission's only genuine unknown.

## What could still go wrong

| Risk | Mitigation |
|---|---|
| pyright at 3.14 semantics produces real churn | It is step 2, deliberately early, so the surprise lands before anything else is built on it |
| The gates pass locally but not in the container | FR-003 is a separate proof and is not satisfied by a laptop run |
| The intermittent failure is ours, not pytest's | Step 6 is scoped to answer that, and the answer may enlarge this mission — better than shipping it unexplained |
| The 90-file edit is done partially | The grep proof is a hard gate, not a review note |

## Proved by removal, not by passing

- **FR-004** — "no file imports future annotations" passes if `src` is empty. Pair it with
  a test-count assertion so the proof cannot be satisfied by deleting the codebase.
- **FR-006** — "everything installs" passes if nothing is installed. The lock must contain
  the same dependency set it does today.
- **NFR-001** — "the suite passes" passes if the suite is skipped. **961 passed / 18
  skipped** is the number to beat, and it is recorded here for that purpose.
