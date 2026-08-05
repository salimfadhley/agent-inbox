"""A blocklist that overrides the mode, and one place that decides.

**The highest-value target in the federation work**, in the parent mission's words, and
the reason is worth keeping in front of whoever reads this next:

> If the decision is made in two places they will disagree, and a disagreement here is a
> disclosure.

So the tests are as much about *where* the decision lives as about what it answers.
"""

import pytest

from agent_inbox.federation import may_exchange
from agent_inbox.store import InMemoryStore

PEER = "https://peer.example"
STAMP = "2026-08-05"


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


class TestABlockRefuses:
    async def test_a_blocked_origin_is_refused(self, store: InMemoryStore) -> None:
        await store.add_block(PEER, STAMP, "spam")

        verdict = await may_exchange(store, PEER)

        assert not verdict
        assert "blocked" in verdict.reason

    async def test_an_unblocked_origin_is_allowed(self, store: InMemoryStore) -> None:
        """The paired positive. Without it a blocklist that refused *everything* would
        satisfy every other test in this file."""
        assert await may_exchange(store, PEER)

    async def test_removing_the_block_restores_the_peer(
        self, store: InMemoryStore
    ) -> None:
        await store.add_block(PEER, STAMP, "spam")
        await store.remove_block(PEER)

        assert await may_exchange(store, PEER)

    async def test_the_reason_carries_the_operators_note(
        self, store: InMemoryStore
    ) -> None:
        """An operator reading a refusal months later needs to know why they made it —
        "blocked" alone sends them to the git history of a database."""
        await store.add_block(PEER, STAMP, "sent phishing to three agents")

        verdict = await may_exchange(store, PEER)

        assert "phishing" in verdict.reason


class TestABlockSurvivesTheThreeAccidentalEvasions:
    """Case, a trailing slash and an explicit `:443`. Each is the same hub, and each is
    how a blocklist stops matching the traffic it was written for."""

    @pytest.mark.parametrize(
        "written",
        [
            "https://PEER.example",
            "https://peer.example/",
            "https://peer.example:443",
            "https://Peer.Example:443/",
        ],
    )
    async def test_a_block_entered_one_way_catches_the_others(
        self, store: InMemoryStore, written: str
    ) -> None:
        await store.add_block(PEER, STAMP)

        assert not await may_exchange(store, written)

    @pytest.mark.parametrize(
        "written",
        ["https://PEER.example", "https://peer.example/", "https://peer.example:443"],
    )
    async def test_and_the_other_direction(
        self, store: InMemoryStore, written: str
    ) -> None:
        """Blocked *as* the variant, checked as the canonical form."""
        from agent_inbox.peers import peer_origin

        await store.add_block(peer_origin(written), STAMP)

        assert not await may_exchange(store, PEER)

    @pytest.mark.parametrize(
        "neighbour",
        [
            # A subdomain: `peer.example` is a *suffix* of this, so a naive `endswith`
            # would block it — and it is a different hub run by different people.
            "https://sub.peer.example",
            # And the other direction, which a naive `startswith` would catch.
            "https://peerless.example",
        ],
    )
    async def test_a_different_hub_is_not_caught(
        self, store: InMemoryStore, neighbour: str
    ) -> None:
        """The paired negative for normalisation: matching must not be so loose that a
        neighbour is blocked by somebody else's block. Blocking the wrong hub is a
        quieter failure than failing to block the right one, and harder to notice."""
        await store.add_block(PEER, STAMP)

        assert await may_exchange(store, neighbour)


