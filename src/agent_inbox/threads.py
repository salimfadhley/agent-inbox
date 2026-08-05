"""Retracting a thread: the same primitive, applied to a set.

There is no thread *object* here — membership is computed per turn — so "delete the
thread" means retracting each message in the set the reader is looking at. This module
is a loop over :func:`agent_inbox.retraction.retract` and deliberately nothing more.

**If this grows its own permission test, its own audit format, or its own idea of what
a retraction is, it has gone wrong.** That is the whole reason it is thin.

The one thing it *does* decide is what to do about a mixed thread, and the answer is
uncomfortable enough to be worth stating: **partial outcomes are normal here, not an
error state.** A human may retract anything, so a thread-wide retraction succeeds for
them entirely. An agent may retract only its own, so the same call over a conversation
retracts its messages and refuses the rest — and reporting that as a single failure
would be a lie in one direction, while reporting it as a single success would be a lie
in the other.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agent_inbox.exceptions import MailboxError
from agent_inbox.retraction import NotYoursToRetract, retract
from agent_inbox.store import MessageStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Refused:
    """One message a caller could not retract, and why."""

    object_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ThreadRetraction:
    """What a thread-wide retraction actually did.

    Both lists are reported because either alone misleads. An operator who is told
    "done" while three messages survived will believe a conversation is gone when it is
    not — and that belief is the harm, more than the messages.
    """

    retracted: tuple[str, ...] = ()
    refused: tuple[Refused, ...] = ()

    @property
    def partial(self) -> bool:
        """Whether some went and some stayed — the case a caller must not gloss."""
        return bool(self.retracted) and bool(self.refused)


async def retract_thread(
    store: MessageStore,
    object_ids: Sequence[str],
    by: str,
    *,
    now: Callable[[], str] | None = None,
) -> ThreadRetraction:
    """Retract every message in *object_ids* that *by* has the power to.

    The permission test runs **per message**, inside `retract`, because that is where
    it lives. Nothing here inspects who anyone is.

    Each retraction is audited separately, which follows from calling `retract` once
    per message rather than from remembering to: one entry saying "a thread" would lose
    which messages were destroyed, and that is the thing an audit is for.
    """
    kwargs = {} if now is None else {"now": now}
    retracted: list[str] = []
    refused: list[Refused] = []
    for object_id in object_ids:
        try:
            await retract(store, object_id, by, **kwargs)  # type: ignore[arg-type]
        except NotYoursToRetract as no:
            refused.append(Refused(object_id=object_id, reason=str(no)))
        except MailboxError as gone:
            # A message that vanished between listing the thread and retracting it is
            # not the caller's mistake, and must not abort the rest — somebody else
            # retracting concurrently is the ordinary way this happens.
            refused.append(Refused(object_id=object_id, reason=str(gone)))
        else:
            retracted.append(object_id)

    done = ThreadRetraction(retracted=tuple(retracted), refused=tuple(refused))
    logger.warning(
        "event=thread.retracted by=%s retracted=%d refused=%d",
        by,
        len(done.retracted),
        len(done.refused),
    )
    return done


__all__ = ["Refused", "ThreadRetraction", "retract_thread"]
