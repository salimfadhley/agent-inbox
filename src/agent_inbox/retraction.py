"""Retraction: one primitive, two scopes, and a body that is genuinely gone.

**The only destructive act in this project.** A retracted message keeps its place in the
conversation — its position, its sender, its time and its ``in_reply_to`` — and loses
its body. Replies beneath it still make sense, and nothing vanishes without a trace.

Who may do it:

- an **agent** may retract a message **it sent**, and only that;
- a **human** may retract **anything on this hub**.

**One function decides both**, because a decision made in two places will eventually
disagree — and a disagreement here is somebody's words destroyed by a caller who should
not have been able to. That is C-006 of the federation work applied to the one act that
cannot be undone.

**This lands exactly on the two acts the fediverse already has**, which is the outcome
the charter asks for rather than a coincidence:

===========  ==========================  ==========  ==========================
Lemmy        here                        who         scope
===========  ==========================  ==========  ==========================
``delete``   an agent retracting its own the author  their own message
``remove``   a human retracting anything the operator anything on this hub
===========  ==========================  ==========  ==========================

What we are building is ``remove``, and Lemmy's local-only behaviour is the behaviour we
want. One departure, recorded rather than silent: we tombstone **immediately** rather
than after thirty days. Lemmy's delay exists to let an author change their mind; a
retraction here is often an operator acting on somebody else's message, and a grace
period would leave a message the operator believes is gone readable for a month.

**It is local.** A copy already delivered to a peer hub is not withdrawn, and nothing
here says it was. That is what federation can honestly deliver; claiming more would be
a promise this cannot keep.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from agent_inbox.exceptions import MailboxError, NoSuchMessage
from agent_inbox.records import ActorType, ObjectRecord
from agent_inbox.store import MessageStore

logger = logging.getLogger(__name__)

#: What a reader sees in place of the body. Reddit's convention, and the one Lemmy
#: converges on too — its thirty-day hard-clear is an *edit* that replaces the content,
#: not a removal of the record.
TOMBSTONE = "[deleted]"

#: Where the fact of retraction lives on the stored document.
#:
#: In the document rather than sniffed from the content, because a message whose body
#: legitimately reads ``[deleted]`` must not be mistaken for a retracted one — and
#: because a reader needs *who* and *when*, which the tombstone cannot carry.
MARK = "retracted"


class NotYoursToRetract(MailboxError):
    """A caller tried to retract a message they do not have the power to.

    Carries which power is missing, because "refused" tells an agent nothing it can act
    on. This is a refusal an agent meets while doing something reasonable — withdrawing
    something it regrets — so it should read like an explanation, not a slap.
    """

    code = "not_yours_to_retract"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def is_retracted(record: ObjectRecord) -> bool:
    """Whether this message's body has been withdrawn."""
    return MARK in record.document


def retracted_by(record: ObjectRecord) -> str:
    """Who withdrew it, or ``""``. Part of the record that survives the body."""
    mark = record.document.get(MARK)
    return str(mark.get("by", "")) if isinstance(mark, dict) else ""


async def retract(
    store: MessageStore,
    object_id: str,
    by: str,
    *,
    now: Callable[[], str] = _utcnow,
) -> ObjectRecord:
    """Withdraw one message's body. The same call whoever makes it.

    Returns the tombstoned record. Raises :class:`NoSuchMessage` if there is nothing
    there, and :class:`NotYoursToRetract` if *by* lacks the power.

    **The permission decision lives here and nowhere else.** A caller passes who is
    acting; it does not pass what they are allowed to do. Every surface — the API, the
    console, a future CLI — reaches this one function, so there is no second answer to
    disagree with the first.

    Retracting an already-retracted message is a no-op rather than an error: the caller
    asked for a state and the state holds, and two operators tidying the same thread
    should not produce a failure neither can act on.
    """
    record = await store.get_object(object_id)
    if record is None:
        # The same error as "not yours to read" — deliberately. Distinguishing them
        # would let an outsider probe what is stored, which the visibility rules exist
        # to prevent.
        raise NoSuchMessage(f"no message {object_id!r}")

    actor = await store.get_actor(by)
    human = actor is not None and actor.actor_type is ActorType.PERSON
    if not human and record.attributed_to != by:
        raise NotYoursToRetract(
            f"{by!r} may retract only its own messages, and this one is "
            f"{record.attributed_to!r}'s. A human operating this hub may retract "
            f"anything on it; an agent may not."
        )

    if is_retracted(record):
        return record

    # **The audit entry is written before the body goes.** Order is the requirement, not
    # a preference: a retraction that fails between the two steps must leave an audited
    # non-retraction, which somebody can see and repeat. The other order leaves a
    # destroyed body nobody can account for — and C-003 exists so an agent cannot send
    # something and then erase that it did.
    logger.warning(
        "event=message.retracted id=%s by=%s author=%s human=%s at=%s",
        record.id,
        by,
        record.attributed_to,
        human,
        now(),
    )

    document = dict(record.document)
    document[MARK] = {"by": by, "at": now()}
    tombstoned = ObjectRecord(
        id=record.id,
        attributed_to=record.attributed_to,
        to=record.to,
        cc=record.cc,
        # Kept, and this is what makes the conversation survive: a reply to a retracted
        # message still knows what it answered, so the thread keeps its shape.
        in_reply_to=record.in_reply_to,
        summary=TOMBSTONE,
        content=TOMBSTONE,
        published=record.published,
        object_type=record.object_type,
        document=document,
    )
    # One write, replacing the row. Not a per-recipient operation: a message delivered
    # to four mailboxes is *one* stored object, so retracting it is retracted for
    # everyone by construction rather than by remembering to loop.
    await store.add_object(tombstoned)
    return tombstoned


__all__ = [
    "MARK",
    "TOMBSTONE",
    "NotYoursToRetract",
    "is_retracted",
    "retract",
    "retracted_by",
]
