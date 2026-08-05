"""Names: requested by the agent, adjudicated by the hub, or issued when absent.

A name is **opaque**. It carries no meaning the system routes on, which is the whole
point of ADR 0003 — our previous identifier was assembled from project, engine and role,
and every one of those facts eventually changed.

An agent may pick its own; the hub decides whether it gets it. What the hub
guarantees is **uniqueness**, which nothing enforced before — so two agents
sharing a name silently shared an inbox.

Issued names come from a checked-in pool (:mod:`agent_inbox.name_pool`) — no
generator library at runtime, because it is, in the end, two lists of words.
"""

import random
import re
import unicodedata
from dataclasses import dataclass

from agent_inbox.exceptions import NameUnavailable
from agent_inbox.name_pool import FAMILY_NAMES, GIVEN_NAMES

#: Reserved: addressing keywords, not names anyone may hold. ``local`` matters
#: most — it is a guarantee of non-egress, so it must never be something an
#: agent can be called.
#: Words that mean *who to send to* rather than *who somebody is*. An actor called
#: ``everyone`` makes every broadcast ambiguous, so these are refused to everybody —
#: agent and human alike.
ADDRESSING_KEYWORDS: frozenset[str] = frozenset(
    {"local", "all", "any", "public", "me", "everyone"}
)

#: The hub's own mailboxes. Reserved so no *agent* can claim one and quietly start
#: receiving the hub's complaints or its introductions — but these are exactly the
#: names a human operator holds, which is why they are a separate set from the
#: addressing keywords above rather than one undifferentiated list.
STANDING_RESIDENTS: frozenset[str] = frozenset({"admin", "host"})

RESERVED_NAMES: frozenset[str] = ADDRESSING_KEYWORDS | STANDING_RESIDENTS