class TestBlockBeatsTrust:
    async def test_a_blocked_peer_is_refused_even_when_trusted(
        self, store: InMemoryStore
    ) -> None:
        """FR-004: the blocklist overrides the mode **in every case**. A peer that is
        both trusted and blocked is not a contradiction to resolve — it is one somebody
        added and later blocked, and block wins."""
        await store.add_peer(PEER, STAMP, "an old friend")
        await store.add_block(PEER, STAMP, "not any more")

        assert not await may_exchange(store, PEER)

    async def test_unblocking_does_not_silently_restore_trust(
        self, store: InMemoryStore
    ) -> None:
        """Unblocking says "stop refusing", not "start trusting". The two statements are
        separate and an operator makes each on purpose."""
        await store.add_block(PEER, STAMP)
        await store.remove_block(PEER)

        assert await may_exchange(store, PEER)
        assert PEER not in await store.peers(), "unblocking granted a peering"


class TestAnOriginWeCannotReadIsNotPermitted:
    @pytest.mark.parametrize(
        "junk", ["", "not a url", "http://insecure.example", "ftp://peer.example"]
    )
    async def test_it_fails_towards_refusal(
        self, store: InMemoryStore, junk: str
    ) -> None:
        """The charter's rule, in the one place it matters most: an exception swallowed
        towards *permission* is never acceptable. "Cannot parse" must not read as
        "allowed"."""
        assert not await may_exchange(store, junk)


