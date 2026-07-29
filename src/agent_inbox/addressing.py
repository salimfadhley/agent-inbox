"""Addresses: ``name@hub``.

Two halves, and they do different jobs. The **name** identifies an actor and is opaque
(ADR 0003). The **hub** says which mailbox holds them, and is where a guarantee lives.

``local`` is a reserved alias for *this* mailbox, and it is a promise of **non-egress**:
an address ending ``@local`` can never be federated, whatever peering is arranged later.
That makes containment something an agent gets by choosing an address — visible by
inspection, with no configuration to get wrong. The same instinct as ``.local`` in mDNS,
and for the same reason.

Every hub therefore answers to two names: its own, and ``local``.

**This mailbox does not carry mail between hubs yet**, whatever its federation
setting says. Identity federation arrived first — a hub can be discovered, and can
discover others (:mod:`agent_inbox.peers`) — but no message crosses a hub boundary
in either direction.

A message to another hub is therefore **refused, loudly**, rather than silently going
nowhere: an agent learns immediately, and delivery later turns a clear error into a
delivery rather than changing what silence meant.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_inbox.exceptions import MalformedAddress, RemoteMailbox

#: The reserved alias for this mailbox, and the non-egress guarantee.
LOCAL = "local"

#: An address with no ``@`` part is local. Bare names are the common case, and making
#: them mean anything else would be a trap.
DEFAULT_HUB = LOCAL


@dataclass(frozen=True, slots=True)
class Address:
    """A parsed ``name@hub``."""

    name: str
    hub: str = DEFAULT_HUB

    def __str__(self) -> str:
        return f"{self.name}@{self.hub}"

    @property
    def guarantees_non_egress(self) -> bool:
        """Whether this address can *never* leave the mailbox it was written on.

        True only for the literal ``@local``. An address naming the hub by its own
        name is equivalent for delivery **today** but carries no such promise, because
        that name is meaningful to other hubs and this one is not.
        """
        return self.hub == LOCAL

    def is_local_to(self, hub_name: str) -> bool:
        """Whether this address is held by the hub called ``hub_name``."""
        return self.hub in (LOCAL, hub_name)


def parse(text: str, *, default_hub: str = DEFAULT_HUB) -> Address:
    """Parse ``name@hub``, or a bare ``name`` meaning this mailbox."""
    raw = text.strip()
    if not raw:
        raise MalformedAddress("an address cannot be empty")
    if raw.count("@") > 1:
        raise MalformedAddress(
            f"{text!r} has more than one '@' — addresses are name@hub"
        )
    name, _, hub = raw.partition("@")
    name, hub = name.strip(), hub.strip()
    if not name:
        raise MalformedAddress(f"{text!r} has no name before the '@'")
    if "@" in raw and not hub:
        raise MalformedAddress(f"{text!r} has no hub after the '@'")
    return Address(name=name.lower(), hub=(hub or default_hub).lower())


def split_recipients(
    addresses: tuple[str, ...], hub_name: str = LOCAL
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition addresses into local names and remote addresses.

    The widening federation needs, and it is deliberately **not** a change to
    :func:`local_name`. That function means "the local name, or refuse", and it is the
    boundary this module exists to keep: above it the world is addresses, below it the
    rules deal only in names. Letting it return something that is not a local name would
    dissolve the very split that lets the rules stay hub-agnostic.

    So the fork happens here, above it, and the rules below never learn that remote
    recipients exist.

    **`@local` can never end up in the remote half**, and by construction rather than by
    a check: an address ending `@local` is local to every hub, so it resolves through
    the first branch and stays. That is what makes the non-egress promise hold even now
    that this hub can send — the guarantee is a property of the addressing model, not a
    rule somebody has to remember to apply.
    """
    local: list[str] = []
    remote: list[str] = []
    for text in addresses:
        address = parse(text)
        if address.is_local_to(hub_name):
            local.append(address.name)
        else:
            remote.append(str(address))
    return tuple(local), tuple(remote)


def local_name(text: str, hub_name: str = LOCAL) -> str:
    """The local actor name an address refers to, refusing anything we cannot reach.

    This is the boundary: above it the world is addresses, below it the messaging rules
    deal only in names. Keeping the split here is what lets the rules stay hub-agnostic
    — and lets federation later widen this one function rather than the whole engine.
    """
    address = parse(text)
    if not address.is_local_to(hub_name):
        raise RemoteMailbox(
            f"{address} is on another mailbox, and this hub does not carry mail "
            f"between hubs yet — reachable addresses end in @{LOCAL} or @{hub_name}"
        )
    return address.name
