"""A timeout is not an empty inbox (issue #31).

`nadia_harari`, running host-role monitoring and polling for mail over several hours,
saw ordinary 1–3 second checks occasionally take 20 seconds and once exceed 30 —
immediately followed by a successful retry with nothing else changed. What she could not
get was a clear signal from the server about what that meant, so a timeout was handled
by caller judgement: retry, skip the cycle, or **assume empty**.

Assume-empty is the one that must never happen, and it is the tempting one for a poller:
a mailbox that looks quiet is exactly what a quiet mailbox looks like. So the difference
has to be stated rather than left to be inferred from a missing number.

The measurement that changed the fix: the count itself is **4.3ms over 5000 messages**,
so it is not what made those polls slow. Making the probe cheaper would have been work
aimed at the wrong thing.
"""

from typing import Any

import pytest

from agent_inbox.client import ClientError, HubTimeout


class TestTheTwoStatesAreDistinguishable:
    async def test_a_timeout_says_the_count_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox import mcp_client

        class Slow:
            def check_inbox(self, **kw: Any) -> dict[str, Any]:
                raise HubTimeout("the mailbox at http://h did not answer within 10s.")

        _hub(monkeypatch, Slow())

        answer = await mcp_client.unread_count()

        assert answer["ok"] is False
        assert answer["count_unknown"] is True
        assert "unread" not in answer, "a failure must not carry a count of any kind"

    async def test_an_empty_inbox_carries_a_real_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The paired positive, and the whole point. Without it, a change that reported
        every poll as unknown would satisfy the test above and make the tool useless."""
        from agent_inbox import mcp_client

        class Quiet:
            def check_inbox(self, **kw: Any) -> dict[str, Any]:
                return {"unread": 0, "totalItems": 0, "cursor": "2026-08-07T00:00:00Z|"}

        _hub(monkeypatch, Quiet())

        answer = await mcp_client.unread_count()

        assert answer["unread"] == 0
        assert "count_unknown" not in answer
        assert answer.get("ok") is not False

    async def test_the_advice_forbids_the_tempting_mistake(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Naming the wrong move is the substance of the fix. An agent that reads
        "something went wrong" still has to decide what a poller does about it."""
        from agent_inbox import mcp_client

        class Slow:
            def check_inbox(self, **kw: Any) -> dict[str, Any]:
                raise HubTimeout("did not answer within 10s.")

        _hub(monkeypatch, Slow())

        advice = (await mcp_client.unread_count())["what_to_do"]

        assert "NOT an empty inbox" in advice
        assert "loop" in advice, "a poller needs to know retrying here is not free"


class TestATimeoutIsNotAnUnreachableHub:
    """They had the same advice, because it was chosen by matching the message text —
    and a timeout's text says "did not answer", which matched the unreachable branch.
    So the one case where asking again is right was told not to."""

    async def test_an_unreachable_hub_is_still_told_not_to_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_inbox import mcp_client

        class Gone:
            def check_inbox(self, **kw: Any) -> dict[str, Any]:
                raise ClientError("cannot reach the mailbox at http://h (refused).")

        _hub(monkeypatch, Gone())

        advice = (await mcp_client.unread_count())["what_to_do"]

        assert "do not retry in a loop" in advice

    async def test_a_timeout_is_not_given_that_advice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug, stated. `nadia_harari`'s 30-second timeout was followed immediately
        by a success, so "the hub is unreachable, nothing you send is arriving" was
        both wrong and discouraging the thing that worked."""
        from agent_inbox import mcp_client

        class Slow:
            def check_inbox(self, **kw: Any) -> dict[str, Any]:
                raise HubTimeout("the mailbox at http://h did not answer within 10s.")

        _hub(monkeypatch, Slow())

        advice = (await mcp_client.unread_count())["what_to_do"]

        assert "nothing you send is arriving" not in advice
        assert "asking again is reasonable" in advice

    def test_a_timeout_raises_the_specific_type(self) -> None:
        """The whole mechanism rests on the type, not on the words. If the client
        raised a bare `ClientError` again, every test above would still pass while the
        advice quietly reverted to the unreachable branch — so this asserts the raise
        itself, at the one place it happens."""
        import urllib.error
        import urllib.request

        from agent_inbox.client import Config, HubClient

        client = HubClient(Config(hub="http://hub.invalid:1", name="nadia_harari"))

        def _timeout(*a: Any, **kw: Any) -> Any:
            raise TimeoutError("too slow")

        original = urllib.request.urlopen
        urllib.request.urlopen = _timeout  # type: ignore[assignment]
        try:
            with pytest.raises(HubTimeout):
                client.ping()
        finally:
            urllib.request.urlopen = original  # type: ignore[assignment]


def _hub(monkeypatch: pytest.MonkeyPatch, hub: object) -> None:
    """Stand a fake hub behind the tools, with the session machinery stubbed out."""
    from agent_inbox import mcp_client

    async def _nothing() -> None:
        return None

    monkeypatch.setattr(mcp_client, "_client", lambda: hub)
    monkeypatch.setattr(mcp_client, "_resolve_project", _nothing)
    monkeypatch.setattr(mcp_client, "_start_listening", lambda: None)
