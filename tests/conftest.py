"""Test settings that must hold for every test, whoever is running them.

There is one rule here and it exists because breaking it cost two red builds in a
single evening: **the suite must not be able to see the engine markers of whatever
agent is running it.**

`agent-inbox` works out which engine it is serving by looking for `CLAUDECODE`,
`CODEX_HOME` and friends in the environment (`client.ENGINE_MARKERS`). That is
deliberate and it is how an agent gets its identity without being told. It also means a
test run *inside* a Claude Code session sees `CLAUDECODE`, resolves an engine, and
takes a different path than the same test in CI, which has no markers at all and a
project configuring two engines — where the CLI correctly refuses to guess.

The result was a test that passed on the author's machine and failed in CI for a reason
having nothing to do with what it was testing. "Remember to unset the variables" is not
a fix; it is a thing to forget. Stripping them here makes the ambient environment
unable to reach a test at all.

A test that *wants* an engine marker sets one with `monkeypatch.setenv`, which runs
after this and works exactly as before.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent_inbox.client import ENGINE_MARKERS


@pytest.fixture(autouse=True)
def _no_ambient_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hide the running agent's engine markers from every test.

    Autouse and unconditional. A fixture that had to be requested would be absent from
    exactly the tests whose author did not know it existed, which is the same failure
    with more steps.
    """
    for marker, _engine in ENGINE_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    yield
