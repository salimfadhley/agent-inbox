"""A hub that is starting is not a hub that is gone.

A hub scaled to zero, or restarting mid-deploy, refuses connections for a second or two
and then serves normally. Treating that as "no such hub" makes the first call after any
quiet period fail, for every agent, every time (issue #34).

**The safety argument is the interesting half.** Retrying a connection is safe only when
we know the request never arrived. A refused connection is that; a timeout is not — the
hub may have received it, acted on it, and been slow to answer, and a retried send that
already arrived is a second message. So exactly one failure kind is retried, and the
tests below exist mostly to pin the ones that are not.
"""

import urllib.error
from typing import Any

import pytest

from agent_inbox.client import ClientError, Config, HubClient

HUB = "https://hub.invalid"


class _Body:
    def __init__(self, payload: bytes = b'{"ok": true}') -> None:
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class Opener:
    """Fails a given number of times, then succeeds. Counts what it was asked."""

    def __init__(self, failures: int, reason: BaseException | None = None) -> None:
        self.left = failures
        self.reason = reason or ConnectionRefusedError(61, "Connection refused")
        self.attempts = 0

    def __call__(self, request: Any, timeout: float = 0) -> _Body:
        self.attempts += 1
        if self.left > 0:
            self.left -= 1
            raise urllib.error.URLError(self.reason)
        return _Body()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> HubClient:
    """A client whose clock only moves when it sleeps.

    Not merely a no-op sleep: with one of those the retry loop spins as fast as the CPU
    allows and can exhaust a *ten-thousand* failure budget inside the real six-second
    grace, so a hub that never comes up appears to come up. The first version of these
    tests did exactly that and reported DID NOT RAISE. A fake clock makes the bound mean
    attempts rather than wall time.
    """
    now = [0.0]
    monkeypatch.setattr("agent_inbox.client.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "agent_inbox.client.time.sleep",
        lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    return HubClient(Config(hub=HUB, name="jed_smith"))


def test_it_waits_out_a_hub_that_is_starting(
    client: HubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = Opener(failures=3)
    monkeypatch.setattr("urllib.request.urlopen", opener)

    assert client.hub_info() == {"ok": True}
    assert opener.attempts == 4


def test_a_hub_that_stays_down_still_fails(
    client: HubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The paired positive. Waiting for ever is a worse failure than a fast error.

    A retry that never gives up turns "your hub is misconfigured" into "your agent
    hangs", which is harder to diagnose and costs a turn.
    """
    monkeypatch.setattr("urllib.request.urlopen", Opener(failures=10_000))

    with pytest.raises(ClientError, match="cannot reach the mailbox"):
        client.hub_info()


def test_it_says_something_rather_than_appearing_hung(
    client: HubClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", Opener(failures=2))

    client.hub_info()

    said = capsys.readouterr().err
    assert "waiting" in said
    assert said.count("waiting") == 1, "a line per attempt is noise in a transcript"


@pytest.mark.parametrize(
    "reason",
    [
        TimeoutError("timed out"),
        ConnectionResetError(54, "Connection reset by peer"),
        OSError(8, "nodename nor servname provided"),
    ],
    ids=["timeout", "reset", "dns"],
)
def test_only_a_refused_connection_is_retried(
    client: HubClient, monkeypatch: pytest.MonkeyPatch, reason: BaseException
) -> None:
    """**The safety rule, and the reason this is narrow.**

    A timeout or a reset may mean the hub received the request and acted on it.
    Replaying a send in that state produces a second message — worse than the error it
    would be hiding. A DNS failure is a misconfiguration; retrying only delays the
    answer.
    """
    opener = Opener(failures=10_000, reason=reason)
    monkeypatch.setattr("urllib.request.urlopen", opener)

    with pytest.raises(ClientError):
        client.hub_info()

    assert opener.attempts == 1, f"{reason!r} was retried; it must not be"


def test_a_working_hub_is_not_slowed(
    client: HubClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The common case: one attempt, nothing said."""
    opener = Opener(failures=0)
    monkeypatch.setattr("urllib.request.urlopen", opener)

    client.hub_info()

    assert opener.attempts == 1
    assert capsys.readouterr().err == ""