class TestNoRequestReachesABlockedPeer:
    """FR-007 orders the add flow: normalise, check the blocklist, *then* fetch.

    The order is the requirement, not an optimisation. **Blocking a hub while still
    sending it a request tells it we tried**, which is worse than not blocking it — it
    is a confirmation that this hub exists, is running, and is paying attention to them.
    """

    @staticmethod
    def _hub() -> tuple[object, InMemoryStore]:
        from litestar.testing import TestClient

        from agent_inbox.api import build_api
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox

        made = InMemoryStore()
        house = House(Mailbox(made, hub_name="testhub"))
        return TestClient(app=build_api(house, "http://hub.invalid")), made

    async def test_adding_a_blocked_peer_is_refused(self) -> None:
        client, made = self._hub()
        with client as c:  # type: ignore[attr-defined]
            await made.add_block(PEER, STAMP, "no")

            answer = c.post("/observe/peers", json={"origin": PEER})

        assert answer.status_code == 403, answer.text
        assert PEER not in await made.peers(), "a blocked hub was trusted anyway"

    async def test_no_network_call_is_made(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asserted by counting, with a fetch that fails the test if it is called at
        all — the only way to prove an absence.

        **This one is nearly vacuous and is kept deliberately**, which is worth saying
        rather than letting a future reader mistake it for proof. `add_peer` does not
        contact the peer at all — peering is a local statement about who *we* trust —
        so no request would reach a blocked hub here even with the check removed. The
        removal proof showed exactly that: deleting the guard failed one test, not two.

        It stays as a regression guard for the day somebody makes adding a peer verify
        it, which is a reasonable thing to want. The place a request genuinely *would*
        reach a blocked hub is delivery, and that is asserted in
        `TestNothingIsDeliveredToABlockedHub` below.
        """
        calls: list[str] = []

        def explode(*a: object, **kw: object) -> object:
            calls.append("reached the network")
            raise AssertionError("a blocked peer was contacted")

        monkeypatch.setattr("urllib.request.urlopen", explode)

        client, made = self._hub()
        with client as c:  # type: ignore[attr-defined]
            await made.add_block(PEER, STAMP)
            c.post("/observe/peers", json={"origin": PEER})

        assert calls == []

    async def test_an_unblocked_peer_is_still_added(self) -> None:
        """The paired positive for this whole class. Without it, an add flow that
        refused *everything* would pass every assertion above."""
        client, made = self._hub()
        with client as c:  # type: ignore[attr-defined]
            answer = c.post("/observe/peers", json={"origin": PEER})

        assert answer.status_code == 201, answer.text
        assert PEER in await made.peers()


class TestOneDecisionAndOnlyOne:
    """The property the parent mission called the highest-value target: *"if the
    decision is made in two places they will disagree, and a disagreement here is a
    disclosure."*

    Written against the source, because the second implementation does not exist yet and
    a reviewer's eye is not a guard.
    """

    #: Reading the blocklist anywhere other than the decision function is the shape of a
    #: second implementation. `store.blocks()` is legitimate in the *routes* that list
    #: and edit it — those report and mutate, they do not decide.
    DECIDERS = ("peers.py", "outbound.py", "inbound.py", "delivery.py", "house.py")

    def test_nothing_else_consults_the_blocklist(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "src" / "agent_inbox"
        offenders = [
            f"{name}:{number}"
            for name in self.DECIDERS
            for number, line in enumerate((source / name).read_text().splitlines(), 1)
            if ".blocks(" in line or "federation_blocks" in line
        ]

        assert not offenders, (
            "the blocklist is read outside the decision function, which is how two "
            f"answers begin to disagree: {offenders}"
        )

    def test_the_search_would_find_one(self) -> None:
        """The premise. A check that matches nothing passes for the wrong reason."""
        probe = "        blocked = await store.blocks()"
        assert ".blocks(" in probe


class TestNothingIsDeliveredToABlockedHub:
    """Where FR-007's "no request reaches a blocked peer" actually bites.

    Adding a peer never touches the network; **delivery does**. A blocked hub must learn
    nothing, and a request arriving is itself information — it confirms this hub exists,
    is running, and is still trying to reach them.
    """

    @staticmethod
    async def _house(made: InMemoryStore) -> object:
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox

        return House(Mailbox(made, hub_name="testhub"))

    async def test_delivery_to_a_blocked_origin_is_refused_before_the_socket(
        self, store: InMemoryStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox import outbound
        from agent_inbox.delivery import FederatedDelivery

        def explode(*a: object, **kw: object) -> object:
            raise AssertionError("a blocked hub was contacted")

        monkeypatch.setattr("urllib.request.urlopen", explode)
        monkeypatch.setattr(outbound, "sign_request", lambda *a, **kw: explode())

        await store.add_block(PEER, STAMP, "no")
        house = await self._house(store)
        courier = FederatedDelivery(house.mailbox, "https://us.example")  # type: ignore[attr-defined]
        # `origin` is derived from `actor_uri`, through the same `peer_origin` the
        # decision uses — there is no way to construct a recipient whose origin
        # disagrees with its address, which is itself the right design.
        resolved = outbound.RemoteRecipient(
            handle="them@peer.example",
            actor_uri=f"{PEER}/actors/them",
            inbox=f"{PEER}/actors/them/inbox",
        )

        from agent_inbox.records import ObjectRecord

        with pytest.raises(outbound.DeliveryRefused) as refused:
            await courier.deliver(
                resolved,
                ObjectRecord(id="m1", attributed_to="us", content="x", published="s"),
            )

        assert "blocked" in str(refused.value)

    async def test_an_unblocked_origin_gets_past_the_block_check(
        self, store: InMemoryStore
    ) -> None:
        """The paired positive: the gate must refuse blocked hubs, not all hubs. It gets
        past the block and stops at the *peering* check, which is the next question and
        a different one."""
        from agent_inbox import outbound
        from agent_inbox.delivery import FederatedDelivery
        from agent_inbox.records import ObjectRecord

        house = await self._house(store)
        courier = FederatedDelivery(house.mailbox, "https://us.example")  # type: ignore[attr-defined]
        # `origin` is derived from `actor_uri`, through the same `peer_origin` the
        # decision uses — there is no way to construct a recipient whose origin
        # disagrees with its address, which is itself the right design.
        resolved = outbound.RemoteRecipient(
            handle="them@peer.example",
            actor_uri=f"{PEER}/actors/them",
            inbox=f"{PEER}/actors/them/inbox",
        )

        with pytest.raises(outbound.DeliveryRefused) as refused:
            await courier.deliver(
                resolved,
                ObjectRecord(id="m1", attributed_to="us", content="x", published="s"),
            )

        said = str(refused.value)
        assert "blocked" not in said, (
            f"an unblocked hub was reported as blocked: {said}"
        )
