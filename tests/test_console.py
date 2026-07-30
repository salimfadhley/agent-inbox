"""The human console.

Two things are worth testing here, and neither is the HTML:

1. The prompt page hands out **this** hub's address, because a placeholder is the thing
   a human gets wrong. A page that renders beautifully with `localhost` in the commands
   has failed at its only job.
2. The observatory screens read the hub *without impersonating anyone*. The old console
   viewed a mailbox by pretending to be its owner; these tests pin that it no longer
   does — it calls the `/observe/*` routes, which take no caller.

The hub is stubbed in-process so the pages render without a network. The stub records
which client methods were called, which is how the no-impersonation property is checked.
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from litestar.testing import TestClient

from agent_inbox import __version__
from agent_inbox.client import (
    CONFIG_NAME,
    SESSION_COOKIE,
    ClientError,
    Config,
    HubClient,
)
from agent_inbox.console import _freshness, build_console
from agent_inbox.prompts import MINIMUM_CLIENT

HUB = "http://mailbox.invalid:8081"


class StubHub(HubClient):
    """A hub that answers from memory and remembers what it was asked.

    Every method the console uses is stubbed so no request leaves the process. The
    ``calls`` list is the point of the fixture: a test can assert that viewing a
    mailbox went through ``observe_*`` and never through ``check_inbox`` as someone
    else — the impersonation the rewrite removed.
    """

    def __init__(self, hub: str = HUB, name: str = "console") -> None:
        super().__init__(Config(hub=hub, name=name))
        self.calls: list[str] = []
        self.tokens: list[dict[str, Any]] = []
        #: The trust list, which gates federation in both directions.
        self.peers: dict[str, str] = {}
        #: Humans who can sign in. All admins; `group` governs nothing.
        self.operators: list[dict[str, Any]] = [
            {
                "username": "admin",
                "email": "",
                "group": "admin",
                "state": "active",
            }
        ]
        #: Who the hub says a session belongs to, when a test wants one.
        self.operator: str | None = None
        self.acting: str | None = None
        self.purged = False
        #: Stored hub settings, and what the environment governs. The stub mirrors the
        #: real routes closely enough that the console's behaviour is what is tested,
        #: not the stub's.
        self.hub_settings: dict[str, str] = {}
        self.governed: dict[str, str] = {}
        self.purge_preview: dict[str, Any] = {
            "threads": [
                {
                    "root": f"{HUB}/objects/abc",
                    "subject": "DNS is still broken",
                    "lastPublished": "2026-07-01T09:00:00Z",
                    "messages": 4,
                    "ids": [f"{HUB}/objects/abc"],
                }
            ],
            "threadCount": 1,
            "messageCount": 4,
            "schedule": {
                "lastCycle": None,
                "cycles": 0,
                "lastRemovedThreads": 0,
                "lastRemovedObjects": 0,
                "lastError": None,
            },
        }

    def hub_info(self) -> dict[str, Any]:
        return {
            "id": HUB,
            "name": "testhub",
            "version": "1.2.3",
            "authenticated": False,
        }

    # The console derives a per-request client from these. The stub stays itself, so
    # its canned answers are used instead of a real socket.
    def with_session(self, session: str | None) -> HubClient:
        return self

    def acting_as(self, name: str, session: str | None = None) -> HubClient:
        self.acting = name
        return self

    def whoami(self) -> str | None:
        return self.operator

    def join(self, name: str | None = None) -> dict[str, Any]:
        self.calls.append("join")
        return {"preferredUsername": self.config.name}

    def list_agents(self) -> dict[str, Any]:
        self.calls.append("list_agents")
        return {
            "items": [
                {
                    "preferredUsername": "rosemary_nasrin",
                    "type": "Service",
                    "summary": "runs the deploys",
                    "profile": {"role": "agent", "project": "billing"},
                    "lastSeen": "2026-07-24T10:00:00Z",
                }
            ]
        }

    def whois(self, name: str) -> dict[str, Any]:
        self.calls.append(f"whois:{name}")
        return {"preferredUsername": name, "summary": "someone"}

    def survey(self, since: str = "") -> dict[str, Any]:
        self.calls.append("survey")
        return {
            "actors": 3,
            "messages": 2,
            "threads": 1,
            "per_day": [["2026-07-24", 2]],
            "flow": [["rosemary_nasrin", "trevor_mahmood", 2]],
            "busiest": [["rosemary_nasrin", 2]],
        }

    def observe_mailbox(self, name: str) -> dict[str, Any]:
        self.calls.append(f"observe_mailbox:{name}")
        return {
            "items": [
                {
                    "id": f"{HUB}/objects/abc123",
                    "attributedTo": f"{HUB}/actors/rosemary_nasrin",
                    "summary": "flaky tests",
                    "content": "one run in five",
                    "published": "2026-07-24T10:00:00Z",
                }
            ]
        }

    def observe_object(self, object_id: str) -> dict[str, Any]:
        self.calls.append(f"observe_object:{object_id}")
        return {
            "id": f"{HUB}/objects/abc123",
            "attributedTo": f"{HUB}/actors/rosemary_nasrin",
            "summary": "flaky tests",
            "content": "one run in five",
            "published": "2026-07-24T10:00:00Z",
            "readBy": ["trevor_mahmood"],
        }

    def observe_thread(self, object_id: str) -> dict[str, Any]:
        self.calls.append(f"observe_thread:{object_id}")
        return self.observe_mailbox("x")

    def check_inbox(self) -> dict[str, Any]:
        self.calls.append("check_inbox")
        return {"items": []}

    def send_message(self, to: Any, body: str, subject: Any = None, **kw: Any) -> dict:
        self.calls.append(f"send:{to}")
        return {"id": f"{HUB}/objects/new"}

    def read_message(self, object_id: str) -> dict[str, Any]:
        self.calls.append(f"read:{object_id}")
        return {}

    def _resolved_settings(self) -> dict[str, Any]:
        import hashlib

        out: dict[str, Any] = {}
        for key in ("name", "title", "description"):
            if key in self.governed:
                out[key] = {
                    "value": self.governed[key],
                    "source": "environment",
                    "variable": f"AGENT_INBOX_HUB_{key.upper()}",
                }
            elif key in self.hub_settings:
                out[key] = {"value": self.hub_settings[key], "source": "stored"}
            else:
                out[key] = {
                    "value": "console" if key == "name" else None,
                    "source": "default",
                }
        material = "|".join(
            f"{k}={out[k]['value']!r}:{out[k]['source']}" for k in sorted(out)
        )
        out["version"] = hashlib.sha256(material.encode()).hexdigest()[:16]
        return out

    def _write_settings(self, body: dict[str, Any]) -> tuple[int, Any, None]:
        current = self._resolved_settings()
        seen = body.get("version")
        if seen is not None and seen != current["version"]:
            return 409, {"detail": "these settings changed since you read them"}, None
        for key, value in body.items():
            if key == "version":
                continue
            if key not in ("name", "title", "description"):
                return 400, {"detail": f"not a hub setting: {key}"}, None
            if key in self.governed:
                return (
                    409,
                    {"detail": f"{key} is set by AGENT_INBOX_HUB_{key.upper()}"},
                    None,
                )
            if key == "name" and value and not value.islower():
                return (
                    422,
                    {"detail": f"{value!r} is not a usable hub name, e.g. 'saltclub'"},
                    None,
                )
            self.hub_settings[key] = str(value)
        return 200, self._resolved_settings(), None

    def auth_call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        session: str | None = None,
    ) -> tuple[int, Any, str | None]:
        self.calls.append(f"auth:{method}:{path}:{'sid' if session else 'nosid'}")
        if path == "/hub/settings" and method == "GET":
            return 200, self._resolved_settings(), None
        if path == "/hub" and method == "PUT":
            return self._write_settings(body or {})
        if path == "/observe/purge":
            if method == "GET":
                return 200, dict(self.purge_preview), None
            removed = self.purge_preview["messageCount"]
            self.purged = True
            answer = {**self.purge_preview, "removed": removed}
            self.purge_preview = {"threads": [], "threadCount": 0, "messageCount": 0}
            return 200, answer, None
        if path == "/auth/login":
            nxt = "enrol" if body and body.get("username") == "admin" else "ok"
            return 200, {"next": nxt}, f"{SESSION_COOKIE}=sess-xyz; HttpOnly; Path=/"
        if path == "/auth/enrol" and method == "GET":
            return (
                200,
                {
                    "provisioningUri": "otpauth://totp/x",
                    "qrSvg": "<svg>qr</svg>",
                    "recoveryCodes": ["r1", "r2"],
                },
                None,
            )
        if path == "/auth/enrol" and method == "POST":
            return 200, {"next": "ok"}, f"{SESSION_COOKIE}=full-sess; HttpOnly; Path=/"
        if path == "/auth/logout":
            return 200, {"next": "ok"}, None
        if path == "/auth/change-password":
            return 200, {"next": "ok"}, None
        # Device tokens: operator-only on the hub, so the stub refuses without a
        # session exactly as the hub does — that is the property the console must
        # relay rather than decide for itself.
        if path.endswith("/tokens") and method == "GET":
            if not session:
                return 401, {"detail": "log in as an operator"}, None
            return 200, {"items": list(self.tokens)}, None
        if path.endswith("/tokens") and method == "POST":
            if not session:
                return 401, {"detail": "log in as an operator"}, None
            minted = {
                "id": "tok1",
                "token": "secret-shown-once",
                "actor": path.split("/")[-2],
            }
            self.tokens.append(
                {"id": "tok1", "label": (body or {}).get("label", ""), "created": ""}
            )
            return 201, minted, None
        if "/tokens/" in path and method == "DELETE":
            if not session:
                return 401, {"detail": "log in as an operator"}, None
            for t in self.tokens:
                t["revoked"] = True
            return 204, None, None
        # The trust list. Operator-gated on the real hub; the stub refuses without
        # a session for the same reason the token routes do — the console must relay
        # that refusal rather than decide for itself.
        if path.startswith("/operators"):
            if method == "GET":
                return (
                    200,
                    {"operators": self.operators, "groups_enforced": False},
                    None,
                )
            if method == "POST":
                name = str((body or {}).get("username", "")).strip().lower()
                if not name:
                    return 422, {"detail": "an operator needs a username"}, None
                if any(o["username"] == name for o in self.operators):
                    return 409, {"detail": f"{name!r} is already an operator"}, None
                self.operators.append(
                    {
                        "username": name,
                        "email": str((body or {}).get("email", "")),
                        "group": str((body or {}).get("group", "admin")),
                        "state": "must_change_and_enrol",
                    }
                )
                return 200, {"username": name, "password": "one-time-secret"}, None
            if method == "DELETE":
                name = path.rsplit("/", 1)[-1]
                if len(self.operators) <= 1:
                    return 409, {"detail": "that is the only operator"}, None
                before = len(self.operators)
                self.operators = [o for o in self.operators if o["username"] != name]
                if len(self.operators) == before:
                    return 404, {"detail": "no such operator"}, None
                return 200, {"username": name, "removed": True}, None
        if path.startswith("/observe/peers"):
            if method == "GET":
                return (
                    200,
                    {
                        "peers": [
                            {"origin": origin, "added": added}
                            for origin, added in sorted(self.peers.items())
                        ]
                    },
                    None,
                )
            if method == "POST":
                origin = str((body or {}).get("origin", "")).strip()
                if not origin.startswith(("http://", "https://")) or " " in origin:
                    return 422, {"detail": f"{origin!r} is not a hub address"}, None
                self.peers[origin.rstrip("/")] = "2026-07-30"
                return 200, {"origin": origin.rstrip("/"), "trusted": True}, None
            if method == "DELETE":
                origin = path.partition("origin=")[2]
                self.peers.pop(origin.rstrip("/"), None)
                return 200, {"origin": origin, "trusted": False}, None
        return 404, {"detail": "no"}, None


def make(stub: StubHub | None = None) -> tuple[TestClient, StubHub]:
    hub = stub or StubHub()
    return TestClient(app=build_console(hub)), hub


@pytest.fixture
def console() -> Iterator[TestClient]:
    client, _ = make()
    with client as c:
        yield c


# -- device tokens ---------------------------------------------------------


def test_minting_a_token_requires_an_operator_session(console: TestClient) -> None:
    """The console decides nothing here — it relays and reports what the hub says.

    Minting is an operator action behind a human login. The console must not invent
    its own answer, in either direction: no session means the hub's refusal is shown
    and the reader is sent to sign in.
    """
    got = console.get("/tokens/rosemary_nasrin")
    assert got.status_code == 200
    assert "operator action" in got.text
    assert "/login" in got.text


def test_a_minted_token_is_shown_once_with_what_to_do_with_it(
    console: TestClient,
) -> None:
    """The hub stores only a hash, so this page is the single chance to read it.

    Anything the agent needs must therefore be here and pasteable — the command that
    installs it, not a description of the file it goes in.
    """
    console.cookies.set(SESSION_COOKIE, "sess-xyz")
    got = console.post("/tokens/rosemary_nasrin/mint", data={"label": "laptop"})
    assert got.status_code == 200
    assert "secret-shown-once" in got.text
    assert "only time it can be read" in got.text
    assert "agent-inbox join rosemary_nasrin --token secret-shown-once" in got.text
    # and it now appears in the list, so the page reflects the mint that just happened
    assert "laptop" in got.text


def test_a_token_can_be_revoked_from_the_same_page(console: TestClient) -> None:
    """A token you cannot revoke is worse than no token — this is the whole point."""
    console.cookies.set(SESSION_COOKIE, "sess-xyz")
    console.post("/tokens/rosemary_nasrin/mint", data={"label": "laptop"})
    got = console.post("/tokens/rosemary_nasrin/revoke", data={"id": "tok1"})
    assert got.status_code == 200
    assert "Revoked" in got.text
    assert "locked out" in got.text


def test_the_agents_table_links_to_each_agent_s_tokens(console: TestClient) -> None:
    """Discoverability: the feature existed in the API and nowhere a human could see."""
    assert "/tokens/rosemary_nasrin" in console.get("/agents").text


# -- the prompt ------------------------------------------------------------


def test_the_prompt_names_this_hub_not_a_placeholder(console: TestClient) -> None:
    """The address in the pasted text is the one the console is actually talking to."""
    body = console.get("/prompts").text
    assert HUB in body
    assert "&lt;host&gt;" not in body and "localhost" not in body


def test_the_prompt_advertises_the_hub_not_the_sidecar_route_to_it() -> None:
    """The sidecar trap: the console reaches the hub by a name no agent can use.

    Over a container network the console talks to `http://agent-mailbox:8080`. Pasting
    that into a prompt sends an agent nowhere. The hub's published `id` is the address
    it claims as its own, and that is the one a reader needs.
    """
    client, _ = make(StubHub(hub="http://agent-mailbox:8080", name="c"))
    with client as c:
        text = c.get("/prompts.txt").text
    assert HUB in text
    assert "agent-mailbox:8080" not in text


def test_the_plain_text_form_is_the_same_prompt(console: TestClient) -> None:
    """`/prompts.txt` exists so it can be curled; it must not drift from the page."""
    page = console.get("/prompts")
    text = console.get("/prompts.txt")
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    assert "uv tool install" in text.text
    assert "uv tool install" in page.text


def test_every_page_footer_names_both_versions(console: TestClient) -> None:
    """Console and hub are separate deployments and can differ — say which is which.

    "What are we actually running?" gets asked when something looks wrong, which is
    the worst moment to go and inspect containers. The console's own version is its
    `__version__`; the hub's is what the hub reports, so a rolling upgrade that has
    moved one and not the other is visible on the page.
    """
    body = console.get("/").text
    assert f"console <code>{__version__}</code>" in body
    assert "hub <code>1.2.3</code>" in body


def test_the_footer_does_not_pass_our_version_off_as_the_hubs(
    console: TestClient,
) -> None:
    """An unreachable hub says so. Showing our number for both would be a lie."""

    class DeadHub(StubHub):
        def hub_info(self) -> dict[str, Any]:
            raise ClientError("hub is down")

    client, _ = make(DeadHub())
    with client as c:
        body = c.get("/").text
    assert "hub <code>unreachable</code>" in body
    assert f"console <code>{__version__}</code>" in body


def test_the_console_reports_its_own_health_without_asking_the_hub(
    console: TestClient,
) -> None:
    """The container healthcheck's target, and it must not depend on the hub.

    The image's check hits `/health` on whichever port the process listens on. The
    console had no such route at all, so its container sat `unhealthy` for its whole
    life while serving pages perfectly. It must also answer while the hub is down —
    otherwise an outage the console cannot fix gets it restarted in a loop.
    """

    class DeadHub(StubHub):
        def hub_info(self) -> dict[str, Any]:
            raise ClientError("hub is down")

    got = console.get("/health")
    assert got.status_code == 200
    assert got.json() == {"status": "ok"}

    client, stub = make(DeadHub())
    with client as c:
        assert c.get("/health").status_code == 200
    assert "hub_info" not in stub.calls


def test_the_prompt_makes_the_reader_check_what_is_already_installed(
    console: TestClient,
) -> None:
    """An agent arriving with an old copy is the case the check exists for.

    It connects and answers, and is merely missing whatever the hub gained since — a
    failure that looks like an absent tool rather than an error. So the prompt names
    the command *and* the number to compare against, and the number is the hub's, not
    one written into the text by hand.
    """
    text = console.get("/prompts/agent").text
    assert "agent-inbox --version" in text
    assert "1.2.3" in text, "the reader should still be told what the hub is running"
    # --force because a plain install is a no-op when the tool is there; --refresh
    # because a hub is upgraded before its agents, so this is usually run in the window
    # where a cached index still lists only the previous release.
    assert "uv tool install --refresh --no-cache --force" in text
    # Pinned to the floor, so a resolver that cannot reach it fails loudly instead of
    # silently installing 0.10.2 — the superseded package, with different commands.
    #
    # The floor is MINIMUM_CLIENT, deliberately *not* the hub's own version. Pinning to
    # the newest release made every release briefly unsatisfiable, because PyPI's
    # install index trails a publish by minutes — three agents hit that window.
    assert f'"agent-inbox[clients]>={MINIMUM_CLIENT}"' in text
    assert "clients]>=1.2.3" not in text


def test_an_unreachable_hub_does_not_invent_a_version_to_compare_against(
    console: TestClient,
) -> None:
    """No hub, no number. The step falls back to installing unconditionally.

    Quoting the console's own version here would be the sidecar trap again: separate
    containers, and a rolling upgrade moves one before the other. Better to ask for an
    install that is always safe than to publish a floor nobody stands behind.
    """

    class DeadHub(StubHub):
        def hub_info(self) -> dict[str, Any]:
            raise ClientError("hub is down")

    client, _ = make(DeadHub())
    with client as c:
        text = c.get("/prompts/agent").text
    assert "uv tool install" in text
    assert "--version" not in text
    assert "older than" not in text


def test_there_is_exactly_one_prompt(console: TestClient) -> None:
    """No per-role prompts. Three drifted apart last time; one cannot.

    The page now links `/prompts/agent`, so "no role appears in the HTML" is no
    longer the property to pin — it never was the real one. What must hold is that
    the role names cannot address *different documents*, which is what drifted
    before. Byte-identical responses are a stronger guarantee than an absent link.
    """
    got = {r: console.get(f"/prompts/{r}") for r in ("agent", "host", "admin")}
    # assert they resolve before comparing: three identical 404s would otherwise
    # satisfy "all the same" and pin nothing at all
    assert all(r.status_code == 200 for r in got.values())
    assert len({r.text for r in got.values()}) == 1, "roles served different prompts"
    assert CONFIG_NAME in console.get("/prompts").text


def test_the_full_prompt_is_plain_text_at_a_role_url(console: TestClient) -> None:
    """`/prompts/agent` is the address pasted into agents, so it must be readable."""
    got = console.get("/prompts/agent")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("text/plain")
    assert "uv tool install" in got.text
    assert got.text == console.get("/prompts.txt").text


def test_the_pasted_prompt_sends_the_agent_back_for_the_real_one(
    console: TestClient,
) -> None:
    """The copy box holds the short note, not the prompt itself.

    Pasting the full text freezes it at the version it was copied on. The whole
    change is that what gets pasted is the *address*, which does not go stale.
    """
    body = console.get("/prompts").text
    assert "/prompts/agent" in body
    assert "every session" in body.lower()
    # the short note is what sits in the copy box, so the box must not be the
    # full prompt — `join(` appears in the full text and nowhere in the note
    box = body.split("<textarea id='prompt'")[1].split("</textarea>")[0]
    assert "curl -s" in box
    assert "join(" not in box


def test_the_pasted_prompt_points_at_this_console_not_the_hub(
    console: TestClient,
) -> None:
    """The prompt lives on the console's port, which is not the hub's.

    Reusing the hub's published address here would send agents to a port that does
    not serve the page — the sidecar trap, in the other direction.
    """
    box = (
        console.get("/prompts")
        .text.split("<textarea id='prompt'")[1]
        .split("</textarea>")[0]
    )
    assert "/prompts/agent" in box
    assert HUB not in box


def test_the_prompt_explains_the_config_file_it_writes(console: TestClient) -> None:
    """`join` writes a file into someone's repository; the prompt must say so.

    Where it lands, what is in it, and that it must not be committed — the last
    matters most, because it carries a deployment's hostname and may carry a token.
    """
    text = console.get("/prompts/agent").text
    assert CONFIG_NAME in text
    assert "[agents." in text, "the per-engine table is not shown"
    assert ".gitignore" in text, "the prompt does not say to keep it out of git"


def test_the_prompt_tells_the_agent_to_fix_stale_instructions(
    console: TestClient,
) -> None:
    """Every project's AGENTS.md is where the last set of instructions went to rot.

    The prompt has to name the address to leave behind, or "replace it with a
    pointer" is advice the reader cannot act on.
    """
    text = console.get("/prompts/agent").text
    assert "AGENTS.md" in text and "CLAUDE.md" in text
    assert "/prompts/agent" in text, "no address to point the stale section at"


def test_the_prompt_says_the_hub_does_not_authenticate(console: TestClient) -> None:
    assert "does not authenticate" in console.get("/prompts.txt").text


def test_the_prompt_names_the_command_that_exists(console: TestClient) -> None:
    text = console.get("/prompts.txt").text
    # The subcommand form, under the project's own name. The hyphenated variants were
    # separate console scripts once and are not commands at all now.
    assert "agent-inbox mcp" in text
    assert "agent-mailbox-mcp" not in text
    assert "agent-inbox-mcp" not in text


# -- the observatory -------------------------------------------------------


def test_every_page_links_to_the_others(console: TestClient) -> None:
    body = console.get("/").text
    for href in ("/agents", "/inbox", "/compose", "/prompts"):
        assert f"'{href}'" in body or f'"{href}"' in body


def test_the_dashboard_shows_traffic(console: TestClient) -> None:
    body = console.get("/").text
    assert "messages" in body
    # the flow edge from the stub survey
    assert "rosemary_nasrin" in body and "trevor_mahmood" in body


def test_viewing_a_mailbox_observes_it_and_never_impersonates(
    console: TestClient,
) -> None:
    """The property the whole rewrite is for.

    Looking at trevor's mailbox must go through `observe_mailbox`, and must NOT call
    `check_inbox` as trevor — the old console did exactly that, and it worked only
    because nothing authenticates.
    """
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.get("/mailbox/trevor_mahmood")
    assert r.status_code == 200
    assert "observe_mailbox:trevor_mahmood" in hub.calls
    assert not any(call.startswith("check_inbox") for call in hub.calls), (
        "the console impersonated the agent instead of observing"
    )


def test_a_message_shows_the_whole_thread_and_who_read_it(
    console: TestClient,
) -> None:
    body = console.get("/message/abc123").text
    assert "flaky tests" in body
    assert "trevor_mahmood" in body  # from readBy


def test_the_inbox_is_the_consoles_own(console: TestClient) -> None:
    """The one place it acts as a participant — its own mail, via the agent route."""
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.get("/inbox")
    assert r.status_code == 200
    assert "check_inbox" in hub.calls


def test_composing_sends_as_the_console(console: TestClient) -> None:
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.post(
            "/compose/send",
            data={"to": "rosemary_nasrin", "subject": "hi", "body": "there"},
        )
    assert r.status_code == 200
    assert any(call.startswith("send:") for call in hub.calls)


def test_the_compose_form_renders(console: TestClient) -> None:
    """The GET form, not just the POST. A Litestar quirk 500s a sync GET when it shares
    an exact path with a sync POST; this pins that the form actually loads."""
    r = console.get("/compose")
    assert r.status_code == 200
    assert 'action="/compose/send"' in r.text


def test_compose_refuses_an_empty_message(console: TestClient) -> None:
    r = console.post("/compose/send", data={"to": "", "body": ""})
    assert r.status_code == 200
    assert "needs at least one recipient" in r.text


def test_the_console_claims_its_own_mailbox_at_startup() -> None:
    """Compose and inbox need somewhere to work, so the console joins on boot."""
    _, hub = make()
    with TestClient(app=build_console(hub)):
        pass
    assert "join" in hub.calls


# -- the auth UI (WP05) ----------------------------------------------------


def test_login_page_renders(console: TestClient) -> None:
    body = console.get("/login").text
    assert "Sign in" in body
    assert 'action="/login/submit"' in body


def test_login_relays_the_session_cookie_and_redirects() -> None:
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.post(
            "/login/submit",
            data={"username": "someone", "password": "pw", "otp": "123456"},
            follow_redirects=False,
        )
    # the console called the hub's login and relayed a Set-Cookie back to the browser
    assert any(call.startswith("auth:POST:/auth/login") for call in hub.calls)
    assert r.status_code in (301, 302, 303)
    assert SESSION_COOKIE in r.cookies


def test_bootstrap_login_sends_to_enrol() -> None:
    _, hub = make()
    with TestClient(app=build_console(hub)) as c:
        r = c.post(
            "/login/submit",
            data={"username": "admin", "password": "pw", "otp": ""},
            follow_redirects=False,
        )
    assert r.headers["location"] == "/account/enrol"


def test_enrol_page_shows_the_qr_and_recovery_codes() -> None:
    _, hub = make()
    with TestClient(app=build_console(hub), cookies={SESSION_COOKIE: "sess-xyz"}) as c:
        body = c.get("/account/enrol").text
    assert "<svg>qr</svg>" in body
    assert "r1" in body and "r2" in body
    assert 'action="/account/enrol/submit"' in body


def test_account_without_a_session_asks_to_sign_in(console: TestClient) -> None:
    body = console.get("/account").text
    assert "not signed in" in body.lower()


def test_the_console_holds_no_password() -> None:
    """The console relays credentials; it must never store one. A crude but real check:
    the module source contains no password constant or field."""
    import agent_inbox.console as con

    src = con.__file__
    text = open(src).read()  # noqa: SIM115, PTH123 - a test reading its own source
    assert "password_hash" not in text  # no hashing here — that is the hub's job


# -- the flow graph (client-side, vendored, same-origin) -------------------


def test_graph_page_renders_a_container_and_loads_the_vendored_lib(
    console: TestClient,
) -> None:
    body = console.get("/graph").text
    assert 'id="graph"' in body
    # the library is loaded same-origin, never from a CDN
    assert '<script src="/static/vis-network.min.js">' in body
    assert "cdn" not in body.lower()
    # the data is a non-executable JSON island the same-origin console.js reads
    assert 'type="application/json" id="graph-data"' in body


def test_graph_data_carries_the_flow_edges(console: TestClient) -> None:
    body = console.get("/graph").text
    # the stub survey has a rosemary→trevor edge
    assert "rosemary_nasrin" in body and "trevor_mahmood" in body


def test_static_assets_are_served_same_origin(console: TestClient) -> None:
    r = console.get("/static/vis-network.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert console.get("/static/console.js").status_code == 200


def test_static_route_will_not_serve_arbitrary_files(console: TestClient) -> None:
    assert console.get("/static/secrets.py").status_code == 404
    assert console.get("/static/../serve.py").status_code in (400, 404)


def test_every_page_carries_a_strict_csp(console: TestClient) -> None:
    csp = console.get("/graph").headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    # scripts must NOT be allowed inline — that is the whole point of moving them out
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "default-src 'self'" in csp


def test_no_page_ships_an_inline_executable_script(console: TestClient) -> None:
    """Under script-src 'self' an inline <script>code</script> would silently not run.
    Every page's JS must come from /static, so no bare inline script may remain."""
    for path in ("/", "/graph", "/prompts", "/login"):
        body = console.get(path).text
        # allowed: <script src=...> and <script type="application/json">
        # forbidden: a bare <script> with code
        assert "<script>" not in body, f"{path} has an inline executable script"