_VALID = re.compile(r"^[a-z0-9](?:[a-z0-9_]{0,62}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class Name:
    """A validated name.

    Frozen because a name is stable for the life of the actor. Changing facts must not
    change identity — that lesson cost six missions (ADR 0003).
    """

    value: str

    def __str__(self) -> str:
        return self.value


def normalize(raw: str) -> str:
    """Reduce a proposed name to its canonical form: ASCII, lowercase, underscored.

    Latin diacritics are folded, so ``Zoë Müller`` and ``zoe_muller`` cannot become two
    different actors. Anything not reducible to ASCII — Cyrillic, CJK, Arabic — reduces
    to something empty or partial and is refused by :func:`validate` with a clear
    message, rather than being silently transliterated into a name the agent did not
    choose.

    This is the one deliberate Western bias in the design, and it is the owner's call:
    names are strictly ASCII, lowercase, underscore-separated. An agent whose name is
    written in another script picks its own romanisation — which is what people do
    anyway, and a better outcome than a machine guessing a reading and being wrong.
    """
    decomposed = unicodedata.normalize("NFKD", raw.strip())
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    underscored = re.sub(r"[\s\-.']+", "_", folded.lower())
    collapsed = re.sub(r"_{2,}", "_", underscored)
    return re.sub(r"[^a-z0-9_]", "", collapsed).strip("_")


def validate(raw: str) -> Name:
    """Validate a proposed name, or explain precisely why it cannot be used.

    The message matters: an agent reads it and has to act on it unaided.
    """
    candidate = normalize(raw)
    if not candidate:
        raise NameUnavailable(
            f"{raw!r} has no usable characters — names are ASCII letters, digits and "
            "underscores, so pick a romanised form (for example 'yitzhak_levin')"
        )
    if candidate in RESERVED_NAMES:
        raise NameUnavailable(
            f"{candidate!r} is reserved for addressing and cannot be a name; "
            f"reserved: {', '.join(sorted(RESERVED_NAMES))}"
        )
    if not _VALID.match(candidate):
        raise NameUnavailable(
            f"{candidate!r} is not a usable name — 1 to 64 characters, starting and "
            "ending with a letter or digit"
        )
    return Name(candidate)


def validate_operator_name(raw: str) -> str:
    """Validate a human operator's username. It must be a name an actor could hold.

    Operators and agents are becoming **one namespace** (owner, 2026-08-05): signing in
    as a human will give you that human's mailbox, and a mailbox is addressed by an
    actor name. A username that no actor could hold is therefore an account that can
    never have an inbox — so the rule is applied at registration, where the person is
    present to fix it, rather than discovered later by someone whose mail has nowhere
    to go.

    Two deliberate differences from :func:`validate`, and the reasoning for each is the
    reasoning in :func:`validate_hub_name`:

    **No normalisation, except case.** ``validate`` reshapes a proposed *agent* name
    because the hub is issuing it. A username is typed into a form by somebody who then
    has to type it again to sign in, so quietly turning ``sal.fadhley`` into
    ``sal_fadhley`` hands them a login they did not choose and will get wrong. They are
    told the rule instead. Case is the exception — ``Sal`` and ``sal`` are the same
    word, every login system in the world folds it, and this one already did.

    **A standing resident is allowed.** ``admin`` is refused to agents precisely so it
    stays available to the human who operates the hub; refusing it here would lock the
    one account the merge exists to serve out of its own name. Addressing keywords stay
    refused to everybody: ``everyone`` as a username would make a broadcast ambiguous
    no matter which side of the machine held it.
    """
    candidate = raw.strip().lower()
    if not candidate:
        raise NameUnavailable("an operator needs a username")
    if candidate in ADDRESSING_KEYWORDS:
        raise NameUnavailable(
            f"{candidate!r} is how mail is addressed, not who somebody is; "
            f"reserved: {', '.join(sorted(ADDRESSING_KEYWORDS))}"
        )
    if not _VALID.match(candidate):
        raise NameUnavailable(
            f"{candidate!r} cannot be a username — 1 to 64 characters of lowercase "
            "letters, digits and underscores, starting and ending with a letter or "
            f"digit (try {normalize(candidate)!r})"
            if normalize(candidate)
            else f"{candidate!r} cannot be a username — use lowercase letters, digits "
            "and underscores, for example 'sam_okonkwo'"
        )
    return candidate


def validate_hub_name(raw: str) -> str:
    """Validate a hub's name — the right-hand side of ``name@hub``.

    Two differences from :func:`validate`, and both are deliberate.

    **No normalisation.** ``validate`` folds and reshapes a proposed *agent* name
    because the hub is issuing it and an agent should get close to what it asked for.
    A hub name is typed by an operator into a form, and silently turning ``The Salt
    Club`` into ``the_salt_club`` is what the system does today and is the bug: they
    should learn what a hub name is, not receive one they did not choose.

    **``local`` is permitted.** It is reserved as an *address* keyword, and it is also
    the default hub name — every hub answers to it as well as to its own name. What
    ``local`` blocks is *enabling federation*, and that rule lives in
    :mod:`agent_inbox.federation`, where the consequence is.

    The rule itself is :data:`_VALID`, unchanged — the same pattern the left-hand side
    of the same address already satisfies. Two validators that nearly agree is a worse
    state than one: the disagreement surfaces later, in a case nobody chose.
    """
    candidate = raw.strip()
    if not candidate:
        raise NameUnavailable(
            "a hub name cannot be empty — use lowercase letters, digits and "
            "underscores, for example 'saltclub'"
        )
    if "." in candidate or "/" in candidate or ":" in candidate:
        raise NameUnavailable(
            f"{candidate!r} looks like an address, not a name. A hub's address is set "
            "by the deployment and a hub may answer to several; its *name* is the "
            "'@hub' part that identifies it — lowercase letters, digits and "
            "underscores, for example 'saltclub'"
        )
    if not _VALID.match(candidate):
        raise NameUnavailable(
            f"{candidate!r} is not a usable hub name — 1 to 64 characters, lowercase "
            "letters, digits and underscores, starting and ending with a letter or "
            "digit, for example 'saltclub'"
        )
    return candidate


def generate(seed: int | None = None) -> str:
    """Propose a name from the checked-in pool.

    Given and family names are drawn **independently**, so most results cross
    traditions — ``rosemary_nasrin``, ``trevor_mahmood``. That is the intent: the
    workforce is explicitly and absurdly multicultural, and pairing within a tradition
    would give a tidier, duller, less representative result.

    Returns a *candidate*. Uniqueness is the directory's job — a generator cannot know
    what is already taken.
    """
    rng = random.Random(seed)
    return f"{rng.choice(GIVEN_NAMES)}_{rng.choice(FAMILY_NAMES)}"
