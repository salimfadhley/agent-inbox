"""What the auth layer raises.

Separate from :mod:`agent_mailbox.exceptions` on purpose — the auth package
does not import the messaging engine and vice-versa. Same discipline, though:
every error carries a stable ``code`` the edge maps to an HTTP status without
pattern-matching on English.

The deliberate *fusion* here is :class:`BadCredentials`, which covers a wrong
username, a wrong password, and a wrong second factor alike. Distinguishing them
would tell an attacker which half they got right (FR-017).
"""

from __future__ import annotations


class AuthError(Exception):
    """Base for everything the auth layer raises. ``code`` is machine-readable."""

    code = "auth_error"


class BadCredentials(AuthError):
    """A login failed. The same for a wrong user, password, or second factor."""

    code = "bad_credentials"


class NotAuthenticated(AuthError):
    """No valid credential was presented where one is required (enforce mode)."""

    code = "not_authenticated"


class EnrolmentRequired(AuthError):
    """The account exists but must set a real password and enrol 2FA before acting."""

    code = "enrolment_required"


class TokenRevoked(AuthError):
    """A device token was presented that has been revoked."""

    code = "token_revoked"


class TooManyAttempts(AuthError):
    """Too many failed logins from this source; try again later.

    Carries ``retry_after`` seconds so the edge can set a ``Retry-After`` header.
    """

    code = "too_many_attempts"

    def __init__(self, message: str, *, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after