def test_tokens_are_reachable_from_the_navigation(console: TestClient) -> None:
    """The capability existed twice over and could still not be found.

    First only in the API, then only behind an unlabelled last column of the agent
    directory. Something nobody can find is indistinguishable from something that was
    never built, so the way in is now a nav entry like every other section.
    """
    assert "href='/tokens'" in console.get("/").text
    index = console.get("/tokens")
    assert index.status_code == 200
    assert "/tokens/rosemary_nasrin" in index.text


def test_the_agent_directory_labels_its_token_column(console: TestClient) -> None:
    """A blank header is why the existing link went unnoticed."""
    assert "Keys" in console.get("/agents").text


def test_a_hub_that_wants_a_login_sends_you_to_the_login(console: TestClient) -> None:
    """On an enforcing hub every page fails this way until someone signs in.

    Meeting a first-time operator with a 502 about their own hub would be absurd, so
    the one failure that means "who are you?" opens the door instead of reporting a
    fault. Matched on the API's stable error code, not on prose.
    """

    class Refusing(StubHub):
        def survey(self, since: str = "") -> dict[str, Any]:
            raise ClientError("this hub requires authentication [not_authenticated]")

    client, _ = make(Refusing())
    with client as c:
        got = c.get("/", follow_redirects=False)
    assert got.status_code in (302, 303, 307)
    assert got.headers["location"].endswith("/login")


