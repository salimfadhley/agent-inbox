"""The client's readers for the operator's view.

Thin by design — one core, and every client is a client (ADR 0005). What is worth
pinning is that they are thin: a reader that filtered, sorted or clamped would be a
client making a decision the hub is supposed to own, and the clamp in particular must
stay the hub's, because a client-side one is a rule that only applies to callers who
happen to use this client.
"""

import pytest

from agent_inbox.client import Config, HubClient


@pytest.fixture
def calls() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def client(calls: list[tuple[str, str]]) -> HubClient:
    made = HubClient(Config(hub="http://hub.invalid", name="jed_smith", token="tok"))

    def record(method: str, path: str, *_: object, **__: object) -> dict[str, object]:
        calls.append((method, path))
        return {"items": []}

    made._call = record  # type: ignore[method-assign]
    return made


def test_the_outbox_reader_asks_the_outbox_route(
    client: HubClient, calls: list[tuple[str, str]]
) -> None:
    client.observe_outbox("rosemary_nasrin")

    assert calls == [("GET", "/observe/outbox/rosemary_nasrin")]


def test_the_outbox_reader_is_not_the_mailbox_reader(
    client: HubClient, calls: list[tuple[str, str]]
) -> None:
    """The paired negative: two methods that hit one route would pass the test above."""
    client.observe_mailbox("rosemary_nasrin")
    client.observe_outbox("rosemary_nasrin")

    assert calls[0] != calls[1]


def test_recent_sends_no_limit_unless_asked(
    client: HubClient, calls: list[tuple[str, str]]
) -> None:
    """The default belongs to the hub, and must not be duplicated here.

    A client that sent its own default would be a second place the number lives, and
    the two would drift — with the client's winning, silently, on every deployment
    running an older copy of it.
    """
    client.observe_recent()

    assert calls == [("GET", "/observe/recent")]


def test_recent_passes_a_limit_through_unchanged(
    client: HubClient, calls: list[tuple[str, str]]
) -> None:
    client.observe_recent(5)

    assert calls == [("GET", "/observe/recent?limit=5")]


def test_the_client_does_not_clamp(
    client: HubClient, calls: list[tuple[str, str]]
) -> None:
    """An absurd limit goes to the hub as asked, and the *hub* refuses it.

    Clamping here would look like defence and would be the opposite: it would apply
    only to callers using this client, and would hide from the hub's own tests that the
    ceiling is being relied upon.
    """
    client.observe_recent(10_000_000)

    assert calls == [("GET", "/observe/recent?limit=10000000")]


class TestTheHubWideStreamAddress:
    def test_it_carries_no_identity(self) -> None:
        """The route takes no caller, so the address must not name one."""
        client = HubClient(Config(hub="http://hub.invalid", name="jed_smith"))

        assert client.hub_events_url() == "http://hub.invalid/observe/events"
        assert "jed_smith" not in client.hub_events_url()

    def test_it_is_not_the_per_actor_stream(self) -> None:
        """The paired negative — the two must not collapse into one address."""
        client = HubClient(Config(hub="http://hub.invalid", name="jed_smith"))

        assert client.hub_events_url() != client.events_url()
        assert "jed_smith" in client.events_url()

    def test_it_is_derived_from_the_configured_hub(self) -> None:
        client = HubClient(Config(hub="http://elsewhere.invalid", name="jed_smith"))

        assert client.hub_events_url().startswith("http://elsewhere.invalid")

    def test_holding_it_uses_the_same_credential_as_every_other_call(self) -> None:
        """Duplicated auth is how a stream works on an open hub and is refused on a
        closed one, months after the change that caused it."""
        client = HubClient(
            Config(hub="http://hub.invalid", name="jed_smith", token="secret-xyz")
        )

        headers = client.stream_headers()

        assert headers["Authorization"] == "Bearer secret-xyz"
        assert headers["Accept"] == "text/event-stream"
