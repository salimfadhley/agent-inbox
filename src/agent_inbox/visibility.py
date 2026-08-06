"""How findable an actor is, decided by the actor.

Three levels, and the middle one is the reason there are three:

``local``
    Reachable only from this hub. Not addressable across federation, not listed.

``normal``
    **Addressable but unlisted.** Somebody who knows the name can reach it; the
    directory does not advertise it. This is the default, and it is what an actor that
    has never heard of this setting already gets.

``discoverable``
    Addressable and listed. An actor asking to be found.

A two-level design collapses *findable* and *reachable* into one decision nobody
actually wants to make together — "you may write to me if you know who I am, but do not
put me in a list" is an ordinary and reasonable position, and it is the default here.

**The actor owns this, and that is not ADR 0008 trouble.** That ADR governs *mail*
carrying authority: nothing arriving in a mailbox may change the mailbox. An agent
choosing its own reachability is not administering the hub and is not acting on
somebody else's say-so — it is the same class of act as choosing its own profile, which
it already does. Lemmy lets a person control their own discoverability, and C-003 makes
that the tie-breaker where we have no stronger reason.
"""

import logging
from collections.abc import Mapping
from enum import StrEnum

from agent_inbox.exceptions import MailboxError

logger = logging.getLogger(__name__)

#: The profile key this lives under. In the profile because that is where the mutable
#: half of identity already lives (ADR 0003) — a second home for actor facts is a second
#: thing to keep in step.
KEY = "visibility"


class Visibility(StrEnum):
    """How findable an actor is. Ordered least to most exposed."""

    LOCAL = "local"
    NORMAL = "normal"
    DISCOVERABLE = "discoverable"


#: What an actor gets without asking, and what every actor that predates this has.
DEFAULT = Visibility.NORMAL

#: What an unreadable stored value is treated as. **The safest level, never the
#: default** — a value we cannot understand must not resolve to something more exposed
#: than the actor may have chosen.
FALLBACK = Visibility.LOCAL


class BadVisibility(MailboxError):
    """A visibility that is not one of the three."""

    code = "bad_visibility"


def parse(value: object) -> Visibility:
    """Validate a *written* visibility, or refuse it by name.

    **Refused rather than coerced.** Silently falling back to the default on an
    unrecognised value would quietly weaken a privacy setting the actor believed it had
    set — and it would do so at the moment the actor was paying most attention.
    """
    if isinstance(value, Visibility):
        return value
    text = str(value or "").strip().lower()
    try:
        return Visibility(text)
    except ValueError as unknown:
        raise BadVisibility(
            f"{text!r} is not a visibility — use one of "
            f"{', '.join(v.value for v in Visibility)}"
        ) from unknown


def read(profile: object) -> Visibility:
    """What a *stored* profile says, never raising.

    FR-015, and the asymmetry with :func:`parse` is the whole point. Reading is not
    writing: a value that should not be in the store is a fact about the store, and
    refusing to start over it would take the hub down to protect one actor's listing.

    So a bad value reads as :data:`FALLBACK` — the safest level — and is logged. It
    fails towards *less* exposure, which is the only direction a privacy default may
    fail in.
    """
    # `Mapping`, not `dict`: `ActorRecord.profile` is frozen into a `MappingProxyType`
    # on construction (ADR 0003 — identity's mutable half is still not mutable in
    # place), so a `dict` check reads every stored profile as absent and hands back the
    # default. Found by the round-trip test, which is exactly what it is for.
    if not isinstance(profile, Mapping) or KEY not in profile:
        return DEFAULT
    raw = profile[KEY]
    try:
        return parse(raw)
    except BadVisibility:
        logger.warning(
            "event=visibility.unreadable value=%r treated_as=%s", raw, FALLBACK.value
        )
        return FALLBACK


__all__ = ["DEFAULT", "FALLBACK", "KEY", "BadVisibility", "Visibility", "parse", "read"]
