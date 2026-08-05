"""One namespace: an operator account and a mailbox are the same identity.

**This reverses an earlier decision** (owner, 2026-08-05). `admin` used to be two
unrelated things that shared a name — a standing resident actor, reserved so no agent
could claim it, and separately a row in ``auth_users`` that somebody signed in with.
Nothing connected them. Signing in as `admin` now gives you the `admin` mailbox, and
that access is what the admin role means.

It resolves an oddity rather than creating one. The `admin` drop box exists so anyone
can *"raise a concern about how this mailbox operates"*, and those concerns should
reach the human who operates it.

**Why this module exists rather than a column on `User`.** Uniqueness has exactly one
enforcement point — :meth:`Store.claim_name`, atomic, the store's own docstring saying
that a check-then-insert in a caller "would reintroduce the race it exists to close".
A human whose name were claimed anywhere else would be a second answer to *is this name
taken*, and two answers that nearly agree is how a human and an agent come to share an
inbox. So a human's name is claimed through the same call an agent's is, and this module
is the one place that knows a human needs both halves.

That also keeps `AuthService` about authentication. It holds an :class:`AuthStore` and
knows nothing about mailboxes, which is right; the coordination belongs here.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_inbox.auth.exceptions import OperatorExists
from agent_inbox.auth.records import ADMIN_GROUP, User
from agent_inbox.auth.service import AuthService
from agent_inbox.exceptions import NameUnavailable
from agent_inbox.naming import normalize, validate_operator_name
from agent_inbox.records import ActorRecord, ActorType
from agent_inbox.store import MessageStore

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class Renamed:
    """One operator whose username was not a name a mailbox could hold."""

    was: str
    now: str


@dataclass(frozen=True, slots=True)
class Collision:
    """Two operators whose usernames normalise to one name. Neither is migrated.

    Not a case to resolve cleverly: merging them **joins two people's mail**, which is
    not recoverable by reading the code afterwards. Both accounts are left exactly as
    they were and a human is told.
    """

    was: str
    would_be: str
    taken_by: str


@dataclass(frozen=True, slots=True)
class Migration:
    """What the merge did, in enough detail to act on.

    Every field is reported together rather than logged and forgotten, because the cost
    of the chosen migration option is that **somebody's login changes and they find out
    when it stops working**. This is what pays that cost down.
    """

    already: tuple[str, ...] = ()
    #: Actors that existed and are now marked `Person`. `admin` on every upgraded hub:
    #: the standing residents are installed at startup *before* this runs, so claiming
    #: fails and promoting is the difference between "an operator has a mailbox" and
    #: "an operator has *that* mailbox".
    promoted: tuple[str, ...] = ()
    renamed: tuple[Renamed, ...] = ()
    collisions: tuple[Collision, ...] = ()
    claimed: tuple[str, ...] = ()

    @property
    def needs_a_human(self) -> bool:
        """Whether anything here somebody has to act on."""
        return bool(self.collisions)

    def lines(self) -> list[str]:
        """The report, one line each, worst first."""
        out = [
            f"operator {c.was!r} was NOT migrated: it would become {c.would_be!r}, "
            f"which {c.taken_by!r} already holds. Rename one of them by hand — "
            f"migrating would have merged two people's mail."
            for c in self.collisions
        ]
        out.extend(
            f"operator {r.was!r} is now {r.now!r} — that is the username to sign in "
            f"with from now on."
            for r in self.renamed
        )
        return out


async def create_human(
    auth: AuthService,
    store: MessageStore,
    username: str,
    email: str = "",
    group: str = ADMIN_GROUP,
    now: Callable[[], str] = _utcnow,
) -> str:
    """Make a human: one name, held as both an account and a mailbox.

    Returns the one-time password, to be shown once.

    **The account is created first, then the name claimed**, and the claim is what
    decides — :meth:`MessageStore.claim_name`, the same atomic call an agent's join
    uses. If it fails the account is removed again, because a human who can sign in and
    has no mailbox is the half-created state in which everything downstream misbehaves
    in a way that looks like its own bug.

    The other order reads better and is not available: there is no way to release a
    claimed name, so a failure after claiming would block that username for ever. Adding
    a release for one caller would be more surface than the ordering is worth.
    """
    name = validate_operator_name(username)
    if await store.get_actor(name) is not None:
        # A courtesy, not the authority. `claim_name` below is still the only thing that
        # decides — this just spares the common case creating an account and deleting it
        # again. Deliberately the same wording whether an agent or a human holds the
        # name: one namespace means one answer, and saying *which* would disclose the
        # roster to somebody not yet on this hub.
        raise OperatorExists(f"{name!r} is already taken here")

    password = await auth.add_operator(name, email, group)
    stamp = now()
    if not await store.claim_name(
        ActorRecord(
            name=name, actor_type=ActorType.PERSON, created=stamp, last_seen=stamp
        )
    ):
        # Lost the race. Undo the account rather than leave a human who can sign in and
        # has no mailbox — that half-created state is the one in which everything
        # downstream misbehaves in a way that looks like its own bug.
        await auth.remove_operator(name)
        raise OperatorExists(f"{name!r} is already taken here")
    return password


async def adopt_existing(
    auth: AuthService,
    store: MessageStore,
    now: Callable[[], str] = _utcnow,
) -> Migration:
    """Give every existing operator a mailbox, renaming where the name is not usable.

    Idempotent: run at every startup, and after the first it reports only `already`.

    **The rename is the decision** (owner, 2026-08-05, from four options). An existing
    `sal.fadhley` becomes `sal_fadhley`, and that is the login from then on. Chosen over
    refusing to start — an upgrade that takes the hub down over a punctuation mark — and
    over leaving them mailboxless until they rename, which creates two classes of human
    indefinitely with an invisible incentive to fix it.

    Case needs no migration: usernames were already stored folded.
    """
    already: list[str] = []
    promoted: list[str] = []
    renamed: list[Renamed] = []
    collisions: list[Collision] = []
    claimed: list[str] = []

    for user in await auth.operators():
        wanted = _usable(user.username)
        if wanted is None:
            collisions.append(
                Collision(
                    was=user.username,
                    would_be="",
                    taken_by="",
                )
            )
            continue
        if wanted != user.username:
            holder = await store.get_actor(wanted)
            other = await auth._store.get_user(wanted)  # noqa: SLF001 - see below
            # Reaching into the store rather than adding a service method: this is the
            # one caller, it is a read, and the alternative is widening AuthService's
            # surface for a question only the migration asks.
            if holder is not None or other is not None:
                collisions.append(
                    Collision(
                        was=user.username,
                        would_be=wanted,
                        taken_by=(other.username if other else wanted),
                    )
                )
                continue
            await _rename(auth, user, wanted)
            renamed.append(Renamed(was=user.username, now=wanted))
            logger.warning(
                "event=namespace.operator.renamed was=%s now=%s "
                "reason=username-was-not-a-usable-actor-name",
                user.username,
                wanted,
            )

        stamp = now()
        if await store.claim_name(
            ActorRecord(
                name=wanted,
                actor_type=ActorType.PERSON,
                created=stamp,
                last_seen=stamp,
            )
        ):
            claimed.append(wanted)
        else:
            already.append(wanted)
            if await _promote(store, wanted):
                promoted.append(wanted)

    report = Migration(
        already=tuple(already),
        promoted=tuple(promoted),
        renamed=tuple(renamed),
        collisions=tuple(collisions),
        claimed=tuple(claimed),
    )
    for line in report.lines():
        logger.warning("event=namespace.migration %s", line)
    return report


async def _promote(store: MessageStore, name: str) -> bool:
    """Mark an actor a human, keeping everything else about it. ``True`` if changed.

    `admin` needs this on every hub that already exists: the standing residents are
    installed at startup *before* the merge runs, so the actor is there and already
    holds the drop box's purpose text and its mail.

    Only the type changes. Overwriting the profile would discard the sentence explaining
    what the drop box is for — which is text every agent reads in its own prompt.
    """
    actor = await store.get_actor(name)
    if actor is None or actor.actor_type is ActorType.PERSON:
        return False
    await store.put_actor(
        ActorRecord(
            name=actor.name,
            actor_type=ActorType.PERSON,
            profile=actor.profile,
            created=actor.created,
            last_seen=actor.last_seen,
        )
    )
    logger.info("event=namespace.actor.promoted name=%s type=Person", name)
    return True


def _usable(username: str) -> str | None:
    """The actor name this username should become, or ``None`` if there is not one."""
    try:
        return validate_operator_name(username)
    except NameUnavailable:
        pass
    candidate = normalize(username)
    if not candidate:
        return None
    try:
        return validate_operator_name(candidate)
    except NameUnavailable:
        return None


async def _rename(auth: AuthService, user: User, to: str) -> None:
    """Move an operator to a new username, keeping everything else about them."""
    await auth._store.add_user(  # noqa: SLF001 - one caller, and see adopt_existing
        User(
            username=to,
            password_hash=user.password_hash,
            enrolment_state=user.enrolment_state,
            totp_secret_enc=user.totp_secret_enc,
            created=user.created,
            last_login=user.last_login,
            group=user.group,
            email=user.email,
        )
    )
    await auth._store.remove_user(user.username)  # noqa: SLF001


__all__ = [
    "Collision",
    "Migration",
    "Renamed",
    "adopt_existing",
    "create_human",
]
