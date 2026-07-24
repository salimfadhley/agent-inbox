"""Live smoke tests against a running hub and console.

These do **not** use the in-process Litestar test client. They speak HTTP to a real hub
on a real port — the actual built image, started the way it is deployed — so they catch
the whole class of failure a unit test structurally cannot see:

- the image starts and the ASGI server actually serves;
- the routes are wired into the app that ships, not just into a `build_api()` call;
- the console container reaches the hub over the compose network and joined at startup;
- the compose topology (hub + console sidecar) works as a unit.

Every earlier live break was of exactly this shape — an ENTRYPOINT that swallowed the
subcommand, a sidecar that advertised the wrong address, a container created but never
started. None of them failed a unit test. These would have.

Skipped unless ``LIVE_HUB_URL`` is set, so an ordinary ``pytest`` run ignores them; CI's
smoke job launches the stack and points these at it. Deliberately stdlib-only (urllib),
so the module always imports and cleanly skips even without the client extras installed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

HUB = os.environ.get("LIVE_HUB_URL")
CONSOLE = os.environ.get("LIVE_CONSOLE_URL")

pytestmark = pytest.mark.skipif(
    not HUB, reason="set LIVE_HUB_URL to run the live smoke tests"
)

needs_console = pytest.mark.skipif(
    not CONSOLE, reason="set LIVE_CONSOLE_URL to run the console smoke tests"
)

TIMEOUT = 15


def _req(
    method: str,
    url: str,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, object]:
    """One request, returning ``(status, parsed-json-or-text)``. HTTP errors don't raise
    — a 4xx is data a smoke test wants to assert on, not an exception to catch."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            ctype = resp.headers.get_content_type()
            parsed = (
                json.loads(raw)
                if raw and ctype == "application/json"
                else raw.decode(errors="replace")
            )
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def _post_form(url: str, fields: dict[str, str]) -> int:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status


# -- the hub ---------------------------------------------------------------


def test_the_hub_describes_itself() -> None:
    status, body = _req("GET", f"{HUB}/")
    assert status == 200, body
    assert isinstance(body, dict)
    assert body["type"] == "Service"
    assert body["id"], "the hub must publish an id — the console pastes it into prompts"


def test_health_answers() -> None:
    status, _ = _req("GET", f"{HUB}/health")
    assert status == 200


def test_standing_residents_exist_before_anyone_joins() -> None:
    """admin and host are the whole point of the policy layer — they must be there."""
    status, body = _req("GET", f"{HUB}/actors")
    assert status == 200 and isinstance(body, dict)
    names = {a.get("preferredUsername") for a in body["items"]}
    assert {"admin", "host"} <= names


def test_join_send_and_observe_end_to_end() -> None:
    """The core loop over real HTTP: join, send to a standing resident, see it via the
    operator view — which takes no caller and must not consume it."""
    status, _ = _req("POST", f"{HUB}/actors", {"preferredUsername": "smoke_tester"})
    assert status in (201, 409), "join should create, or 409 if a prior run left it"

    note = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Create",
        "object": {
            "type": "Note",
            "to": ["admin"],
            "content": "live smoke test",
            "summary": "smoke",
        },
    }
    status, sent = _req(
        "POST",
        f"{HUB}/actors/smoke_tester/outbox",
        note,
        {"X-Agent-Name": "smoke_tester"},
    )
    assert status == 201, sent

    status, mbox = _req("GET", f"{HUB}/observe/mailbox/admin")
    assert status == 200 and isinstance(mbox, dict)
    assert any(n.get("summary") == "smoke" for n in mbox["items"]), (
        "the message admin was sent is not visible in the operator view"
    )

    status, stats = _req("GET", f"{HUB}/observe/stats")
    assert status == 200 and isinstance(stats, dict)
    assert stats["messages"] >= 1


def test_observing_does_not_consume() -> None:
    """The operator view must never mark an agent's mail read. Observe twice; the count
    of what is waiting for admin must not drop just because we looked."""
    _, first = _req("GET", f"{HUB}/observe/mailbox/admin")
    _, second = _req("GET", f"{HUB}/observe/mailbox/admin")
    assert isinstance(first, dict) and isinstance(second, dict)
    assert len(second["items"]) >= len(first["items"])


# -- the console (a client of the same hub) --------------------------------


@needs_console
def test_the_console_serves_and_warns() -> None:
    status, body = _req("GET", f"{CONSOLE}/")
    assert status == 200 and isinstance(body, str)
    assert "Overview" in body
    assert "does not authenticate" in body, "the unauthenticated warning must be shown"


@needs_console
def test_the_console_advertises_the_hub_in_its_prompt() -> None:
    """The prompt must carry the hub's public id, not the sidecar's internal route."""
    status, hub = _req("GET", f"{HUB}/")
    assert status == 200 and isinstance(hub, dict)
    status, prompt = _req("GET", f"{CONSOLE}/prompts.txt")
    assert status == 200 and isinstance(prompt, str)
    assert hub["id"] in prompt, "the console did not advertise the hub's published id"


@needs_console
def test_the_console_composes_as_itself() -> None:
    """The one thing the console does as a participant: send its own mail. Proves it
    joined at startup and can reach the hub."""
    assert (
        _post_form(
            f"{CONSOLE}/compose/send",
            {"to": "admin", "subject": "console smoke", "body": "from the console"},
        )
        == 200
    )
    status, mbox = _req("GET", f"{HUB}/observe/mailbox/admin")
    assert status == 200 and isinstance(mbox, dict)
    assert any(n.get("summary") == "console smoke" for n in mbox["items"])
