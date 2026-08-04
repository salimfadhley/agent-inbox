"""What an agent sent — the half of observation that did not exist.

`observe_mailbox` answers "what was addressed to this agent". Nothing answered "what did
this agent send": `/actors/{name}/outbox` is the route for *sending*, and no query
existed below it. Every test here is written against its received-side twin, because
the failure worth catching is not "returns nothing" — it is "returns everything", which
looks right on any agent whose sent and received happen to overlap.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_inbox.mailbox import Mailbox
from agent_inbox.sqlite_store import SqliteStore
from agent_inbox.store import InMemoryStore, MessageStore

ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"
YITZHAK = "yitzhak_levin"


@pytest.fixture(params=("in_memory", "sqlite"))
async def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[MessageStore]:
    """Both backends, as `test_mailbox.py` does: storage must not matter here either."""
    if request.param == "in_memory":
        yield InMemoryStore()
    else:
        async with SqliteStore(tmp_path / "mail.db") as opened:
            yield opened


@pytest.fixture
async def peopled(store: MessageStore) -> Mailbox:
    mailbox = Mailbox(store)
    for name in (ROSEMARY, TREVOR, YITZHAK):
        await mailbox.join(name)
    return mailbox


async def test_it_returns_only_what_the_agent_sent(peopled: Mailbox) -> None:
    await peopled.send(ROSEMARY, TREVOR, "one", subject="first")
    await peopled.send(ROSEMARY, YITZHAK, "two", subject="second")
    await peopled.send(TREVOR, ROSEMARY, "not hers", subject="inbound")

    sent = await peopled.observe_outbox(ROSEMARY)

    assert [obj.summary for obj in sent] == ["first", "second"]


async def test_the_received_side_still_answers_for_the_same_agent(
    peopled: Mailbox,
) -> None:
    """The paired positive.

    Without it, an `observe_outbox` that returned the whole store would satisfy the test
    above whenever the agent under test had also received something — and a query that
    returns everything is the likeliest way to get this wrong.
    """
    await peopled.send(ROSEMARY, TREVOR, "one", subject="first")
    await peopled.send(TREVOR, ROSEMARY, "not hers", subject="inbound")

    received = await peopled.observe_mailbox(ROSEMARY)

    assert [obj.summary for obj in received] == ["inbound"]


async def test_the_two_halves_do_not_overlap(peopled: Mailbox) -> None:
    await peopled.send(ROSEMARY, TREVOR, "out", subject="out")
    await peopled.send(TREVOR, ROSEMARY, "in", subject="in")

    sent = {obj.id for obj in await peopled.observe_outbox(ROSEMARY)}
    received = {obj.id for obj in await peopled.observe_mailbox(ROSEMARY)}

    assert not sent & received, (
        "a message cannot be both sent and received by one agent"
    )


async def test_a_message_to_several_recipients_is_sent_once(peopled: Mailbox) -> None:
    """One send, one record — however many people it reached."""
    await peopled.send(ROSEMARY, [TREVOR, YITZHAK], "to both", subject="broadcast")

    assert len(await peopled.observe_outbox(ROSEMARY)) == 1


async def test_it_is_ordered_like_its_twin(peopled: Mailbox) -> None:
    for n in range(3):
        await peopled.send(ROSEMARY, TREVOR, str(n), subject=f"s{n}")

    sent = await peopled.observe_outbox(ROSEMARY)

    assert [obj.published for obj in sent] == sorted(obj.published for obj in sent)


async def test_observing_consumes_nothing(peopled: Mailbox) -> None:
    """Watching must never steal what it was only trying to look at.

    The rule the whole observe block exists under, asserted rather than assumed: the
    console reads this on every agent page, and a read that consumed would empty an
    agent's inbox by being looked at.
    """
    await peopled.send(TREVOR, ROSEMARY, "waiting", subject="unread")
    before = await peopled.unread_count(ROSEMARY)

    await peopled.observe_outbox(ROSEMARY)
    await peopled.observe_outbox(TREVOR)

    assert await peopled.unread_count(ROSEMARY) == before == 1


async def test_an_agent_that_has_sent_nothing_gets_an_empty_answer(
    peopled: Mailbox,
) -> None:
    assert await peopled.observe_outbox(YITZHAK) == ()


async def test_an_unknown_name_is_empty_rather_than_an_error(peopled: Mailbox) -> None:
    """It observes what is stored; it does not adjudicate who exists."""
    assert await peopled.observe_outbox("nobody_here") == ()
