"""Addressing another hub from `House.send` — the wiring of federation step 6.

The network half is proved against two real servers in
`tests/federation/test_two_real_hubs.py`. What is proved *here* is the part that has
nothing to do with sockets: which recipients go where, what gets stored for a remote
one, and what the sender is told when somebody else's server is down.

The delivery collaborator is faked, deliberately. A fake makes the interesting
failures — resolution refused, delivery refused, nothing reachable at all — cheap
enough to assert one at a time, and it is the only way to assert that a request was
**not attempted**.
"""

from collections.abc import AsyncIterator

import pytest

from agent_inbox.exceptions import RemoteMailbox
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.peers import PeerUnreachable
from agent_inbox.records import ObjectRecord
from agent_inbox.store import InMemoryStore
from agent_inbox.wire import Renderer

ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"
ATLAS = "atlas@beta.example"


class FakeDelivery:
    """A delivery collaborator that never opens a socket.

    Records every address it was *asked* about, which is what lets a test assert that
    `@local` never reached the network at all.
    """

    def __init__(self, unresolvable: set[str] | None = None, refuse: bool = False):
        self.resolved: list[str] = []
        self.delivered: list[tuple[str, str]] = []
        self.unresolvable = unresolvable or set()
        self.refuse = refuse

    async def resolve(self, address: str) -> object:
        self.resolved.append(address)
        if address in self.unresolvable:
            raise PeerUnreachable(f"could not reach {address}")
        name, _, host = address.partition("@")
        return f"https://{host}/actors/{name}"

    def actor_uri(self, resolved: object) -> str:
        assert isinstance(resolved, str)
        return resolved

    async def deliver(self, resolved: object, record: ObjectRecord) -> None:
        if self.refuse:
            # The status matters as of step 7, and this fake stated its 403 in prose
            # only. A peer that *answered* 403 has considered the message and rejected
            # it — terminal. A `PeerUnreachable` with no status means nobody answered at
            # all, which is the retryable case and a different scenario entirely.
            raise PeerUnreachable(f"{resolved} refused it (403)", status=403)
        assert isinstance(resolved, str)
        self.delivered.append((resolved, record.id))


@pytest.fixture
async def parochial() -> AsyncIterator[House]:
    """A house that cannot reach another hub — no delivery collaborator at all."""
    async with House(Mailbox(InMemoryStore())) as opened:
        yield opened


@pytest.fixture
async def federated() -> AsyncIterator[tuple[House, FakeDelivery]]:
    post = FakeDelivery()
    async with House(Mailbox(InMemoryStore()), deliver=post) as opened:
        await opened.join(ROSEMARY)
        await opened.join(TREVOR)
        yield opened, post


class TestAHouseThatCannotFederate:
    async def test_a_remote_recipient_is_refused_not_dropped(
        self, parochial: House
    ) -> None:
        """The whole reason delivery is injected rather than looked up.

        Delivering the local half and quietly discarding the rest would return 201 and
        reach nobody, which is the worst failure shape this project has.
        """
        await parochial.join(ROSEMARY)
        with pytest.raises(RemoteMailbox) as refused:
            await parochial.send(ROSEMARY, ATLAS, "over there")
        assert ATLAS in str(refused.value)

    async def test_the_local_half_is_refused_with_it(self, parochial: House) -> None:
        """All or nothing when the house cannot federate at all.

        A partial send here would be *silent* about the missing half, because there are
        no receipts to carry the news — this house has no delivery collaborator to
        produce them. Refusing the whole attempt is the only honest answer available.
        """
        await parochial.join(ROSEMARY)
        await parochial.join(TREVOR)
        with pytest.raises(RemoteMailbox):
            await parochial.send(ROSEMARY, [TREVOR, ATLAS], "half here, half away")
        assert await parochial.observe_mailbox(TREVOR) == ()


