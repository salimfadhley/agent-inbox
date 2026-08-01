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

from agent_inbox.exceptions import MailboxError

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
