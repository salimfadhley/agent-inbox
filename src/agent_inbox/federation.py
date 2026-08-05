"""Whether this hub federates, and the one rule about turning it on.

Federation itself is not built. What lives here is the switch and the rule that guards
it, because both are needed before any discovery surface can decide whether to answer.

The rule is small and worth stating plainly: **a hub called ``local`` cannot enable
federation.** ``local`` is the default name and a real one — every hub answers to it
as well as to its own name, and an address ending ``@local`` is a promise of
non-egress. But a hub called "local" cannot be told apart from every other hub called
"local", which is fine until the moment it must not be, and that moment is federation.

Note what is gated: **enabling the mode**, not federating. A hub that has switched
federation on and has not been named is a state worth not having.
"""

from dataclasses import dataclass

from agent_inbox.exceptions import MailboxError
from agent_inbox.store import MessageStore

#: The name every hub answers to in addition to its own, and the default.
LOCAL = "local"

#: The setting's key, and its values. Deliberately two: `open` mode and anything else
#: belong to a later step, and a mode with nothing behind it would be decoration.
FEDERATION_KEY = "federation"
DISABLED = "disabled"
ENABLED = "enabled"
FEDERATION_MODES = (DISABLED, ENABLED)


class FederationRefused(MailboxError):
    """Federation cannot be enabled in the hub's current state."""

    code = "federation_refused"


def check_may_enable_federation(hub_name: str) -> None:
    """Refuse to enable federation on a hub that has no name of its own.

    Raises with the reason rather than returning a bool: the operator needs to be told
    *why*, and a caller reconstructing the reason is how two call sites start to
    disagree.
    """
    if hub_name.strip().lower() == LOCAL:
        raise FederationRefused(
            "this hub is called 'local', and a hub called 'local' cannot be told apart "
            "from every other hub called 'local'. Give it a name before enabling "
            "federation — Settings, or AGENT_INBOX_HUB_NAME"
        )


def federates(settings: dict[str, str]) -> bool:
    """Whether federation is on. Off unless something says otherwise."""
    return settings.get(FEDERATION_KEY, DISABLED) == ENABLED


class PeerBlocked(MailboxError):
    """This origin is refused, whatever the mode says.

    Its own type rather than a generic refusal, because the *remedy* differs from every
    other reason an exchange might not happen: nothing about the peer, the network or
    the mode will change it. An operator decided this, and only an operator undoes it.
    """

    code = "peer_blocked"


@dataclass(frozen=True, slots=True)
class Exchange:
    """Whether an exchange with an origin may happen, and why not if it may not.

    Carrying the reason rather than a bare ``False`` is the same rule the rest of this
    codebase follows: a caller reconstructing *why* is how two call sites begin to
    disagree, and a disagreement about whether to talk to a stranger is a disclosure.
    """

    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


async def may_exchange(store: MessageStore, origin: str) -> Exchange:
    """**The** decision: may this hub exchange anything with *origin*?

    One function, consulted by every path that needs the answer — adding a peer,
    delivering outbound, accepting inbound. If the decision is made in two places they
    will disagree, and a disagreement here is a disclosure (C-006).

    **The blocklist overrides the mode in every case, and is checked first.** A blocked
    origin is refused even when it is also a trusted peer: that combination is not a
    contradiction to resolve but a peer somebody added and later blocked, and block
    wins. Checking it first is not an optimisation — it is what stops a blocked hub
    learning that we tried.

    Matching is on the **normalised** origin, through the same `peer_origin` every other
    guard uses, so a block survives the three ways one is evaded by accident: case, a
    trailing slash, and an explicit `:443`.

    Nothing here reads the mode setting. Whether federation is on at all is a separate
    question with a separate answer, asked by the caller that knows the mode; folding it
    in would make this function need a second input and give it a second reason to
    refuse, which is how one decision becomes two.
    """
    from agent_inbox.peers import peer_origin

    try:
        normalised = peer_origin(origin)
    except MailboxError as unusable:
        # An origin we cannot even normalise is not one we can decide about, and
        # "cannot parse" must never read as "permitted".
        return Exchange(False, str(unusable))

    blocked = await store.blocks()
    if normalised in blocked:
        note = blocked[normalised]
        because = f" — {note}" if note else ""
        return Exchange(False, f"{normalised} is blocked by this hub{because}")
    return Exchange(True)
