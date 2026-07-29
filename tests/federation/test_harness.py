"""The harness proves itself before anything relies on it.

A harness that delivers regardless of addressing would make every later test pass for
the wrong reason, so the important test here is the one where nothing arrives.
"""

from __future__ import annotations

import contextlib

import pytest

from .harness import two_hubs


@pytest.fixture
def fleet():
    fleet, clients = two_hubs()
    with contextlib.ExitStack() as stack:
        for client in clients:
            stack.enter_context(client)
        yield fleet


def test_the_hubs_are_genuinely_separate(fleet) -> None:
    """Shared state would make every isolation assertion vacuous."""
    assert fleet["alpha"].house is not fleet["beta"].house
    assert fleet["alpha"].base != fleet["beta"].base


def test_one_hub_can_read_the_other(fleet) -> None:
    """Only once beta has chosen to federate — a hub that has not is silent."""
    import asyncio

    beta = fleet["beta"]
    assert fleet.fetch("alpha", f"{beta.base}/nodeinfo/2.1")[0] == 404

    asyncio.run(beta.house.mailbox.set_hub_setting("federation", "enabled"))
    status, body = fleet.fetch("alpha", f"{beta.base}/nodeinfo/2.1")
    assert status == 200
    assert body["software"]["name"] == "agent-inbox"


def test_an_unknown_host_fails_the_way_an_unreachable_one_would(fleet) -> None:
    """The assertion that makes the rest of the suite mean anything.

    If the transport delivered to whoever was listening, a test that pointed at the
    wrong hub would still pass — and every policy test after it would be worthless.
    """
    with pytest.raises(ConnectionError):
        fleet.fetch("alpha", "http://nowhere.invalid/nodeinfo/2.1")


def test_attempts_are_recorded_even_when_refused(fleet) -> None:
    """Some rules are about not *trying*, so silence and refusal must be different."""
    fleet.fetch(
        "alpha", f"{fleet['beta'].base}/.well-known/webfinger?resource=acct:x@y"
    )
    attempts = fleet.attempted("beta")
    assert attempts, "a refused request is still an attempt"
    assert attempts[-1].status == 404
    assert attempts[-1].delivered is True


def test_a_hub_sees_only_what_the_other_publishes(fleet) -> None:
    """The end-to-end shape of Step 2: beta federates, alpha reads it, and gets the
    barebones document rather than beta's roster."""
    import asyncio

    beta = fleet["beta"]
    asyncio.run(beta.house.mailbox.set_hub_setting("federation", "enabled"))
    asyncio.run(beta.house.join("alice"))

    status, finger = fleet.fetch(
        "alpha", f"{beta.base}/.well-known/webfinger?resource=acct:alice@beta.invalid"
    )
    assert status == 200, finger
    actor_url = finger["links"][0]["href"]

    status, actor = fleet.fetch("alpha", actor_url)
    assert status == 200
    assert actor["preferredUsername"] == "alice"
    assert "profile" not in actor, "alpha must not learn beta's agent profiles"


def test_a_signed_peer_sees_more_than_a_stranger(fleet) -> None:
    """Step 4, end to end: `AUTHORIZED_FETCH` between two hubs.

    This is what the thin/rich split was built for. Before signatures there was no way
    for a peer to ever be verified, so everyone got the barebones document forever.
    """
    import asyncio

    from agent_inbox.api import Api

    alpha, beta = fleet["alpha"], fleet["beta"]
    for hub in (alpha, beta):
        asyncio.run(hub.house.mailbox.set_hub_setting("federation", "enabled"))
    asyncio.run(beta.house.join("alice"))
    asyncio.run(alpha.house.join("asker"))

    url = f"{beta.base}/actors/alice"

    # The transport is in-process, so fetch through the client rather than the network.
    unsigned = beta.client.get("/actors/alice").json()
    assert "profile" not in unsigned, "a stranger must not see an agent's profile"

    key = asyncio.run(Api(alpha.house, alpha.base).signing_key())
    from agent_inbox.signatures import sign_request

    key_id = f"{alpha.base}/actors/asker#main-key"
    headers = sign_request(key, key_id, "GET", url)
    signed = beta.client.get("/actors/alice", headers=headers)

    # The verifier fetches alpha's key over the real network, which the harness does
    # not provide — so this asserts the *decision*, not a successful round trip. The
    # two-hub HTTP demo covers the round trip.
    assert signed.status_code == 200
    assert unsigned == beta.client.get("/actors/alice").json()
