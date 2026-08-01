"""Accepting one message from one configured peer.

Everything here happens **before** delivery, and the ordering is the requirement: a
message that is refused must provably never reach a mailbox, so the checks run first
and delivery is the last thing that happens.

Nothing here trusts what arrived. A peer is a machine we have decided to accept mail
from; it is not a machine we believe. Its `Create` is bounded before it is parsed, its
activity type is checked against a list of one, and its content is data — never
instruction — which is charter directive 7's second bullet arriving over HTTP.
"""

from dataclasses import dataclass
from typing import Any

from agent_inbox.exceptions import MailboxError

#: Bounded before parsing. A `Note` is prose; anything larger is not one, and a peer
#: must not be able to cost us memory by claiming otherwise.
MAX_ACTIVITY_BYTES = 128 * 1024

#: The only activity this hub accepts. Not a denylist of the rest: a denylist is a guess
#: about what exists, and ActivityPub carries a great deal we want no part of.
ACCEPTED_ACTIVITY = "Create"
ACCEPTED_OBJECT = "Note"


class InboundRefused(MailboxError):
    """A remote delivery was refused.

    **One exception for every reason**, and the reason is in the message rather than in
    the type. A caller that could branch on *why* would be a caller that could tell a
    stranger which of "no such actor", "not a peer" and "bad signature" was true — and
    the first two are exactly what must stay unsaid.
    """

    code = "inbound_refused"


@dataclass(frozen=True, slots=True)
class RemoteMessage:
    """A `Create`/`Note` from a peer, after checking and before delivery."""

    activity_id: str
    sender: str
    recipients: tuple[str, ...]
    body: str
    subject: str | None
    in_reply_to: str | None


def _string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def parse_activity(raw: bytes) -> dict[str, Any]:
    """Read an activity, bounded, refusing anything that is not one.

    Size is checked **before** parsing: a hostile peer must not be able to make us
    deserialise something enormous in order to discover it was too big.
    """
    if len(raw) > MAX_ACTIVITY_BYTES:
        raise InboundRefused("that delivery is larger than this hub accepts")
    import json

    try:
        document = json.loads(raw)
    except ValueError as bad:
        raise InboundRefused("that delivery is not JSON") from bad
    if not isinstance(document, dict):
        raise InboundRefused("that delivery is not an activity")
    return document


def read_create(document: dict[str, Any], sender: str) -> RemoteMessage:
    """Turn a checked `Create` into something deliverable, or refuse it.

    The activity type is checked against a list of one. `Follow`, `Like`, `Announce`,
    `Update` and `Undo` are refused because engagement mechanics do not arrive merely
    because the protocol carries them; **`Delete` is refused for a stronger reason** —
    a peer cannot reach into our store, in either direction. Our retention is ours.
    """
    kind = document.get("type")
    if kind != ACCEPTED_ACTIVITY:
        raise InboundRefused(
            f"this hub accepts {ACCEPTED_ACTIVITY!r} and nothing else, not {kind!r}"
        )

    activity_id = _string(document.get("id"), 2000)
    if activity_id is None:
        raise InboundRefused("that activity has no id, so it cannot be de-duplicated")

    obj = document.get("object")
    if not isinstance(obj, dict) or obj.get("type") != ACCEPTED_OBJECT:
        raise InboundRefused(
            f"this hub accepts a {ACCEPTED_OBJECT!r} inside a {ACCEPTED_ACTIVITY!r}"
        )

    to = obj.get("to")
    recipients = tuple(
        clean
        for item in (to if isinstance(to, list) else [to])
        if (clean := _string(item, 500)) is not None
    )
    if not recipients:
        raise InboundRefused("that delivery names nobody")

    return RemoteMessage(
        activity_id=activity_id,
        sender=sender,
        recipients=recipients,
        body=_string(obj.get("content"), MAX_ACTIVITY_BYTES) or "",
        subject=_string(obj.get("summary"), 500),
        in_reply_to=_string(obj.get("inReplyTo"), 2000),
    )