def test_a_hub_that_is_merely_broken_still_reports_the_fault(
    console: TestClient,
) -> None:
    """The redirect must not swallow real failures — that would hide an outage."""

    class Broken(StubHub):
        def survey(self, since: str = "") -> dict[str, Any]:
            raise ClientError("connection refused")

    client, _ = make(Broken())
    with client as c:
        got = c.get("/", follow_redirects=False)
    assert got.status_code == 502
    assert "connection refused" in got.text


# -- the gate ---------------------------------------------------------------


class AuthenticatingHub(StubHub):
    """A hub that reports it enforces authentication, like a real one under enforce."""

    def hub_info(self) -> dict[str, Any]:
        return {"id": HUB, "name": "testhub", "version": "1.2.3", "authenticated": True}


def test_every_console_page_needs_a_session_once_the_hub_authenticates() -> None:
    """Relying on the API to refuse was not enough.

    A page that happens not to call a guarded route still rendered — which is exactly
    how /tokens showed a stranger every agent on the hub while / was correctly
    redirecting. The gate is on the console itself, so it does not depend on which
    routes a given screen happens to touch.
    """
    client, _ = make(AuthenticatingHub())
    with client as c:
        for path in ("/", "/agents", "/tokens", "/graph", "/inbox", "/compose"):
            got = c.get(path, follow_redirects=False)
            assert got.status_code in (302, 303, 307), f"{path} rendered unguarded"
            assert got.headers["location"].endswith("/login"), path


