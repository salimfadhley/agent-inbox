"""A human posts to a thread, and to one message in it — as themselves.

**Almost nothing here is new code, and that is the finding.** `outbox` already accepts
`inReplyTo` and routes it through `House.reply`; the console already acts as the
signed-in operator rather than as itself. What was missing was the human: before the
namespace merge there was no actor to attribute a message to, so a human's own outbox
had no mailbox behind it. WP01 supplied one and this became possible without a route.

So this package is proof and negatives. The negatives are the part that would otherwise
rot: **a human never sends as an agent** (C-002), and the console decides nothing about
any of it (NFR-002, ADR 0005).
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from litestar.testing import TestClient

from agent_inbox import merge
from agent_inbox.api import IDENTITY_HEADER, SESSION_COOKIE, build_api
from agent_inbox.auth import secrets, totp
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"
AGENT = "rosemary_nasrin"
HUMAN = "admin"  # the signed-in operator *is* this mailbox — the point of WP01


@pytest.fixture
async def hub() -> AsyncIterator[tuple[TestClient, AuthService, InMemoryStore]]:
    store = InMemoryStore()
    auth = AuthService(InMemoryAuthStore(), secret_key=secrets.generate_key())
    house = House(Mailbox(store, hub_name="testhub"))
    app = build_api(house, HUB, auth=auth, auth_mode="enforce")
    with TestClient(app=app) as client:
        yield client, auth, store


async def sign_in(client: TestClient, auth: AuthService) -> str:
    """An enrolled operator, through the real flow, and their session cookie."""
    pw = await auth.bootstrap()
    client.post("/auth/login", json={"username": "admin", "password": pw})
    enrol = client.get("/auth/enrol").json()
    secret = enrol["provisioningUri"].split("secret=")[1].split("&")[0]
    client.post(
        "/auth/enrol",
        json={"password": "newpassword", "otp": totp.current_code(secret)},
    )
    return client.cookies.get(SESSION_COOKIE) or ""


async def a_human(auth: AuthService, store: InMemoryStore, name: str = HUMAN) -> None:
    """Make sure the signed-in operator has a mailbox.

    On a real hub the startup migration does this. Here the admin account is created by
    `bootstrap()` *after* the app has started, so the adoption is run explicitly — the
    same call, not a substitute for it.
    """
    del name
    await merge.adopt_existing(auth, store)


def as_human(client: TestClient, sid: str, name: str, note: dict[str, Any]) -> Any:
    return client.post(
        f"/actors/{name}/outbox", json=note, cookies={SESSION_COOKIE: sid}
    )


class TestAHumanCanPost:
    async def test_a_human_sends_a_message_attributed_to_them(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )

        sent = as_human(
            client,
            sid,
            HUMAN,
            {"type": "Note", "to": [AGENT], "content": "hello", "summary": "hi"},
        )

        assert sent.status_code == 201, sent.text
        assert sent.json()["attributedTo"].endswith(f"/{HUMAN}")

    async def test_it_arrives_in_the_agents_mailbox(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        """The paired positive for the whole class. Without it every assertion here
        could pass against a hub that accepted messages and delivered none."""
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )
        as_human(
            client, sid, HUMAN, {"type": "Note", "to": [AGENT], "content": "hello"}
        )

        mailbox = await Mailbox(store, hub_name="testhub").peek(AGENT)

        assert [note.attributed_to for note in mailbox] == [HUMAN]


class TestReplyingToOneMessageNests:
    async def test_a_reply_carries_in_reply_to(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )
        first = as_human(
            client, sid, HUMAN, {"type": "Note", "to": [AGENT], "content": "one"}
        ).json()

        second = as_human(
            client,
            sid,
            HUMAN,
            {"type": "Note", "content": "two", "inReplyTo": first["id"]},
        )

        assert second.status_code == 201, second.text
        assert second.json()["inReplyTo"] == first["id"]

    async def test_posting_to_the_thread_and_to_a_message_differ_only_there(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        """The distinction the whole of reddit-style nesting rests on. A route where
        both produced the same record would satisfy a careless test of either."""
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )
        root = as_human(
            client, sid, HUMAN, {"type": "Note", "to": [AGENT], "content": "one"}
        ).json()

        plain = as_human(
            client, sid, HUMAN, {"type": "Note", "to": [AGENT], "content": "flat"}
        ).json()
        nested = as_human(
            client,
            sid,
            HUMAN,
            {"type": "Note", "content": "deep", "inReplyTo": root["id"]},
        ).json()

        assert plain.get("inReplyTo") in (None, "")
        assert nested["inReplyTo"] == root["id"]


class TestAHumanNeverSendsAsAnAgent:
    """C-002, attacked rather than assumed. A constraint nobody tried to break is a
    constraint nobody tested."""

    async def test_a_human_cannot_post_from_an_agents_outbox(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )

        stolen = as_human(
            client,
            sid,
            AGENT,  # the agent's mailbox, with the human's session
            {"type": "Note", "to": [HUMAN], "content": "not me"},
        )

        assert stolen.status_code >= 400, (
            "a human sent as an agent — impersonation, the exact thing the observe "
            "routes were built to remove"
        )

    async def test_an_identity_header_cannot_override_the_session(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        """The other way somebody would try it: claim a name in a header and hope the
        hub believes the claim rather than the credential."""
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )

        answer = client.post(
            f"/actors/{AGENT}/outbox",
            json={"type": "Note", "to": [HUMAN], "content": "not me either"},
            cookies={SESSION_COOKIE: sid},
            headers={IDENTITY_HEADER: AGENT},
        )

        assert answer.status_code >= 400, "a header overrode the credential"


class TestReachingForEverybody:
    """Reported by the owner, 2026-08-05: addressing `*` gave *"nobody here is called
    '*'"* — correct, and no help at all.

    `*` is the actor a **shared token** shows as, so it appears in `doctor` output and
    on the tokens screen where it reads like a name. Guessing it is a reasonable thing
    to do, and there is exactly one right answer, so the refusal should say it.
    """

    @pytest.mark.parametrize("guess", ["*", "all", "any", "public", "everybody"])
    async def test_the_refusal_names_the_address_they_wanted(
        self, hub: tuple[TestClient, AuthService, InMemoryStore], guess: str
    ) -> None:
        from agent_inbox.exceptions import UnknownRecipient

        client, auth, store = hub
        await sign_in(client, auth)
        await a_human(auth, store)
        mailbox = Mailbox(store, hub_name="testhub")

        with pytest.raises(UnknownRecipient) as refused:
            await mailbox.send(HUMAN, [guess], "hello")

        assert "everyone" in str(refused.value), (
            f"a sender who guessed {guess!r} is left to guess again"
        )

    async def test_an_ordinary_typo_is_not_given_that_advice(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        """The paired negative. Suggesting a broadcast to somebody who mistyped one
        agent's name would be worse than saying nothing — a broadcast costs every
        recipient a turn none of them can decline."""
        from agent_inbox.exceptions import UnknownRecipient

        client, auth, store = hub
        await sign_in(client, auth)
        await a_human(auth, store)
        mailbox = Mailbox(store, hub_name="testhub")

        with pytest.raises(UnknownRecipient) as refused:
            await mailbox.send(HUMAN, ["rosemary_nasrn"], "hello")

        assert "everyone" not in str(refused.value)

    async def test_everyone_itself_still_works(
        self, hub: tuple[TestClient, AuthService, InMemoryStore]
    ) -> None:
        """The paired positive: the advice must name something that actually works."""
        client, auth, store = hub
        sid = await sign_in(client, auth)
        await a_human(auth, store)
        client.post(
            "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
        )
        mailbox = Mailbox(store, hub_name="testhub")

        await mailbox.send(HUMAN, ["everyone"], "hello", subject="s")

        assert await mailbox.unread_count(AGENT) == 1
