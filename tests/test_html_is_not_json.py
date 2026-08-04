"""A console address given where the API address was meant.

The commonest misconfiguration there is, and until now it ended in thirty lines of
`JSONDecodeError` naming neither the url, nor what answered, nor what to do. It is worth
catching because of *who* hits it: the console is the address a human bookmarks and can
watch working in a browser, so it is the natural thing to paste.

Observed 2026-08-04 while repointing a client — `doctor` died rather than diagnosing,
which is the opposite of its job (#50).
"""

import json
from typing import Any

import pytest

from agent_inbox.client import ClientError, Config, HubClient

HUB = "https://hub.invalid"


class _Response:
    """Just enough of an HTTP response for `_call` to read."""

    def __init__(self, body: bytes, content_type: str) -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def client() -> HubClient:
    return HubClient(Config(hub=HUB, name="jed_smith"))


def answering(monkeypatch: pytest.MonkeyPatch, body: bytes, content_type: str) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _Response(body, content_type),
    )


def test_html_is_refused_with_a_sentence_not_a_traceback(
    client: HubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(monkeypatch, b"<!doctype html><title>Sign in</title>", "text/html")

    with pytest.raises(ClientError) as raised:
        client.hub_info()

    said = str(raised.value)
    assert "text/html" in said, "it does not say what answered"
    assert HUB in said, "it does not name the address"
    assert "console" in said, "it does not name the likeliest cause"
    assert "config list" in said, "it does not say what to do next"


def test_it_is_a_client_error_not_a_json_error(
    client: HubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every caller catches `ClientError`; a JSONDecodeError escapes all of them.

    Which is exactly how this became a traceback rather than a diagnosis.
    """
    answering(monkeypatch, b"<html></html>", "text/html")

    with pytest.raises(ClientError):
        client.hub_info()
    # And specifically not the raw decode error, which nothing catches.
    answering(monkeypatch, b"<html></html>", "text/html")
    try:
        client.hub_info()
    except json.JSONDecodeError:  # pragma: no cover - the regression
        pytest.fail("the raw JSONDecodeError escaped again")
    except ClientError:
        pass


def test_a_body_with_no_content_type_still_says_something_useful(
    client: HubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(monkeypatch, b"not json at all", "")

    with pytest.raises(ClientError, match="no content type"):
        client.hub_info()


def test_json_still_decodes(client: HubClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The paired positive. A guard that rejected everything would pass the tests above
    and break every working hub."""
    answering(monkeypatch, b'{"name": "testhub"}', "application/json")

    got: Any = client.hub_info()

    assert got == {"name": "testhub"}


def test_an_empty_body_is_still_none(
    client: HubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """204-shaped replies are ordinary and must not be read as a broken hub."""
    answering(monkeypatch, b"", "application/json")

    assert client.hub_info() is None