def test_the_way_in_and_the_prompt_stay_open() -> None:
    """A gate that locks the door from the outside is not a gate.

    Sign-in, the health probe and the onboarding prompt are all needed *before* anyone
    can hold a session — the prompt especially, since it is how an agent is set up in
    the first place, and it holds nothing secret.
    """
    client, _ = make(AuthenticatingHub())
    with client as c:
        for path in ("/login", "/health", "/prompts", "/prompts/agent", "/prompts.txt"):
            assert c.get(path, follow_redirects=False).status_code == 200, path


def test_a_trusted_lan_is_not_asked_to_sign_in(console: TestClient) -> None:
    """Off and warn unchanged: the gate closes only when the hub enforces."""
    assert console.get("/", follow_redirects=False).status_code == 200


def test_the_first_run_hint_is_shown_only_while_setup_is_pending() -> None:
    """A hub in use for months should not still explain where its first password was.

    Beyond being noise, it reads as though the hub were less configured than it is —
    and it points at a log line that no longer exists.
    """

    class Fresh(StubHub):
        def hub_info(self) -> dict[str, Any]:
            return {**super().hub_info(), "setupRequired": True, "setupUser": "admin"}

    class SetUp(StubHub):
        def hub_info(self) -> dict[str, Any]:
            return {**super().hub_info(), "setupRequired": False}

    fresh, _ = make(Fresh())
    with fresh as c:
        assert "First run?" in c.get("/login").text
    done, _ = make(SetUp())
    with done as c:
        page = c.get("/login").text
        assert "First run?" not in page
        assert "start-up log" not in page


