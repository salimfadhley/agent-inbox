"""What the auth store persists — plain frozen data, no behaviour.

These cross the boundary between the auth service and whatever keeps the bytes.
Everything sensitive is already hashed or encrypted by the time it becomes a
record: ``password_hash`` is an Argon2id string, ``totp_secret_enc`` is Fernet
ciphertext, ``token_hash`` is a SHA-256 hex digest. Never a plaintext secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EnrolmentState(StrEnum):
    """Where a user is in first-run onboarding."""

    #: Must set a real password and enrol 2FA before doing anything else (FR-010).
    MUST_CHANGE_AND_ENROL = "must_change_and_enrol"
    #: Fully set up.
    ACTIVE = "active"


#: The groups a human can be in. **Nothing enforces these yet** — see `User.group`.
ADMIN_GROUP = "admin"
USER_GROUP = "user"
GROUPS = (ADMIN_GROUP, USER_GROUP)


@dataclass(frozen=True, slots=True)
class User:
    """A human operator.

    **Today every user is an admin, whatever their group says.** `group` is recorded and
    displayed and governs nothing at all.
    """

    username: str
    password_hash: str
    enrolment_state: EnrolmentState = EnrolmentState.MUST_CHANGE_AND_ENROL
    #: Fernet ciphertext of the TOTP secret; ``None`` until enrolled.
    totp_secret_enc: bytes | None = None
    created: str = ""
    last_login: str | None = None
    #: Which group this human is in — and **a stub that enforces nothing**.
    #:
    #: Recorded now so the shape exists before the checks do: `admin` is intended to
    #: mean "can add and remove operators" and `user` to mean "read-only, plus minting
    #: device tokens". Neither is checked anywhere, so **an account marked `user` has
    #: exactly the same powers as one marked `admin`**.
    #:
    #: That gap is the danger. A field that reads like a permission and is not one
    #: invites somebody to demote a colleague and believe it took effect, so every
    #: surface that shows this must say it is not enforced, and the day the checks land
    #: is the day it stops needing to.
    group: str = ADMIN_GROUP
    #: For password recovery, which does not exist yet. Collected now because
    #: asking an operator for it *after* they are locked out is too late — the
    #: address has to be on file before the day it is needed.
    email: str = ""


#: An ``actor`` of ``*`` means the token names nobody: it admits the *machine*, and
#: whoever presents it says which agent they are in the usual way. Safe as a sentinel
#: because name validation refuses ``*``, so no real actor can ever collide with it.
#:
#: This is the difference between "prove you are rosemary_nasrin" and "prove you are
#: allowed in here" — and both are wanted. A per-agent token binds a credential to one
#: identity; a shared one lets a trusted machine hold a single token for every agent on
#: it, which is what a laptop running four coding agents actually needs.
SHARED_ACTOR = "*"


@dataclass(frozen=True, slots=True)
class DeviceToken:
    """A bearer credential. Holds only the secret's hash.

    ``actor`` is one agent's name, or :data:`SHARED_ACTOR` for a token that admits any
    agent and leaves identity to the caller.
    """

    id: str
    actor: str
    token_hash: str
    label: str = ""
    created: str = ""
    last_used: str | None = None
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class Session:
    """A human's authenticated session after password + second factor."""

    id: str
    username: str
    created: str = ""
    expires: str = ""
    #: A limited session may only reach the enrolment endpoints (first-run flow).
    limited: bool = False
