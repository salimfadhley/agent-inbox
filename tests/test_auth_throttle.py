"""The login throttle — unit level, with a controllable clock.

The properties that matter for brute-force protection: failures accumulate to a lockout,
a lockout expires, a success forgives, sources are independent, and the window slides.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_inbox.auth.throttle import LoginThrottle


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t = self.t + timedelta(**kw)


def _throttle(clock: Clock) -> LoginThrottle:
    return LoginThrottle(
        max_failures=3,
        window=timedelta(minutes=10),
        lockout=timedelta(minutes=10),
        clock=clock,
    )


def test_a_source_is_allowed_until_it_hits_the_limit() -> None:
    c = Clock()
    t = _throttle(c)
    assert t.allowed("ip1")
    t.record_failure("ip1")
    t.record_failure("ip1")
    assert t.allowed("ip1")  # two failures, still under the limit of three
    t.record_failure("ip1")
    assert not t.allowed("ip1")  # third trips the lockout


def test_the_lockout_expires() -> None:
    c = Clock()
    t = _throttle(c)
    for _ in range(3):
        t.record_failure("ip1")
    assert not t.allowed("ip1")
    c.advance(minutes=11)  # past the 10-minute lockout
    assert t.allowed("ip1")


def test_retry_after_counts_down() -> None:
    c = Clock()
    t = _throttle(c)
    for _ in range(3):
        t.record_failure("ip1")
    after = t.retry_after("ip1")
    assert 0 < after <= 601  # ~10 minutes, in seconds


def test_a_success_forgives_the_source() -> None:
    c = Clock()
    t = _throttle(c)
    t.record_failure("ip1")
    t.record_failure("ip1")
    t.record_success("ip1")
    # the earlier failures are cleared, so it takes a fresh three to lock again
    t.record_failure("ip1")
    t.record_failure("ip1")
    assert t.allowed("ip1")


def test_sources_are_independent() -> None:
    c = Clock()
    t = _throttle(c)
    for _ in range(3):
        t.record_failure("attacker")
    assert not t.allowed("attacker")
    assert t.allowed("victim")  # a different source is untouched — no DoS on the victim


def test_old_failures_fall_out_of_the_window() -> None:
    c = Clock()
    t = _throttle(c)
    t.record_failure("ip1")
    t.record_failure("ip1")
    c.advance(minutes=11)  # the two failures age past the window
    t.record_failure("ip1")  # a lone recent failure
    assert t.allowed("ip1")  # not locked: only one failure is within the window