def test_a_signed_in_operator_observes_with_their_own_session() -> None:
    """The bug that read as "my login is rejected".

    Login succeeded, the console redirected to the overview, and the overview asked the
    hub for `/observe/stats` **as the console** — which under enforce holds no
    credential of its own. The hub said 401, the not-authenticated redirect sent the
    operator back to the login form they had just used successfully, and round it went.

    So the session must travel inward on observation calls. The console still holds no
    authority: it borrows the human's and the hub decides.
    """
    seen: list[str | None] = []

    class Watching(StubHub):
        def with_session(self, session: str | None) -> HubClient:
            # Record and stay ourselves, so the stubbed answers are still used.
            seen.append(session)
            return self

    client, _ = make(Watching())
    with client as c:
        c.cookies.set(SESSION_COOKIE, "sess-xyz")
        assert c.get("/").status_code == 200
    assert "sess-xyz" in seen, "the overview observed as nobody"


def test_a_signed_in_operator_is_not_bounced_to_a_login_they_already_passed() -> None:
    """The console's own pages act as the console, which holds no token under enforce.

    Refusing those must not send a signed-in operator back to sign in: they have, it
    worked, and doing so reads as a random logout while hiding what actually failed.
    """

    class RefusingInbox(StubHub):
        def check_inbox(self) -> dict[str, Any]:
            raise ClientError("requires authentication [not_authenticated]")

    client, _ = make(RefusingInbox())
    with client as c:
        c.cookies.set(SESSION_COOKIE, "sess-xyz")
        got = c.get("/inbox", follow_redirects=False)
        assert got.status_code == 502, "signed in: explain, do not redirect"
        assert "not_authenticated" in got.text
    # and with no session at all, the door still opens
    client2, _ = make(RefusingInbox())
    with client2 as c:
        got = c.get("/inbox", follow_redirects=False)
        assert got.status_code in (302, 303, 307)


