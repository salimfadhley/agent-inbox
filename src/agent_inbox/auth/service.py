"""The auth service — orchestration over the store, like Mailbox for messaging.

No HTTP here and no framework: the service holds an :class:`AuthStore`, the
secret key (for encrypting TOTP secrets), a session lifetime, and a clock. It
exposes exactly the verbs the edge and the console call — bootstrap, login,
enrol, device tokens, caller resolution — and makes the security decisions the
store deliberately does not.

The clock is injected (like the mailbox's) so every time-dependent path —
session expiry, the TOTP window — is deterministic in tests.
"""

import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_inbox.auth import secrets, totp
from agent_inbox.auth.exceptions import (
    BadCredentials,
    EnrolmentRequired,
    LastOperator,
    OperatorExists,
    TokenRevoked,
    UnknownOperator,
)
from agent_inbox.auth.records import (
    ADMIN_GROUP,
    GROUPS,
    SHARED_ACTOR,
    DeviceToken,
    EnrolmentState,
    Session,
    TokenUse,
    User,
)
from agent_inbox.auth.store import AuthStore

logger = logging.getLogger("agent_inbox.auth")

#: **A contract, not a log message.** An unattended setup — CI standing up an enforcing
#: hub, or an operator scripting a deployment — has no other way to learn the password
#: of a hub it has just created, so it reads this prefix out of the container log.
#:
#: Changing it breaks those callers, and breaks them *badly*: the symptom is a failure
#: to authenticate somewhere later, which sends whoever is debugging to the wrong place
#: entirely. `tests/test_auth_bootstrap.py` asserts it, so the break happens here and
#: says what it is.
#:
#: `AGENT_MAILBOX_INITIAL_ADMIN_PASSWORD` is the alternative for callers that would
#: rather supply a password than scrape one.
INITIAL_PASSWORD_LOG_PREFIX = "initial admin password: "

#: A throwaway hash to verify against when the user does not exist, so a wrong username
#: costs the same time as a wrong password — no user-enumeration by timing (FR-017).
_DUMMY_HASH = secrets.hash_password("this password matches nobody")

#: The single operator account this hub seeds and the only one the override applies to.
ADMIN_USERNAME = "admin"

#: Shown wherever the low-security mode is surfaced — descriptor, console, startup log.
#: One sentence, one wording, so it is recognisable in a log and in a browser alike.
INSECURE_ADMIN_WARNING = "Explicitly setting an admin password is insecure"

#: Length of a generated session / token id.
_ID_BYTES = 16

