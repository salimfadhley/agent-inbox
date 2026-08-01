"""Brute-force protection for the login endpoint.

A password is the one low-entropy factor in the system, so the login endpoint is
the one place worth throttling. This is a **per-source sliding-window** limiter:
too many failed attempts from one source within a window, and further attempts
are refused for a lockout period — turning an online brute-force from millions of
guesses an hour into a handful.

Two deliberate choices:

- **Keyed by source (IP), not by username.** Locking a *username* would let an
  attacker lock the real admin out (a denial of service), and a username-specific
  lockout response is a user-enumeration oracle. Keying by source throttles the
  guesser without punishing the victim and without revealing who exists.
- **A success clears the source's failures.** The window is there to stop
  guessing, not to punish someone who eventually typed their password correctly.

State is in-memory and per-process — the right scope for rate-limiting. A restart
resets the counters, which is not a security hole (it only forgives a window
early) and keeps the hub a single SQLite file with nothing else to persist. The
clock is injected so the windows are testable.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LoginThrottle:
    """A per-source failed-login limiter with a lockout after too many failures."""

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window: timedelta = timedelta(minutes=15),
        lockout: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._max = max_failures
        self._window = window
        self._lockout = lockout
        self._clock = clock
        #: source -> recent failure timestamps (pruned to the window on each touch)
        self._failures: dict[str, list[datetime]] = {}
        #: source -> time a lockout ends
        self._locked_until: dict[str, datetime] = {}

    def _prune(self, key: str, now: datetime) -> None:
        cutoff = now - self._window
        recent = [t for t in self._failures.get(key, ()) if t >= cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)

    def allowed(self, key: str) -> bool:
        """Whether a login attempt from ``key`` may proceed right now."""
        now = self._clock()
        until = self._locked_until.get(key)
        if until is not None:
            if now < until:
                return False
            # lockout elapsed — clear it and the failures that caused it
            self._locked_until.pop(key, None)
            self._failures.pop(key, None)
        return True

    def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again — for the ``Retry-After`` header."""
        until = self._locked_until.get(key)
        if until is None:
            return 0
        return max(0, int((until - self._clock()).total_seconds()) + 1)

    def record_failure(self, key: str) -> None:
        """Note a failed attempt; trip a lockout once the window fills with failures."""
        now = self._clock()
        self._prune(key, now)
        self._failures.setdefault(key, []).append(now)
        if len(self._failures[key]) >= self._max:
            self._locked_until[key] = now + self._lockout

    def record_success(self, key: str) -> None:
        """A correct login forgives the source — clear its failures and any lockout."""
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)
