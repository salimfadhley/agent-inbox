"""The remote half of a send, and what to tell the sender about it.

`House.send` handles both halves of a message. The local half is a row in this store;
the remote half is somebody else's HTTP endpoint, and it can fail in ways a local
delivery never can. This module holds the collaborator that performs it and the shape of
the answer.

**A house with no delivery collaborator refuses remote recipients. It never drops
them.** That is the whole reason this is injected rather than looked up: a `House` built
without federation and handed `atlas@beta.example` must say so, because a send that
succeeds and reaches nobody is the worst failure shape available.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from agent_inbox import outbound
from agent_inbox.keys import PRIVATE_KEY_SETTING, SigningKey, generate
from agent_inbox.records import ObjectRecord

#: What every `queued` receipt tells the sender about how long the wait is good for.
#:
#: The retry queue is held in memory and does not survive a restart — a deliberate
#: choice for the first slice, permitted **only** because the volatility is disclosed
#: rather than discovered. This hub is redeployed on every release, so "we restarted" is
#: a scheduled event rather than an edge case, and a sender told `queued` with no
#: disclosure would hold a promise we stop keeping without ever saying so.
NOT_DURABLE = (
    "waiting for the peer to become reachable. This wait is held in memory and "
    "does not survive a restart of this hub."
)


@dataclass(frozen=True, slots=True)
class Receipt:
    """What happened to one remote recipient.

    Local recipients get no receipt: storing the row *is* the delivery, and there is no
    separate act that could have failed.
    """

    recipient: str
    delivered: bool
    detail: str | None = None
    #: Accepted for retry: not delivered, but not failed either. `delivered` stays a
    #: boolean that is true to its name — a queued message genuinely has not arrived —
    #: so every existing reader of it keeps giving the right answer.
    queued: bool = False

    @classmethod
    def waiting(cls, recipient: str) -> Receipt:
        """A receipt for a message accepted onto the retry queue.

        **The only way to mint one**, so the durability disclosure cannot be left off by
        a caller who did not know it was required. A rule that lives in one constructor
        is kept; a rule that lives in a docstring is remembered until it isn't.
        """
        return cls(recipient, delivered=False, queued=True, detail=NOT_DURABLE)

    @property
    def state(self) -> str:
        """`queued`, `delivered` or `failed`.

        Three words rather than a boolean, which is why adding the third broke no
        client: anything reading this already had to handle an unrecognised word.
        """
        if self.queued:
            return "queued"
        return "delivered" if self.delivered else "failed"


@dataclass(frozen=True, slots=True)
class Sent:
    """A stored message, and what became of any remote recipients."""

    record: ObjectRecord
    receipts: tuple[Receipt, ...] = ()
    #: The local recipients the message actually reached.
    #:
    #: Told to us rather than read back off ``record.to``, and the difference is not
    #: cosmetic. Since step 6 that field holds local names **and** remote actor URIs
    #: (ADR 0003), so a remote recipient that resolved and then failed delivery still
    #: appears in it. Deriving "did anyone get this" from ``to`` therefore counted an
    #: undelivered stranger as a success — which the two-hub test caught.
    local_recipients: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def reached_local_recipients(self) -> bool:
        return bool(self.local_recipients)

    @property
    def reached_nobody(self) -> bool:
        """True when nothing was delivered anywhere.

        The one case that must never look like success. `api.py` already refuses to
        return 201 for a reply addressed to nobody, calling it "a silent success, which
        is the worst failure shape we have"; a send whose only recipients were remote
        and unreachable is the same thing arriving by a different route.
        """
        if self.reached_local_recipients:
            return False
        # A queued recipient has not been reached, but it has not failed either — it is
        # still being tried. Counting it as "nobody" would turn the ordinary case this
        # queue exists for, a peer that is merely asleep, into a hard error the sender
        # cannot act on, moments before the message very likely arrives.
        if any(r.queued for r in self.receipts):
            return False
        return bool(self.receipts) and not any(r.delivered for r in self.receipts)


class RemoteDelivery(Protocol):
    """How a house reaches another hub.

    Two steps rather than one, because the answer to the first is needed *before* the
    message is stored: a remote recipient is recorded by its actor URI (ADR 0003), and
    that URI is what resolution produces.
    """

    async def resolve(self, address: str) -> object:
        """Turn `alice@beta.example` into something :meth:`deliver` takes, or raise."""
        ...

    def actor_uri(self, resolved: object) -> str:
        """The actor URI of a resolved recipient — what gets stored."""
        ...

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        """Sign and send, or raise. Authorization is re-derived inside this call."""
        ...


async def hub_signing_key(mailbox: Any) -> SigningKey:
    """This hub's key, minted on first need and kept thereafter.

    Generated lazily rather than at startup: a hub that never federates never needs one,
    and generating a 2048-bit key on every boot of every test would be a cost with no
    purpose.
    """
    stored = await mailbox.hub_settings()
    pem = stored.get(PRIVATE_KEY_SETTING)
    if pem:
        return SigningKey(pem)
    minted = generate()
    await mailbox.set_hub_setting(PRIVATE_KEY_SETTING, minted.private_pem)
    return minted


@dataclass(frozen=True, slots=True)
class FederatedDelivery:
    """Delivery over the fediverse, as Step 6 built it.

    Every network call goes to a thread: the machinery underneath is `urllib`, which is
    blocking, and running it on the event loop would stall the whole hub while somebody
    else's server thinks about it.
    """

    mailbox: Any
    public_url: str

    async def _signing(self, sender: str) -> tuple[SigningKey, str]:
        key = await hub_signing_key(self.mailbox)
        # The sending actor, not a hub-level one. One hub key signs for the whole
        # roster, so any actor's document would verify — but receiving implementations
        # commonly check that the signer and the activity's `actor` agree, and a
        # hub-level `keyId` on a `Create` fails that check. The limit this leaves
        # behind is recorded in `doc/federation-step-6.md`: it reads as though the
        # actor holds the key, when the hub does.
        return key, f"{self.public_url}/actors/{sender}#main-key"

    async def resolve(self, address: str) -> object:
        key, key_id = await self._signing("host")
        return await asyncio.to_thread(outbound.resolve, address, (key, key_id))

    def actor_uri(self, resolved: object) -> str:
        assert isinstance(resolved, outbound.RemoteRecipient)
        return resolved.actor_uri

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        assert isinstance(resolved, outbound.RemoteRecipient)
        key, key_id = await self._signing(record.attributed_to)

        # Read immediately before the call and handed straight in, so `outbound.deliver`
        # decides against what is true *now*. Never cache this (FR-050).
        settings = await self.mailbox.hub_settings()
        peers = await self.mailbox.peers()

        name = resolved.handle.partition("@")[0]
        activity: dict[str, object] = {
            "type": "Create",
            "id": f"{self.public_url}/act/{record.id}",
            "actor": f"{self.public_url}/actors/{record.attributed_to}",
            "object": {
                "type": "Note",
                "to": [name],
                "content": record.content,
                "summary": record.summary,
                "inReplyTo": record.in_reply_to,
            },
        }
        await asyncio.to_thread(
            outbound.deliver,
            resolved,
            activity,
            key=key,
            key_id=key_id,
            settings=settings,
            peers=peers,
        )
