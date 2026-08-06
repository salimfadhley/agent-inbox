"""The federation audit: what was administered, and what was refused.

**The automated refusals matter as much as the deliberate acts**, and that is the whole
reason this module exists rather than a few scattered log lines. An operator asking *why
did that peer not get my mail* is asking about something nobody typed. An audit that
records only human actions cannot answer them, and they will conclude the software is
broken — which, for their purposes, it is.

So both are recorded through one function, in one shape: who (where there is a who),
what, to whom, and why.

**It never carries a secret.** No key, no token, no message content. That is asserted as
an *absence over the whole serialised entry* rather than field by field, because a
field-by-field check passes an entry that has since gained one — and this is a record
that will grow fields.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("agent_inbox.federation.audit")

#: Keys whose *values* are never recorded, whatever a caller passes. Belt and braces
#: beside the tests: a caller assembling detail from a request body should not be able
#: to put a token in the log by naming it something plausible.
NEVER: frozenset[str] = frozenset(
    {
        "key",
        "signing_key",
        "private_key",
        "publickey",
        "token",
        "secret",
        "password",
        "content",
        "body",
        "summary",
        # Ambiguous on purpose: `message` is as likely to be somebody's prose as an
        # identifier, and a caller who means the id can say `message_id`. Guessing
        # generously here would be guessing in the direction of disclosure.
        "message",
    }
)

#: What the value is replaced with, rather than dropping the key. Dropping it would make
#: the entry look as though nothing was passed, and "nothing was passed" and "something
#: was passed and withheld" are different facts about the same request.
REDACTED = "[withheld]"


@dataclass(frozen=True, slots=True)
class Entry:
    """One thing that happened, deliberate or automatic."""

    at: str
    action: str
    target: str
    #: The human who did it, or ``""`` when nothing did — an automated refusal has no
    #: actor, and inventing one would be worse than the gap.
    by: str = ""
    reason: str = ""
    detail: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "at": self.at,
            "action": self.action,
            "target": self.target,
            "by": self.by,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


def _safe(detail: Mapping[str, object] | None) -> dict[str, str]:
    """What a caller passed, with anything sensitive replaced rather than dropped."""
    if not detail:
        return {}
    return {
        str(key): (REDACTED if str(key).lower() in NEVER else str(value))
        for key, value in detail.items()
    }


def record(
    action: str,
    target: str,
    *,
    by: str = "",
    reason: str = "",
    detail: Mapping[str, object] | None = None,
    now: str = "",
) -> Entry:
    """Write one entry and return it.

    Append-only by construction: this emits a log line and holds no state, so there is
    nothing to rewrite. A store-backed audit would need a deletion policy, and a
    deletion policy on an audit is the first step towards an audit that can be edited.
    """
    entry = Entry(
        at=now or datetime.now(UTC).isoformat(),
        action=action,
        target=target,
        by=by,
        reason=reason,
        detail=_safe(detail),
    )
    logger.warning("event=federation.audit %s", json.dumps(entry.as_dict()))
    return entry


__all__ = ["NEVER", "REDACTED", "Entry", "record"]
