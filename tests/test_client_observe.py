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


class TestTheClientSaysWhatItIs:
    """The header must actually go out, not merely be defined.

    Written after a removal proof deleted the `add_header` call and **nothing failed**:
    every other test injected a client version into stub data rather than watching a
    real request carry one. A header nobody sends and no test misses is the same as no
    header at all.
    """

    def test_every_call_carries_the_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox.client import CLIENT_HEADER

        sent: dict[str, str] = {}

        class _Reply:
            headers = {"Content-Type": "application/json"}

            def read(self) -> bytes:
                return b"{}"

            def __enter__(self) -> "_Reply":  # noqa: UP037
                return self

            def __exit__(self, *_: object) -> None:
                return None

        def capture(request: object, timeout: float = 0) -> _Reply:
            sent.update(getattr(request, "headers", {}))
            return _Reply()

        monkeypatch.setattr("urllib.request.urlopen", capture)
        HubClient(Config(hub="http://hub.invalid", name="jed_smith")).hub_info()

        # urllib title-cases header names on the way in.
        carried = {key.lower(): value for key, value in sent.items()}
        assert carried.get(CLIENT_HEADER.lower()), "no client version was sent"

    def test_the_held_stream_carries_it_too(self) -> None:
        """The stream authenticates like every other call, and identifies itself alike.

        A version observed only on short requests would go quiet for exactly the agents
        holding a connection open — the ones being woken, which is the feature whose
        absence started this.
        """
        from agent_inbox.client import CLIENT_HEADER

        client = HubClient(Config(hub="http://hub.invalid", name="jed_smith"))

        assert client.stream_headers()[CLIENT_HEADER]


class TestTheHubSaysWhatItIsOnEveryAnswer:
    """Reported by `mariana_taphrale`, 2026-08-05.

    An MCP session learned the hub's version once, from `ping`, and then repeated it in
    every tool result for the rest of its life. The hub was upgraded twice underneath
    one such session, which went on telling its agent "this hub runs 0.58.0" while its
    own calls were being answered by 0.60.1.

    The bug is not the number being wrong. It is a **cached fact presented as an
    observation** — the failure this project keeps meeting, and the reason the fix is a
    header on every response rather than one more route that remembers to report it.
    """

    @staticmethod
    def _reply(headers: dict[str, str]) -> object:
        class _Reply:
            def __init__(self) -> None:
                self.headers = {"Content-Type": "application/json", **headers}

            def read(self) -> bytes:
                return b"{}"

            def __enter__(self) -> "_Reply":  # noqa: UP037
                return self

            def __exit__(self, *_: object) -> None:
                return None

        return _Reply()

    def test_an_ordinary_call_records_the_hub_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not `ping`. `check_inbox` is what a session actually spends its life doing,
        and before this it taught the client nothing about the hub."""
        from agent_inbox import staleness
        from agent_inbox.client import HUB_HEADER

        staleness.reset()
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda request, timeout=0: self._reply({HUB_HEADER: "999.0.0"}),
        )

        HubClient(Config(hub="http://hub.invalid", name="jed_smith")).check_inbox()

        assert staleness.notice(), "an ordinary call taught the client nothing"
        assert "999.0.0" in str(staleness.notice())
        staleness.reset()

    def test_a_later_answer_corrects_an_earlier_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The actual defect: not that the first observation was wrong, but that no
        second one could ever replace it. A hub upgraded mid-session must be
        believed."""
        from agent_inbox import staleness
        from agent_inbox.client import HUB_HEADER

        staleness.reset()
        client = HubClient(Config(hub="http://hub.invalid", name="jed_smith"))

        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda request, timeout=0: self._reply({HUB_HEADER: "999.0.0"}),
        )
        client.check_inbox()
        assert staleness.notice(), "the premise failed — nothing was recorded at all"

        # The hub is rolled back to something this client is not behind. The notice must
        # stop, rather than persisting because it was learned first.
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda request, timeout=0: self._reply({HUB_HEADER: "0.0.1"}),
        )
        client.check_inbox()

        assert staleness.notice() is None, (
            "a version learned once was never corrected — the reported bug"
        )
        staleness.reset()

    def test_an_answer_with_no_header_is_not_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The paired negative. An older hub sends nothing, and silence must not be read
        as a version — inventing one would make the notice confidently wrong."""
        from agent_inbox import staleness

        staleness.reset()
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda request, timeout=0: self._reply({})
        )

        HubClient(Config(hub="http://hub.invalid", name="jed_smith")).check_inbox()

        assert staleness.notice() is None
