"""The auth service — orchestration over the store, like Mailbox for messaging.

No HTTP here and no framework: the service holds an :class:`AuthStore`, the
secret key (for encrypting TOTP secrets), a session lifetime, and a clock. It
exposes exactly the verbs the edge and the console call — bootstrap, login,
enrol, device tokens, caller resolution — and makes the security decisions the
store deliberately does not.

The clock is injected (like the mailbox's) so every time-dependent path —
session expiry, the TOTP window — is deterministic in tests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_mailbox.auth import secrets, totp
from agent_mailbox.auth.exceptions import (
    BadCredentials,
    EnrolmentRequired,
    TokenRevoked,
)
from agent_mailbox.auth.records import DeviceToken, EnrolmentState, Session, User
from agent_mailbox.auth.store import AuthStore

logger = logging.getLogger("agent_mailbox.auth")

#: A throwaway hash to verify against when the user does not exist, so a wrong username
#: costs the same time as a wrong password — no user-enumeration by timing (FR-017).
_DUMMY_HASH = secrets.hash_password("this password matches nobody")

#: Length of a generated session / token id.
_ID_BYTES = 16


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """The outcome of a successful password (+ maybe second-factor) check."""

    session: Session
    #: True when the caller must complete first-run enrolment before acting.
    enrolment_required: bool


@dataclass(frozen=True, slots=True)
class EnrolmentOffer:
    """What to show a human enrolling 2FA — the QR to scan and codes to keep. Once."""

    provisioning_uri: str
    qr_svg: str
    recovery_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MintedToken:
    """A freshly minted device token. ``secret`` is shown once and never stored raw."""

    id: str
    secret: str
    actor: str


class AuthService:
    """Everything the edge needs to prove who is calling, over an :class:`AuthStore`."""

    def __init__(
        self,
        store: AuthStore,
        *,
        secret_key: str,
        session_ttl: timedelta = timedelta(hours=12),
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._key = secret_key
        self._ttl = session_ttl
        self._clock = clock

    def _now(self) -> str:
        return self._clock().isoformat()

    # -- bootstrap ---------------------------------------------------------

    async def bootstrap(self) -> str | None:
        """Seed the first admin if there are none. Returns the password if seeded.

        Jenkins-style: a random password is generated, returned to the caller to
        log once, and only its hash is stored. The account must change its
        password and enrol 2FA before it can do anything else.
        """
        if await self._store.any_users():
            return None
        password = secrets.generate_token()
        await self._store.add_user(
            User(
                username="admin",
                password_hash=secrets.hash_password(password),
                enrolment_state=EnrolmentState.MUST_CHANGE_AND_ENROL,
                created=self._now(),
            )
        )
        logger.warning("no users found — created bootstrap admin")
        logger.warning(
            "initial admin password: %s (shown once; change it now)", password
        )
        return password

    # -- login -------------------------------------------------------------

    async def login(
        self, username: str, password: str, otp: str | None = None
    ) -> LoginResult:
        """Verify a password and, if enrolled, a second factor. Returns a session.

        A wrong username and a wrong password are indistinguishable and take the
        same time (FR-017). An account still in first-run state gets a *limited*
        session that may only reach the enrolment endpoints.
        """
        user = await self._store.get_user(username)
        if user is None:
            secrets.verify_password(_DUMMY_HASH, password)  # equalise timing
            raise BadCredentials("incorrect username or password")
        if not secrets.verify_password(user.password_hash, password):
            raise BadCredentials("incorrect username or password")

        if user.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL:
            session = await self._new_session(username, limited=True)
            return LoginResult(session=session, enrolment_required=True)

        if not await self._second_factor_ok(user, otp):
            raise BadCredentials("incorrect username or password")

        await self._store.put_user(
            User(
                username=user.username,
                password_hash=user.password_hash,
                enrolment_state=user.enrolment_state,
                totp_secret_enc=user.totp_secret_enc,
                created=user.created,
                last_login=self._now(),
            )
        )
        session = await self._new_session(username, limited=False)
        return LoginResult(session=session, enrolment_required=False)

    async def _second_factor_ok(self, user: User, otp: str | None) -> bool:
        if not otp:
            return False
        if user.totp_secret_enc is not None:
            secret = secrets.decrypt_secret(user.totp_secret_enc, self._key)
            if totp.verify(secret, otp):
                return True
        # fall back to a single-use recovery code
        return await self._store.spend_recovery_code(
            user.username, secrets.hash_token(otp)
        )

    async def _new_session(self, username: str, *, limited: bool) -> Session:
        now = self._clock()
        session = Session(
            id=secrets.generate_token(),
            username=username,
            created=now.isoformat(),
            expires=(now + self._ttl).isoformat(),
            limited=limited,
        )
        await self._store.add_session(session)
        return session

    async def resolve_session(self, session_id: str) -> Session | None:
        """The session for an id, or ``None`` if unknown or expired (then swept)."""
        session = await self._store.get_session(session_id)
        if session is None:
            return None
        if session.expires and session.expires < self._now():
            await self._store.delete_session(session_id)
            return None
        return session

    async def logout(self, session_id: str) -> None:
        await self._store.delete_session(session_id)

    # -- enrolment & account ----------------------------------------------

    async def begin_enrolment(self, username: str) -> EnrolmentOffer:
        """Issue a fresh TOTP secret (stored, pending) + recovery codes, shown once."""
        user = await self._require(username)
        secret = totp.new_secret()
        codes = totp.new_recovery_codes()
        await self._store.put_user(
            User(
                username=user.username,
                password_hash=user.password_hash,
                enrolment_state=user.enrolment_state,
                totp_secret_enc=secrets.encrypt_secret(secret, self._key),
                created=user.created,
                last_login=user.last_login,
            )
        )
        await self._store.add_recovery_codes(
            username, [secrets.hash_token(c) for c in codes]
        )
        return EnrolmentOffer(
            provisioning_uri=totp.provisioning_uri(secret, username),
            qr_svg=totp.qr_svg(totp.provisioning_uri(secret, username)),
            recovery_codes=codes,
        )

    async def complete_enrolment(
        self, username: str, new_password: str, otp: str
    ) -> None:
        """Finish first-run: set a password, confirm the authenticator, activate."""
        user = await self._require(username)
        if user.totp_secret_enc is None:
            raise EnrolmentRequired("start enrolment before completing it")
        secret = secrets.decrypt_secret(user.totp_secret_enc, self._key)
        if not totp.verify(secret, otp):
            raise BadCredentials("that code did not match the authenticator")
        await self._store.put_user(
            User(
                username=user.username,
                password_hash=secrets.hash_password(new_password),
                enrolment_state=EnrolmentState.ACTIVE,
                totp_secret_enc=user.totp_secret_enc,
                created=user.created,
                last_login=self._now(),
            )
        )

    async def confirm_2fa(self, username: str, otp: str) -> None:
        """Confirm a rotated authenticator for an already-active user."""
        user = await self._require(username)
        if user.totp_secret_enc is None:
            raise EnrolmentRequired("start enrolment before confirming it")
        secret = secrets.decrypt_secret(user.totp_secret_enc, self._key)
        if not totp.verify(secret, otp):
            raise BadCredentials("that code did not match the authenticator")

    async def change_password(self, username: str, current: str, new: str) -> None:
        user = await self._require(username)
        if not secrets.verify_password(user.password_hash, current):
            raise BadCredentials("current password is incorrect")
        await self._store.put_user(
            User(
                username=user.username,
                password_hash=secrets.hash_password(new),
                enrolment_state=user.enrolment_state,
                totp_secret_enc=user.totp_secret_enc,
                created=user.created,
                last_login=user.last_login,
            )
        )

    # -- device tokens -----------------------------------------------------

    async def mint_token(self, actor: str, label: str = "") -> MintedToken:
        """Create a device token. The secret is returned once, then only hashed."""
        secret = secrets.generate_token()
        token = DeviceToken(
            id=secrets.generate_token()[:_ID_BYTES],
            actor=actor,
            token_hash=secrets.hash_token(secret),
            label=label,
            created=self._now(),
        )
        await self._store.add_token(token)
        return MintedToken(id=token.id, secret=secret, actor=actor)

    async def list_tokens(self, actor: str) -> tuple[DeviceToken, ...]:
        return await self._store.tokens_for(actor)

    async def revoke_token(self, token_id: str) -> bool:
        return await self._store.revoke_token(token_id)

    async def resolve_token(self, secret: str) -> str | None:
        """Resolve a bearer secret to its actor; None if unknown, raise if revoked."""
        token = await self._store.get_token_by_hash(secrets.hash_token(secret))
        if token is None:
            return None
        if token.revoked:
            raise TokenRevoked("this device token has been revoked")
        await self._store.touch_token(token.id, self._now())
        return token.actor

    # -- helpers -----------------------------------------------------------

    async def _require(self, username: str) -> User:
        user = await self._store.get_user(username)
        if user is None:
            raise BadCredentials("no such user")
        return user