#: How much of an ISO timestamp makes a bucket. 16 characters is `YYYY-MM-DDTHH:MM` —
#: one minute. Fine enough that "last used" reads as live while an operator is setting a
#: machine up, which is when they actually watch the screen, and coarse enough that a
#: busy agent collapses to one write a minute.
_BUCKET_PRECISION = 16


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
    """A freshly minted token. ``secret`` is shown once and never stored raw.

    It carries no actor. A token admits a *machine*; who is using it is settled per
    request from the caller's own name, and a field here saying otherwise would be the
    old model surviving in the one place an operator looks.
    """

    id: str
    secret: str


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
        admin_password: str = "",
    ) -> None:
        self._store = store
        self._key = secret_key
        self._ttl = session_ttl
        self._clock = clock
        #: Shown in the authenticator entry, so one phone can hold several hubs.
        self._hub_name = hub_name
        #: **A deliberate hole in the front door.** See :meth:`login`. Empty means off,
        #: which is the only safe value and the default.
        self._admin_password = admin_password.strip()
        #: (token, actor, minute) triples already recorded. The bucket that keeps the
        #: hot path cheap — see :meth:`admit`. Per process and deliberately not
        #: persisted: losing it costs one redundant write.
        self._admitted: set[tuple[str, str, str]] = set()

    @property
    def admin_password_set(self) -> bool:
        """Whether the low-security admin override is active.

        Public because it must be *visible*: the hub reports it in its own descriptor
        and the console shows a banner. A hole in the front door that nobody can see
        from outside is the worst version of this feature.
        """
        return bool(self._admin_password)

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

        # CONTRACT: this exact prefix is depended upon. `tests/test_auth_bootstrap.py`
        # asserts it, because an unattended setup reads the password back out of the
        # container log and has nothing else to go on. Reword it and that breaks — so
        # change the test deliberately, rather than discovering it as a confusing
        # authentication failure somewhere unrelated.
        logger.warning("%s%s (change it now)", INITIAL_PASSWORD_LOG_PREFIX, password)
        return password

    async def pending_setup(self) -> str | None:
        """The account still waiting to be set up, or ``None`` if none is.

        Drives the console's first-run instructions, which have to disappear once
        somebody has actually enrolled: an operator six months in should not still be
        told where to find a password they replaced long ago, and — worse — being told
        so suggests the hub is less set up than it is.
        """
        user = await self._store.get_user("admin")
        if user is None or user.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL:
            return "admin"
        return None

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

    # -- operators ---------------------------------------------------------
    #
    # **Every operator is an admin.** There is no role column and no hierarchy: the
    # owner's rule is that all humans here are equal, and a second class of human would
    # be a role by another name.
    #
    # The one asymmetry is arithmetic rather than status — the last account cannot be
    # removed, so nobody can empty the list and leave a hub with no way in. That is a
    # convenience guard, not the safety net: whoever owns the hosting can always set
    # `AGENT_INBOX_ADMIN_PASSWORD` and get back in. It exists because a co-operator may
    # have console access without hosting access, and for them the mistake would be
    # unrecoverable.

    async def operators(self) -> tuple[User, ...]:
        """Every human who can sign in. All equal; none is the owner of the others."""
        return await self._store.users()

    async def add_operator(
        self, username: str, email: str = "", group: str = ADMIN_GROUP
    ) -> str:
        """Invite a human. Returns their one-time password, to be shown once.

        `group` is recorded and **enforced nowhere** — an account marked `user` can do
        everything an `admin` can. It exists so the shape is in place before the checks
        are, and every surface that shows it has to say so.

        The new account starts where the seeded one does — MUST_CHANGE_AND_ENROL — so an
        invitation confers nothing until its holder sets a real password and enrols a
        second factor. The password is returned rather than mailed because this hub
        cannot send mail; whoever invites them has to pass it on out of band.
        """
        name = username.strip().lower()
        if not name:
            raise ValueError("an operator needs a username")
        if await self._store.get_user(name) is not None:
            raise OperatorExists(f"{name!r} is already an operator here")
        password = secrets.generate_token()
        await self._store.add_user(
            User(
                username=name,
                password_hash=secrets.hash_password(password),
                enrolment_state=EnrolmentState.MUST_CHANGE_AND_ENROL,
                created=self._now(),
                email=email.strip(),
                group=group if group in GROUPS else ADMIN_GROUP,
            )
        )
        logger.warning("added operator %r — every operator is an admin here", name)
        return password

    async def remove_operator(self, username: str) -> None:
        """Remove a human, unless they are the last one.

        Their sessions go with them, so removal takes effect immediately rather than
        whenever they next happen to sign in.
        """
        name = username.strip().lower()
        remaining = [u for u in await self._store.users() if u.username != name]
        if not remaining:
            raise LastOperator(
                f"{name!r} is the only operator — removing them would leave this hub "
                "with no way in. Add another operator first."
            )
        if not await self._store.remove_user(name):
            raise UnknownOperator(f"{name!r} is not an operator here")
        logger.warning("removed operator %r", name)

    # -- login -------------------------------------------------------------

    async def login(
        self, username: str, password: str, otp: str | None = None
    ) -> LoginResult:
        """Verify a password and, if enrolled, a second factor. Returns a session.

        **Except in low-security mode.** When ``AGENT_MAILBOX_ADMIN_PASSWORD`` is set,
        that value logs `admin` straight in — no second factor, no enrolment, whatever
        state the stored account is in. That is the point of it: it is the way back into
        a hub whose password is forgotten or whose authenticator is gone, and the way a
        test drives a hub without a phone.

        It is insecure and is meant to be. Anyone who can read the environment — or a
        compose file, or a shell history, or a process listing — is an administrator of
        this hub, and no second factor stands in their way. It is never a default, the
        hub says so in its own descriptor, and the console shows a banner while it is
        set. Do not leave it on.

        A wrong username and a wrong password are indistinguishable and take the
        same time (FR-017). An account still in first-run state gets a *limited*
        session that may only reach the enrolment endpoints.

        **The log says which factor failed; the caller is never told.** Those are
        different audiences: telling the browser would hand an attacker a password
        oracle, while telling the operator nothing leaves them staring at "incorrect
        username or password" with no way to know whether to retype their password or
        their phone. Whoever reads the log already controls the deployment.
        """
        if self._admin_password and username == ADMIN_USERNAME:
            # THE OVERRIDE. Deliberately low-security, and deliberately first: it must
            # work when the stored account is unusable, because recovering from exactly
            # that is what it is for — a forgotten password, a lost authenticator, a
            # hub being driven by a test.
            #
            # `compare_digest` because there is no reason to leak the password through
            # timing even in a mode that has already given up on secrecy.
            if hmac.compare_digest(password, self._admin_password):
                logger.warning(
                    "admin signed in with AGENT_MAILBOX_ADMIN_PASSWORD — no second "
                    "factor was required. This hub is in low-security mode."
                )
                session = await self._new_session(username, limited=False)
                return LoginResult(session=session, enrolment_required=False)
            # Fall through: a wrong override attempt may still be a right stored one.

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

    async def mint_token(self, label: str = "") -> MintedToken:
        """Create a token that admits a machine. The secret is returned once.

        No actor. Every token is shared: it says the holder is allowed in, and the
        holder says which agent they are, exactly as they always did.
        """
        secret = secrets.generate_token()
        token = DeviceToken(
            id=secrets.generate_token()[:_ID_BYTES],
            actor=SHARED_ACTOR,
            token_hash=secrets.hash_token(secret),
            label=label,
            created=self._now(),
        )
        await self._store.add_token(token)
        return MintedToken(id=token.id, secret=secret)

    async def list_tokens(self) -> tuple[DeviceToken, ...]:
        """Every token on the hub. Not per agent — a token belongs to no agent."""
        return await self._store.all_tokens()

    async def token_uses(self, token_id: str) -> tuple[TokenUse, ...]:
        """Which agents this token has admitted, most recently seen first."""
        return await self._store.uses_for(token_id)

    async def revoke_token(self, token_id: str) -> bool:
        return await self._store.revoke_token(token_id)

    async def resolve_token(self, secret: str) -> DeviceToken | None:
        """Is this credential good? ``None`` if unknown, raise if revoked.

        **It does not answer "who is this"**, because a secret cannot: a token admits a
        machine and several agents share it. The caller knows the claimed name from the
        request and is the only place both facts are in hand, so the caller combines
        them — see :meth:`admit`.

        No write happens here. Recording belongs with the name, one layer up.
        """
        token = await self._store.get_token_by_hash(secrets.hash_token(secret))
        if token is None:
            return None
        if token.revoked:
            # First, before anything else, and it must stay first: a revoked credential
            # that gets as far as being recorded has been honoured for one more request
            # than it should have been.
            raise TokenRevoked("this token has been revoked")
        return token

    async def admit(self, token: DeviceToken, actor: str) -> None:
        """Note that this token let this agent in — at most once per bucket.

        Coarse on purpose (FR-009). Authentication is the most-called path here and it
        **already** wrote on every call: `resolve_token` used to touch `last_used` per
        request. Collapsing that to one write per token per minute makes the hot path
        cheaper than it was while adding the record that makes revoking informed.

        The bucket is checked *before* the write, not wrapped around one that already
        happened. In-memory and per process: a restart writes once more than it needed
        to, which costs nothing and needs no persistence.
        """
        if not actor:
            return  # nothing to record against; an unnamed caller is not an agent
        now = self._now()
        bucket = (token.id, actor, now[:_BUCKET_PRECISION])
        if bucket in self._admitted:
            return
        # Bounded by tokens x agents, and cleared whenever the minute moves on, so it
        # cannot grow with traffic. A dict that only ever grows is the failure this
        # whole mission is trying not to repeat elsewhere.
        self._admitted = {b for b in self._admitted if b[2] == bucket[2]}
        self._admitted.add(bucket)
        await self._store.record_use(token.id, actor, now)
        await self._store.touch_token(token.id, now)

    # -- helpers -----------------------------------------------------------

    async def _require(self, username: str) -> User:
        user = await self._store.get_user(username)
        if user is None:
            raise BadCredentials("no such user")
        return user
