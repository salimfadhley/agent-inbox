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
        hub_name: str = "",
    ) -> None:
        self._store = store
        self._key = secret_key
        self._ttl = session_ttl
        self._clock = clock
        #: Shown in the authenticator entry, so one phone can hold several hubs.
        self._hub_name = hub_name

    def _now(self) -> str:
        return self._clock().isoformat()

    # -- bootstrap ---------------------------------------------------------

    async def bootstrap(self) -> str | None:
        """Make sure someone can get in, and say how. Returns a password if it set one.

        Jenkins-style: a random password, only ever stored hashed, printed to the log
        for the operator to use once.

        **It keeps printing — a fresh password each boot — until that account has
        actually been set up.** Printing only at the instant of seeding was a trap:
        the password lives in one container's log, and a container is a thing that gets
        replaced. On a hub deployed in July the admin account was seeded, the log was
        rotated away with the container, and the only credential to a hub nobody could
        log into was gone. Nothing could recover it; the hash is one-way by design.

        So while the account is still `MUST_CHANGE_AND_ENROL` it has no powers worth
        stealing — it can reach the enrolment endpoints and nothing else — and a
        rotating password in the log is worth far more than a lost one. The moment a
        real operator finishes enrolling, the account becomes ACTIVE and this goes
        quiet for good.
        """
        existing = await self._store.get_user("admin")
        if existing is None and await self._store.any_users():
            # Someone renamed or replaced the seed account. Not ours to second-guess.
            return None

        password = secrets.generate_token()
        if existing is None:
            await self._store.add_user(
                User(
                    username="admin",
                    password_hash=secrets.hash_password(password),
                    enrolment_state=EnrolmentState.MUST_CHANGE_AND_ENROL,
                    created=self._now(),
                )
            )
            logger.warning("no users found — created bootstrap admin")
        elif existing.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL:
            await self._store.put_user(
                User(
                    username=existing.username,
                    password_hash=secrets.hash_password(password),
                    enrolment_state=existing.enrolment_state,
                    totp_secret_enc=existing.totp_secret_enc,
                    created=existing.created,
                    last_login=existing.last_login,
                )
            )
            logger.warning(
                "the admin account has never been set up — issuing a new password"
            )
        else:
            return None  # set up properly; never print again

        logger.warning("initial admin password: %s (change it now)", password)
        return password

    async def reset_user(self, username: str = "admin") -> str:
        """Put an account back to first-run: new password, no authenticator.

        The escape hatch for the operator locked out of their own hub — a wrong
        password, a lost phone, an authenticator enrolled against a secret nobody
        kept. Without it the only route back is deleting rows from the database by
        hand, which is how this was recovered the first time and is not a procedure
        anyone should be asked to follow.

        It grants nothing that possession of the server does not already grant: this
        runs on the box, against the hub's own storage, and whoever can run it can
        read the database anyway. The password is returned for the caller to print,
        and the account must set a real one and enrol again before it can act.
        """
        user = await self._require(username)
        password = secrets.generate_token()
        await self._store.put_user(
            User(
                username=user.username,
                password_hash=secrets.hash_password(password),
                enrolment_state=EnrolmentState.MUST_CHANGE_AND_ENROL,
                totp_secret_enc=None,  # the old authenticator stops working, by design
                created=user.created,
                last_login=user.last_login,
            )
        )
        logger.warning(
            "reset %r to first-run state; 2FA must be enrolled again", username
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

        **The log says which factor failed; the caller is never told.** Those are
        different audiences: telling the browser would hand an attacker a password
        oracle, while telling the operator nothing leaves them staring at "incorrect
        username or password" with no way to know whether to retype their password or
        their phone. Whoever reads the log already controls the deployment.
        """
        user = await self._store.get_user(username)
        if user is None:
            secrets.verify_password(_DUMMY_HASH, password)  # equalise timing
            logger.warning("login failed for %r: no such user", username)
            raise BadCredentials("incorrect username or password")
        if not secrets.verify_password(user.password_hash, password):
            logger.warning("login failed for %r: wrong password", username)
            raise BadCredentials("incorrect username or password")

        if user.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL:
            session = await self._new_session(username, limited=True)
            return LoginResult(session=session, enrolment_required=True)

        if not await self._second_factor_ok(user, otp):
            logger.warning(
                "login failed for %r: password correct, second factor %s",
                username,
                "not supplied" if not otp else "did not match",
            )
            raise BadCredentials("incorrect username or password")
        logger.info("login succeeded for %r", username)

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

    async def open_full_session(self, username: str) -> Session:
        """A fresh full session — used right after first-run enrolment completes."""
        return await self._new_session(username, limited=False)

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
        uri = totp.provisioning_uri(secret, username, self._hub_name)
        return EnrolmentOffer(
            provisioning_uri=uri,
            qr_svg=totp.qr_svg(uri),
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
