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


@dataclass(frozen=True, slots=True)
class User:
    """A human operator. Every user is an admin (single-owner; no role column)."""

    username: str
    password_hash: str
    enrolment_state: EnrolmentState = EnrolmentState.MUST_CHANGE_AND_ENROL
    #: Fernet ciphertext of the TOTP secret; ``None`` until enrolled.
    totp_secret_enc: bytes | None = None
    created: str = ""
    last_login: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceToken:
    """A bearer credential for one agent actor. Holds only the secret's hash."""

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
