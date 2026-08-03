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


def test_the_suite_knows_what_kind_of_hub_this_is(hub) -> None:
    """The premise every other assertion rests on (FR-001).

    Before this, the suite had no representation of the hub's posture at all, so the
    answer was hardcoded — and pointing it at an enforcing hub made most of it fail for
    reasons that had nothing to do with the deployment being broken.

    Asserting the descriptor is coherent rather than that it holds any particular value:
    the same run must pass against either kind of hub, which is the whole point.
    """
    assert hub.name, hub.assuming("the hub published no name")
    assert hub.version, hub.assuming("the hub published no version")
    assert hub.mode in ("open", "enforcing"), hub.assuming("unrecognised auth mode")


def test_the_hub_describes_itself() -> None:
    status, body = _req("GET", f"{HUB}/")
    assert status == 200, body
    assert isinstance(body, dict)
    assert body["type"] == "Service"
    assert body["id"], "the hub must publish an id — the console pastes it into prompts"


def test_health_answers() -> None:
    status, _ = _req("GET", f"{HUB}/health")
    assert status == 200


def test_standing_residents_exist_before_anyone_joins(hub) -> None:
    """admin and host are the whole point of the policy layer — they must be there.

    On an enforcing hub an anonymous read is refused, and that refusal *is* the correct
    behaviour. Asserting 200 unconditionally is what made this fail against production.
    """
    from conftest import anonymous_status, auth_headers

    status, body = _req("GET", f"{HUB}/actors", headers=auth_headers())
    expected = anonymous_status(hub.mode, 200) if not auth_headers() else 200
    assert status == expected, hub.assuming(f"GET /actors gave {status}")
    if status != 200:
        return  # refused, as this mode requires; there is nothing further to check
    assert isinstance(body, dict)
    names = {a.get("preferredUsername") for a in body["items"]}
    assert {"admin", "host"} <= names, hub.assuming("a standing resident is missing")


def test_join_send_and_observe_end_to_end(hub) -> None:
    """The core loop over real HTTP: join, send to a standing resident, see it via the
    operator view — which takes no caller and must not consume it.

    Needs a credential on an enforcing hub. Without one the loop is not merely expected
    to fail, it is *required* to — so the refusal is asserted rather than skipped.
    """
    from conftest import auth_headers

    head = auth_headers()
    status, _ = _req(
        "POST", f"{HUB}/actors", {"preferredUsername": "smoke_tester"}, head
    )
    if hub.mode == "enforcing" and not head:
        assert status == 401, hub.assuming(
            f"an anonymous join gave {status}; an enforcing hub must refuse it"
        )
        return
    assert status in (201, 409), hub.assuming("join should create, or 409 if it exists")

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
        {"X-Agent-Name": "smoke_tester", **head},
    )
    assert status == 201, sent

    status, mbox = _req("GET", f"{HUB}/observe/mailbox/admin", headers=head)
    assert status == 200 and isinstance(mbox, dict)
    assert any(n.get("summary") == "smoke" for n in mbox["items"]), (
        "the message admin was sent is not visible in the operator view"
    )

    status, stats = _req("GET", f"{HUB}/observe/stats", headers=head)
    assert status == 200 and isinstance(stats, dict)
    assert stats["messages"] >= 1


def test_observing_does_not_consume(hub) -> None:
    """The operator view must never mark an agent's mail read. Observe twice; the count
    of what is waiting for admin must not drop just because we looked."""
    from conftest import auth_headers

    head = auth_headers()
    code, first = _req("GET", f"{HUB}/observe/mailbox/admin", headers=head)
    if hub.mode == "enforcing" and not head:
        assert code == 401, hub.assuming(f"anonymous observe gave {code}")
        return
    _, second = _req("GET", f"{HUB}/observe/mailbox/admin", headers=head)
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


# -- auth (only when the hub is started with enforcement) ------------------

AUTH = os.environ.get("LIVE_AUTH")

#: **Two decorators, because `-k auth` used to select nothing.** None of the three
#: auth tests has "auth" in its name, so the obvious way to reach them deselected all
#: eleven — and an empty selection reads exactly like a pass. `-k` matches markers as
#: well as names, so the marker is what makes the obvious command work; it is registered
#: in `pyproject.toml` so it does not warn.
needs_auth = pytest.mark.skipif(
    not (HUB and AUTH),
    reason="set LIVE_AUTH=1 (and LIVE_HUB_URL) against an enforcing hub",
)
auth = pytest.mark.auth


@auth
def test_the_hub_does_what_it_advertises(hub) -> None:
    """FR-003, and **only one direction is a failure.**

    A hub that says `authenticated: true` while a protected route serves an anonymous
    caller is broken, and dangerously so — every operator reading the descriptor
    believes something untrue of it. The reverse is a hub merely stricter than it
    admits, which is safe, and asserting it would fail honest deployments.

    Needs no credential and no `LIVE_AUTH`: it is a question about the hub's honesty,
    which is worth asking of every hub the suite is ever pointed at.
    """
    if hub.mode != "enforcing":
        pytest.skip("only an enforcing hub can misreport enforcement")
    status, _ = _req("GET", f"{HUB}/observe/stats")
    assert status != 200, hub.assuming(
        "the hub advertises authentication but served /observe/stats anonymously"
    )


@needs_auth
@auth
def test_an_enforcing_hub_says_so() -> None:
    status, body = _req("GET", f"{HUB}/")
    assert status == 200 and isinstance(body, dict)
    assert body["authenticated"] is True


@needs_auth
@auth
def test_anonymous_write_is_refused_when_enforced() -> None:
    """No credential, a write route → 401. The point of enforcement, over real HTTP."""
    status, _ = _req("POST", f"{HUB}/actors", {"preferredUsername": "nobody_here"})
    assert status == 401


@needs_auth
@auth
def test_anonymous_observe_is_refused_when_enforced() -> None:
    status, _ = _req("GET", f"{HUB}/observe/stats")
    assert status == 401
