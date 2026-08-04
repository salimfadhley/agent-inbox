"""Watching the whole hub, rather than one agent's mail.

The per-actor stream answers "has anything arrived for me". A console watching a hub
needs "has anything arrived at all", which is a different subscriber and — importantly —
a different *arity*. `House._announce` calls `announce` once per local recipient, so a
hub-wide leg folded into that call would deliver one message once per person it reached.
The test that pins this is `test_a_message_to_three_recipients_arrives_once`, and it is
the reason `announce_all` exists as its own method.
"""

import asyncio

import pytest

from agent_inbox.notify import Arrival, Listeners, TooManyListeners

ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"
YITZHAK = "yitzhak_levin"


def arrival(id_: str, sender: str = ROSEMARY, subject: str = "hello") -> Arrival:
    return Arrival(
        id=id_, sender=sender, subject=subject, published="2026-08-04T00:00:00Z"
    )


def drain(queue: asyncio.Queue[Arrival]) -> list[str]:
    got: list[str] = []
    while not queue.empty():
        got.append(queue.get_nowait().id)
    return got


async def test_a_watcher_sees_arrivals_for_every_actor() -> None:
    listeners = Listeners()
    with listeners.watching() as everything:
        listeners.announce_all(arrival("a"))
        listeners.announce_all(arrival("b"))

        assert drain(everything) == ["a", "b"]


async def test_a_per_actor_listener_still_sees_only_its_own() -> None:
    """The paired positive.

    Without it, the test above would pass on an implementation that had simply started
    broadcasting everything to everybody — which would be a disclosure bug wearing the
    costume of a working feature.
    """
    listeners = Listeners()
    with listeners.listening(ROSEMARY) as hers, listeners.listening(TREVOR) as his:
        listeners.announce(ROSEMARY, arrival("for-her"))
        listeners.announce(TREVOR, arrival("for-him"))

        assert drain(hers) == ["for-her"]
        assert drain(his) == ["for-him"]


async def test_a_message_to_three_recipients_arrives_once() -> None:
    """The regression that forced `announce_all` to be its own method.

    This mirrors what `House._announce` does: one `announce` per local recipient, and
    one `announce_all` for the message. Fold the hub-wide leg into `announce` and a
    watcher sees this single message three times.
    """
    listeners = Listeners()
    one = arrival("just-the-one")
    with listeners.watching() as everything:
        for who in (ROSEMARY, TREVOR, YITZHAK):
            listeners.announce(who, one)
        listeners.announce_all(one)

        assert drain(everything) == ["just-the-one"]


async def test_a_watcher_is_not_reported_as_an_actor() -> None:
    listeners = Listeners()
    with listeners.watching():
        assert listeners.by_actor() == {}
        assert listeners.count_for(ROSEMARY) == 0
        assert listeners.count_for("") == 0
        assert listeners.count_for("*") == 0
        # But it is a held connection, and `count` is the method that means all of them.
        assert listeners.count() == 1
        assert listeners.count_everything() == 1


async def test_watchers_count_towards_the_cap() -> None:
    listeners = Listeners(max_listeners=2)
    with listeners.watching(), listeners.watching():
        assert listeners.at_capacity()
        with pytest.raises(TooManyListeners):
            listeners.open_everything()
        with pytest.raises(TooManyListeners):
            listeners.open(ROSEMARY)


async def test_a_watcher_and_a_listener_share_one_cap() -> None:
    listeners = Listeners(max_listeners=2)
    with listeners.listening(ROSEMARY), listeners.watching():
        assert listeners.count() == 2
        assert listeners.at_capacity()


async def test_closing_releases_the_slot() -> None:
    listeners = Listeners(max_listeners=1)
    with listeners.watching():
        assert listeners.at_capacity()
    assert listeners.count() == 0
    assert not listeners.at_capacity()


async def test_closing_twice_is_harmless() -> None:
    """Callers close from a `finally`, which can run after an earlier close."""
    listeners = Listeners()
    queue = listeners.open_everything()
    listeners.close_everything(queue)
    listeners.close_everything(queue)
    assert listeners.count() == 0


async def test_announcing_to_nobody_is_fine() -> None:
    assert Listeners().announce_all(arrival("unheard")) == 0


async def test_a_watcher_that_falls_behind_drops_rather_than_blocks() -> None:
    """A send must never be slowed by somebody watching it."""
    listeners = Listeners(queue_depth=2)
    with listeners.watching() as everything:
        for n in range(5):
            listeners.announce_all(arrival(str(n)))

        assert drain(everything) == ["0", "1"]