def test_a_signed_in_operator_reads_their_own_mailbox_not_the_console_s() -> None:
    """Acting needs the operator's *name*, not just their session.

    The hub resolves a session to that human, and every mailbox route checks the path
    against the caller — so `/actors/console/inbox` carrying an admin's session is
    refused. Forwarding the session alone left Inbox and Compose broken on an
    authenticating hub; the console has to act as the person who is signed in.
    """
    stub = StubHub()
    stub.operator = "admin"
    client, _ = make(stub)
    with client as c:
        c.cookies.set(SESSION_COOKIE, "sess-xyz")
        page = c.get("/inbox")
    assert page.status_code == 200
    assert stub.acting == "admin", "acted as the console instead of the operator"


def test_with_no_session_the_console_still_acts_as_itself(console: TestClient) -> None:
    """On an open hub nothing changes — it is an ordinary agent that joined."""
    assert console.get("/inbox").status_code == 200


def test_the_page_says_what_application_it_is(console: TestClient) -> None:
    """A self-hosted hub answers to whatever the box is called.

    "examplehub" tells a browser tab, a history entry or a bookmark nothing about
    what the site is, so the application's own name goes in the title and in the
    documented `application-name` meta. Bitwarden will not read either — it names
    saved items after the hostname — but everything else does.
    """
    page = console.get("/login").text
    assert '<meta name="application-name" content="agent-inbox">' in page
    assert "<title>Sign in — agent-inbox (testhub)</title>" in page


def test_the_well_known_change_password_url_points_at_the_form(
    console: TestClient,
) -> None:
    """The one piece of password-manager integration that is a real standard.

    Safari since 2019 and Chrome since 86 probe for a 2xx/3xx here and offer to take
    the user to the form. It must answer before anyone signs in, or the probe sees the
    sign-in redirect instead of an answer.
    """
    got = console.get("/.well-known/change-password", follow_redirects=False)
    assert got.status_code in (302, 303, 307)
    assert got.headers["location"].endswith("/account")


def test_the_prompts_call_the_project_by_its_real_name(console: TestClient) -> None:
    """The opening line of both prompts is where a reader learns what this is.

    It said "agent-mailbox" — an informal name the project does not go by. The pasted
    note is the one piece of text that ends up in other people's repositories, so the
    wrong name there propagates furthest and lives longest.
    """
    for path in ("/prompts/agent", "/prompts"):
        text = console.get(path).text
        assert "**agent-inbox** lets you message them" in text
        assert "**agent-mailbox** lets" not in text


def test_the_prompt_names_the_real_config_filename(console: TestClient) -> None:
    """The prompt must name the file actually written, not a name for the project.

    Naming the wrong one sends agents looking for a file that is not there. This test
    used to assert the old filename for exactly that reason; the file was renamed in
    v0.25.0 and the prompt had not followed, so the test pinned the old truth. Its
    intent is unchanged — only the filename it guards.
    """
    text = console.get("/prompts/agent").text
    assert CONFIG_NAME in text, f"the prompt must name {CONFIG_NAME}"


def test_a_failed_install_routes_to_doctor_rather_than_reading_as_fatal(
    console: TestClient,
) -> None:
    """Reported by an agent that hit it: step 1 failed and it nearly stopped there.

    The hub and the package are released together but published by separate jobs, so
    for a few minutes after an upgrade the hub advertises a version the index has not
    caught up with. The prompt's own framing — that an old client is "missing whatever
    was added since" — primes a reader to distrust its client at exactly that moment,
    before `doctor` has told it anything. So the floor must read as advisory, and the
    failure must point at the check that actually knows.
    """
    # Newline-tolerant: the prompt is hard-wrapped, so phrases straddle lines.
    text = " ".join(console.get("/prompts/agent").text.split())
    assert "do not conclude your mail is broken" in text
    assert "Run `agent-inbox doctor`" in text.split("If the install fails")[1][:400]


class TestMaintenance:
    """The console's expiry page.

    Added because it was missing entirely: the handlers were written and never put in
    `route_handlers`, so `/maintenance` was a 404 on the live hub while every test
    passed. Nothing here covered console *routing*, only console rendering.
    """

    def test_the_page_exists(self, console: TestClient) -> None:
        assert console.get("/maintenance").status_code == 200

    def test_it_shows_what_would_go_before_offering_to_do_it(
        self, console: TestClient
    ) -> None:
        """The preview is the only chance to disagree: expiry leaves no tombstone."""
        page = console.get("/maintenance").text
        assert "DNS is still broken" in page, "the operator cannot see what would go"
        assert "4 message(s)" in page
        assert "no undo" in page

    def test_looking_removes_nothing(self, console: TestClient) -> None:
        client, hub = make()
        with client as c:
            c.get("/maintenance")
        assert hub.purged is False, "viewing the page purged the hub"
        assert any("GET:/observe/purge" in c for c in hub.calls)
        assert not any("POST:/observe/purge" in c for c in hub.calls)

    def test_purging_says_what_it_did_and_shows_what_is_left(self) -> None:
        client, hub = make()
        with client as c:
            page = c.post("/maintenance/purge").text
        assert hub.purged is True
        assert "Removed 4 message(s)" in page
        assert "DNS is still broken" not in page, (
            "the purged conversation was still listed as pending — "
            "a stale list beside 'removed' reads as a failure"
        )

    def test_the_nav_offers_it(self, console: TestClient) -> None:
        assert "/maintenance" in console.get("/").text


class TestTheMaintenanceHeartbeat:
    """The page must say when retention last actually ran, or that it has not.

    After the 0.18.1 starvation bug, "scheduled" in a startup log is not evidence the
    loop ever reached a cycle. An operator needs to see the difference without reading
    container logs.
    """

    def test_it_says_so_when_no_cycle_has_run(self, console: TestClient) -> None:
        page = console.get("/maintenance").text
        assert "No automatic check has completed yet" in page

    def test_it_shows_when_the_last_cycle_was(self) -> None:
        client, hub = make()
        hub.purge_preview["schedule"] = {
            "lastCycle": "2026-07-27T01:41:09+00:00",
            "cycles": 3,
            "lastRemovedThreads": 0,
            "lastRemovedObjects": 0,
            "lastError": None,
        }
        with client as c:
            page = c.get("/maintenance").text
        assert "2026-07-27 01:41:09" in page
        assert "3 so far" in page

    def test_a_failing_cycle_is_shown_not_swallowed(self) -> None:
        client, hub = make()
        hub.purge_preview["schedule"] = {
            "lastCycle": None,
            "cycles": 0,
            "lastRemovedThreads": 0,
            "lastRemovedObjects": 0,
            "lastError": "OperationalError: database is locked",
        }
        with client as c:
            page = c.get("/maintenance").text
        assert "database is locked" in page


