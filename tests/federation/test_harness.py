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