class TestWhatGetsStored:
    async def test_a_remote_recipient_is_stored_by_its_actor_uri(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        """ADR 0003: the identifier is a URI. No identifier is minted for a stranger."""
        house, _ = federated
        sent = await house.send(ROSEMARY, ATLAS, "hello over there")
        assert sent.record.to == ("https://beta.example/actors/atlas",)

    async def test_the_typed_address_survives_as_audience(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        """`to` is who it reached; `audience` is what was typed. Both must be true."""
        house, _ = federated
        sent = await house.send(ROSEMARY, [TREVOR, ATLAS], "both")
        assert list(sent.record.document["audience"]) == [TREVOR, ATLAS]
        assert TREVOR in sent.record.to
        assert "https://beta.example/actors/atlas" in sent.record.to

    async def test_a_local_send_stores_exactly_what_it_always_did(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        """The widening must be invisible when nobody is remote."""
        house, post = federated
        sent = await house.send(ROSEMARY, TREVOR, "ordinary")
        assert sent.record.to == (TREVOR,)
        assert sent.receipts == ()
        assert post.resolved == [], "a local send must not touch the network"


class TestWhatTheSenderIsTold:
    async def test_a_delivered_remote_recipient_is_reported(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        house, _ = federated
        sent = await house.send(ROSEMARY, ATLAS, "hello")
        assert [(r.recipient, r.state) for r in sent.receipts] == [(ATLAS, "delivered")]

    async def test_an_unresolvable_recipient_fails_and_the_local_copy_survives(
        self,
    ) -> None:
        """FR-7 and FR-8: the sender's own message must not be lost to someone else's
        outage, and the failure must be said out loud."""
        post = FakeDelivery(unresolvable={ATLAS})
        async with House(Mailbox(InMemoryStore()), deliver=post) as house:
            await house.join(ROSEMARY)
            await house.join(TREVOR)
            sent = await house.send(ROSEMARY, [TREVOR, ATLAS], "partly away")

        assert sent.record.id, "the local copy exists"
        assert TREVOR in sent.record.to, "the local half was delivered"
        failed = [r for r in sent.receipts if not r.delivered]
        assert [r.recipient for r in failed] == [ATLAS]
        assert "could not reach" in (failed[0].detail or "")
        assert not sent.reached_nobody, "somebody got it"

    async def test_a_send_that_reached_nobody_is_not_a_success(self) -> None:
        """The rule inherited from the reply-to-nobody fix: reaching nobody must never
        look like it worked."""
        post = FakeDelivery(unresolvable={ATLAS})
        async with House(Mailbox(InMemoryStore()), deliver=post) as house:
            await house.join(ROSEMARY)
            sent = await house.send(ROSEMARY, ATLAS, "into the void")

        assert sent.reached_nobody
        assert sent.record.id, "and the sender still has their own copy"

    async def test_a_refused_delivery_is_reported_not_raised(self) -> None:
        """A peer saying no is news for the sender, not an exception that loses the
        message that was already stored."""
        post = FakeDelivery(refuse=True)
        async with House(Mailbox(InMemoryStore()), deliver=post) as house:
            await house.join(ROSEMARY)
            sent = await house.send(ROSEMARY, ATLAS, "unwelcome")

        assert [r.state for r in sent.receipts] == ["failed"]
        assert "refused it" in (sent.receipts[0].detail or "")

    async def test_state_is_a_word_so_step_seven_can_add_one(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        """`delivered`/`failed` today, `queued` when there is a queue. A boolean would
        have to become a lie or a breaking change."""
        house, _ = federated
        sent = await house.send(ROSEMARY, ATLAS, "hello")
        assert sent.receipts[0].state in {"delivered", "failed", "queued"}


class TestLocalNeverEgresses:
    async def test_at_local_is_never_offered_to_the_network(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        """**Asserted on the attempt, not the outcome.** A `@local` address that reaches
        the network and is refused there has already leaked that it exists.

        And it holds by construction rather than by a check: `@local` is local to every
        hub, so `split_recipients` cannot put it in the remote half.
        """
        house, post = federated
        await house.send(ROSEMARY, f"{TREVOR}@local", "stays here")
        assert post.resolved == [], "nothing about a @local address may leave"
        assert post.delivered == []

    async def test_a_local_address_still_delivers_locally(
        self, federated: tuple[House, FakeDelivery]
    ) -> None:
        house, _ = federated
        await house.send(ROSEMARY, f"{TREVOR}@local", "stays here")
        assert [m.content for m in await house.observe_mailbox(TREVOR)] == [
            "stays here"
        ]


class TestTheRendererDefectFoundInStepSix:
    """A remote actor is stored by its URI, and `actor_uri` prefixed unconditionally.

    Live on main from step 5 until step 6: an inbound remote message rendered its sender
    as `{ourbase}/actors/https://beta.example/actors/alice`. The stored record was right
    and the rendering was mangled; the two-hub test asserted on the record, which is why
    it passed.
    """

    def test_a_remote_actor_uri_is_not_prefixed_again(self) -> None:
        wire = Renderer("http://ourhub.example")
        remote = "https://beta.example/actors/alice"
        assert wire.actor_uri(remote) == remote

    def test_a_local_name_still_gets_this_hubs_base(self) -> None:
        wire = Renderer("http://ourhub.example")
        assert wire.actor_uri("alice") == "http://ourhub.example/actors/alice"

    def test_an_inbound_remote_message_renders_its_sender_honestly(self) -> None:
        wire = Renderer("http://ourhub.example")
        record = ObjectRecord(
            id="x1",
            attributed_to="https://beta.example/actors/alice",
            to=("bob",),
        )
        note = wire.note(record)
        assert note.attributed_to == "https://beta.example/actors/alice"
        assert note.to == ["http://ourhub.example/actors/bob"]

    def test_a_remote_recipient_renders_honestly_too(self) -> None:
        """The same defect pointing the other way, which is what step 6 would have
        added had the question been answered differently."""
        wire = Renderer("http://ourhub.example")
        record = ObjectRecord(
            id="x2",
            attributed_to="bob",
            to=("https://beta.example/actors/atlas",),
        )
        assert wire.note(record).to == ["https://beta.example/actors/atlas"]