class TestTheInsecureAdminBanner:
    """The console is where a human notices. It must not be reassuring by omission."""

    def _page(self, hub_extra: dict[str, Any]) -> str:
        from agent_inbox.console import _page

        hub = {"id": HUB, "name": "testhub", "version": "1.2.3", "authenticated": True}
        return _page("Overview", "<p>body</p>", {**hub, **hub_extra})

    def test_the_banner_appears_when_the_override_is_set(self) -> None:
        html_out = self._page({"adminPasswordSet": True})
        assert "Explicitly setting an admin password is insecure" in html_out
        assert "AGENT_MAILBOX_ADMIN_PASSWORD" in html_out
        assert "without a second factor" in html_out

    def test_no_banner_on_an_ordinary_hub(self) -> None:
        assert "insecure" not in self._page({"adminPasswordSet": False}).lower()

    def test_it_is_shown_alongside_the_unauthenticated_warning_not_instead(
        self,
    ) -> None:
        """Both facts or neither.

        A hub can be unauthenticated *and* have the override set. Showing only one
        banner would let the page tell a reassuring half-truth about the other.
        """
        html_out = self._page({"authenticated": False, "adminPasswordSet": True})
        assert "This hub does not authenticate" in html_out
        assert "Explicitly setting an admin password is insecure" in html_out


class TestTheOverviewShowsProject:
    """What an agent says it is working on, next to who and when.

    Self-declared and free-form, like the rest of a profile. Blank for the standing
    residents and for anyone who joined without describing themselves — on a real hub
    that is most of the roster, and it is not a fault.
    """

    def test_the_column_is_present(self, console: TestClient) -> None:
        body = console.get("/").text
        assert "<th>Project</th>" in body or ">Project<" in body

    def test_a_declared_project_is_shown(self, console: TestClient) -> None:
        assert "billing" in console.get("/").text

    def test_a_missing_project_is_a_dash_not_a_blank(self) -> None:
        """An empty cell reads as a rendering fault; a dash reads as 'not stated'."""

        class NoProfile(StubHub):
            def list_agents(self) -> dict[str, Any]:
                return {
                    "items": [
                        {
                            "preferredUsername": "bryan_hansson",
                            "type": "Service",
                            "profile": {},
                            "lastSeen": "2026-07-24T10:00:00Z",
                        }
                    ]
                }

        with TestClient(app=build_console(NoProfile())) as c:
            body = c.get("/").text
            assert "—" in body

    def test_a_long_project_is_clipped_but_kept_in_the_tooltip(self) -> None:
        """Real values run long: '5g_arg (Project DEVCON / ULEZ-DC)' is a live one."""
        long_name = "5g_arg (Project DEVCON / ULEZ-DC) and then some more words"

        class LongProject(StubHub):
            def list_agents(self) -> dict[str, Any]:
                return {
                    "items": [
                        {
                            "preferredUsername": "farhad_xia",
                            "type": "Service",
                            "profile": {"project": long_name},
                            "lastSeen": "2026-07-24T10:00:00Z",
                        }
                    ]
                }

        with TestClient(app=build_console(LongProject())) as c:
            body = c.get("/").text
            assert "…" in body, "a long project should be clipped"
            assert html.escape(long_name) in body, (
                "the full text belongs in the tooltip"
            )


class TestTheFreshnessDot:
    """Green within the hour, amber within the day, grey after.

    This replaced a comparison against a hardcoded date under a comment claiming a green
    dot meant "seen today". It meant "seen since a fixed date in the past", so every dot
    went green and stayed green, and grew more wrong every day it ran.
    """

    NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)

    def _state(self, seen: datetime) -> str:
        return _freshness(seen.isoformat(), self.NOW)[0]

    def test_within_the_hour_is_green(self) -> None:
        assert self._state(self.NOW - timedelta(minutes=59)) == ""

    def test_within_the_day_is_amber(self) -> None:
        assert self._state(self.NOW - timedelta(hours=2)) == "warm"
        assert self._state(self.NOW - timedelta(hours=23)) == "warm"

    def test_over_a_day_is_grey(self) -> None:
        assert self._state(self.NOW - timedelta(hours=25)) == "off"
        assert self._state(self.NOW - timedelta(days=40)) == "off"

    def test_the_boundaries_fall_the_stated_way(self) -> None:
        assert self._state(self.NOW - timedelta(hours=1)) == "warm", "1h is not green"
        assert self._state(self.NOW - timedelta(hours=24)) == "off", "24h is not amber"

    def test_a_missing_or_unparseable_time_is_grey_never_green(self) -> None:
        """A freshness check that fails must not look like freshness."""
        for junk in ("", "never", "2026-13-45T99:99", "yesterday"):
            assert _freshness(junk, self.NOW)[0] == "off"

    def test_a_naive_timestamp_is_read_as_utc_not_crashed_on(self) -> None:
        assert _freshness("2026-07-28T11:30:00", self.NOW)[0] == ""

    def test_the_old_hardcoded_behaviour_is_gone(self) -> None:
        """The bug, stated directly: a month-old sighting used to show green."""
        assert self._state(datetime(2026, 7, 24, 12, 0, tzinfo=UTC)) == "off"

    def test_every_state_carries_words_a_human_can_read(self) -> None:
        for delta in (timedelta(minutes=1), timedelta(hours=5), timedelta(days=3)):
            _, why = _freshness((self.NOW - delta).isoformat(), self.NOW)
            assert "seen" in why


class TestSettingsTab:
    """Step 1 and 1.1: a Settings container, whose first section is Federation."""

    def test_the_tab_is_in_the_navigation(self, console: TestClient) -> None:
        assert "href='/settings'" in console.get("/").text

    def test_it_shows_the_three_identity_fields(self, console: TestClient) -> None:
        page = console.get("/settings").text
        assert "Federation" in page
        for field in ("name", "title", "description"):
            assert f'name="{field}"' in page

    def test_it_no_longer_claims_federation_is_unbuilt(
        self, console: TestClient
    ) -> None:
        """It was true until step 6, and a page that keeps saying it now lies the other
        way — an operator would not look for the controls that are right there."""
        assert "not built yet" not in console.get("/settings").text

    def test_it_offers_the_trust_list(self, console: TestClient) -> None:
        """Peering is what actually switches federation on, so it must be reachable
        without a shell. Until this existed, `add_peer` had no caller outside the
        store."""
        page = console.get("/settings").text
        assert "Trusted hubs" in page
        assert "action='/settings/peers/add'" in page

    def test_an_empty_trust_list_says_why_nothing_works(
        self, console: TestClient
    ) -> None:
        """The normal starting state, and the reason federation appears broken. A bare
        "none" would leave the operator to guess."""
        page = console.get("/settings").text
        assert "neither send nor receive" in page or "no mail can cross" in page

    def test_it_says_trust_is_not_mutual(self, console: TestClient) -> None:
        """The mistake the two-hub tests made first: peering one side only, and the
        send failing correctly for a reason that reads like a bug."""
        assert "each hub must list the other" in console.get("/settings").text

    def test_a_peer_can_be_added_and_removed(self, console: TestClient) -> None:
        added = console.post(
            "/settings/peers/add", data={"origin": "https://beta.example"}
        )
        assert added.status_code == 200, added.text
        assert "beta.example" in console.get("/settings").text

        gone = console.post(
            "/settings/peers/remove", data={"origin": "https://beta.example"}
        )
        assert gone.status_code == 200, gone.text
        assert "beta.example" not in console.get("/settings").text

    def test_adding_a_peer_says_the_other_hub_must_reciprocate(
        self, console: TestClient
    ) -> None:
        """Told at the moment it matters, not only in the section blurb."""
        page = console.post(
            "/settings/peers/add", data={"origin": "https://gamma.example"}
        ).text
        assert "must trust this one too" in page

    def test_a_junk_origin_is_refused_in_words(self, console: TestClient) -> None:
        page = console.post("/settings/peers/add", data={"origin": "not a url"}).text
        assert "Not added" in page

    def test_saving_a_title_persists_it(self, console: TestClient) -> None:
        version = console.get("/settings").text.split('name="version" value="')[1][:16]
        r = console.post(
            "/settings/save", data={"title": "The Salt Club", "version": version}
        )
        assert r.status_code == 200, r.text
        assert "The Salt Club" in console.get("/settings").text

    def test_a_refusal_is_shown_not_swallowed(self, console: TestClient) -> None:
        version = console.get("/settings").text.split('name="version" value="')[1][:16]
        r = console.post(
            "/settings/save", data={"name": "Not A Name", "version": version}
        )
        assert "Not saved" in r.text
        assert "saltclub" in r.text, "the rule should be quoted back to the operator"

    def test_a_governed_field_is_shown_but_not_offered(self) -> None:
        """A greyed box with no explanation reads as broken; one naming the variable
        reads as governed. The variable comes from the hub, because a deployment may
        be configured through the legacy prefix and naming the wrong one sends the
        operator to edit something that is not in effect."""
        client, hub = make()
        hub.governed["name"] = "fixed-by-deployment"
        with client as c:
            page = c.get("/settings").text
            assert 'name="name" value="fixed-by-deployment" disabled' in page
            assert "AGENT_INBOX_HUB_NAME" in page

    def test_a_governed_field_cannot_be_written(self) -> None:
        client, hub = make()
        hub.governed["title"] = "Set By Deployment"
        with client as c:
            version = c.get("/settings").text.split('name="version" value="')[1][:16]
            r = c.post("/settings/save", data={"title": "Sneaky", "version": version})
            assert "Not saved" in r.text
            assert hub.hub_settings.get("title") is None

    def test_the_peer_check_reports_what_a_hub_says(self, console: TestClient) -> None:
        """And labels it as a claim rather than a finding."""
        r = console.post("/settings/peer", data={"url": "https://nothing.invalid"})
        assert r.status_code == 200
        assert "Could not read that hub" in r.text

    def test_the_peer_check_refuses_a_scheme_it_will_not_fetch(
        self, console: TestClient
    ) -> None:
        r = console.post("/settings/peer", data={"url": "file:///etc/passwd"})
        assert "Could not read that hub" in r.text
        assert "scheme" in r.text

    def test_a_peer_error_does_not_lose_the_settings_form(
        self, console: TestClient
    ) -> None:
        """A failed check must not strand the operator on a dead-end page."""
        r = console.post("/settings/peer", data={"url": "https://nothing.invalid"})
        assert 'action="/settings/save"' in r.text or "/settings/save" in r.text


class TestThePromptDoesNotOverpromise:
    """#17: the prompt advertised commands the floor does not guarantee.

    `ludmila_coe` hit this on 0.20.0 — the prompt offered `profile set` and said
    anything above 0.17.1 was fine. Both statements were true and the advice was
    unusable, which is the worst combination: nothing to notice.
    """

    def test_every_late_command_names_its_version(self) -> None:
        """A command added after the floor must say so where it is advertised.

        This is the test that would have caught #17, and it fails for any future
        command added to the map without a note beside it in the text.
        """
        from agent_inbox.prompts import COMMANDS_ADDED_AFTER_THE_FLOOR, onboarding

        text = onboarding("http://hub.invalid", version="9.9.9")
        for command, needed in COMMANDS_ADDED_AFTER_THE_FLOOR.items():
            assert command in text, f"{command!r} is mapped but never mentioned"
            assert needed in text, (
                f"the prompt advertises {command!r} without naming the version it "
                f"needs ({needed}) — an agent on an older client gets 'No such "
                f"command' and reads it as a broken install"
            )

    def test_the_floor_itself_did_not_move(self) -> None:
        """Raising it would lock out working clients to fix a documentation problem.

        The floor's own rule: move it when a row changes shape, not when a command is
        added. 0.17.1 still reads the current inbox format natively.
        """
        from agent_inbox.prompts import MINIMUM_CLIENT

        assert MINIMUM_CLIENT == "0.17.1"

    def test_the_prompt_says_the_floor_is_not_a_command_guarantee(self) -> None:
        from agent_inbox.prompts import onboarding

        text = onboarding("http://hub.invalid", version="9.9.9")
        assert "does not guarantee every command" in text


class TestUsersTab:
    """Adding and removing humans, and the group stub being visibly a stub."""

    def test_the_settings_page_lists_users(self, console: TestClient) -> None:
        page = console.get("/settings").text
        assert "<h3>Users</h3>" in page
        assert "admin" in page

    def test_it_says_every_user_is_an_admin(self, console: TestClient) -> None:
        """The owner's rule, stated where somebody adding a user will read it."""
        assert "Every user is an admin today" in console.get("/settings").text

    def test_it_says_groups_do_nothing(self, console: TestClient) -> None:
        """**The important one.** A permission-shaped field that is not a permission
        must say so, or an operator will demote a colleague and believe it took."""
        page = console.get("/settings").text
        assert "Groups do nothing yet" in page
        assert "do not rely on this to restrain anybody" in page

    def test_a_user_can_be_added(self, console: TestClient) -> None:
        page = console.post(
            "/settings/users/add",
            data={"username": "ludmila", "email": "l@example.com", "group": "user"},
        ).text
        assert "Added ludmila" in page
        assert "ludmila" in console.get("/settings").text

    def test_the_one_time_password_is_shown_once_and_labelled(
        self, console: TestClient
    ) -> None:
        """The hub sends no mail, so the inviter has to pass it on — and needs telling
        that nobody can look it up later."""
        page = console.post("/settings/users/add", data={"username": "ludmila"}).text
        assert "one-time-secret" in page
        assert "shown once" in page

    def test_a_duplicate_username_is_refused_in_words(
        self, console: TestClient
    ) -> None:
        console.post("/settings/users/add", data={"username": "ludmila"})
        page = console.post("/settings/users/add", data={"username": "ludmila"}).text
        assert "Not added" in page

    def test_a_user_can_be_removed(self, console: TestClient) -> None:
        console.post("/settings/users/add", data={"username": "ludmila"})
        page = console.post("/settings/users/remove", data={"username": "ludmila"}).text
        assert "Removed" in page
        # Checked on a *fresh* page: the confirmation names whoever was removed, so the
        # response body mentions them whether or not the removal actually took.
        assert "ludmila" not in console.get("/settings").text

    def test_the_last_user_cannot_be_removed(self, console: TestClient) -> None:
        """Arithmetic, not rank: the hub must keep a way in."""
        page = console.post("/settings/users/remove", data={"username": "admin"}).text
        assert "Not removed" in page

    def test_the_email_is_explained_as_future_recovery(
        self, console: TestClient
    ) -> None:
        assert "future recovery" in console.get("/settings").text
