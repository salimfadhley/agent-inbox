"""A human has an inbox, and it is their actor's mailbox — not a second one.

The alternative is a thread where the human's words appear and their replies do not
arrive. This ships far smaller than it sounds because of the namespace merge: **a
human's inbox *is* their mailbox**, so there is no second store, no second delivery
path and no second unread model. If a `HumanInbox` had to be written, WP01 would have
failed at its job.

`test_human_posting.py` proves a human can speak; this proves they can be spoken to.
"""

from collections.abc import AsyncIterator

import pytest
from litestar.testing import TestClient

from agent_inbox import merge
from agent_inbox.api import SESSION_COOKIE, build_api
from agent_inbox.auth import secrets, totp
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"
AGENT = "rosemary_nasrin"
HUMAN = "admin"


@pytest.fixture
async def hub() -> AsyncIterator[
    tuple[TestClient, AuthService, InMemoryStore, Mailbox]
]:
    store = InMemoryStore()
    auth = AuthService(InMemoryAuthStore(), secret_key=secrets.generate_key())
    mailbox = Mailbox(store, hub_name="testhub")
    app = build_api(House(mailbox), HUB, auth=auth, auth_mode="enforce")
    with TestClient(app=app) as client:
        yield client, auth, store, mailbox


async def ready(client: TestClient, auth: AuthService, store: InMemoryStore) -> str:
    """An enrolled operator with a mailbox, and an agent to write to them."""
    pw = await auth.bootstrap()
    client.post("/auth/login", json={"username": HUMAN, "password": pw})
    enrol = client.get("/auth/enrol").json()
    secret = enrol["provisioningUri"].split("secret=")[1].split("&")[0]
    client.post(
        "/auth/enrol",
        json={"password": "newpassword", "otp": totp.current_code(secret)},
    )
    sid = client.cookies.get(SESSION_COOKIE) or ""
    await merge.adopt_existing(auth, store)
    client.post(
        "/actors", json={"preferredUsername": AGENT}, cookies={SESSION_COOKIE: sid}
    )
    return sid


class TestAnAgentCanWriteToAHuman:
    async def test_it_arrives(
        self, hub: tuple[TestClient, AuthService, InMemoryStore, Mailbox]
    ) -> None:
        """The premise for everything else here. Without it the unread tests could pass
        against an inbox nothing can reach — a check with nothing to look at."""
        client, auth, store, mailbox = hub
        await ready(client, auth, store)

        await mailbox.send(AGENT, [HUMAN], "are you there?", subject="a question")

        waiting = await mailbox.peek(HUMAN)
        assert [n.attributed_to for n in waiting] == [AGENT]

    async def test_the_human_sees_it_unread(
        self, hub: tuple[TestClient, AuthService, InMemoryStore, Mailbox]
    ) -> None:
        client, auth, store, mailbox = hub
        await ready(client, auth, store)
        await mailbox.send(AGENT, [HUMAN], "are you there?", subject="a question")

        assert await mailbox.unread_count(HUMAN) == 1

    async def test_reading_it_consumes_it_for_them_alone(
        self, hub: tuple[TestClient, AuthService, InMemoryStore, Mailbox]
    ) -> None:
        """A human gets exactly the model an agent has — no more and no less."""
        client, auth, store, mailbox = hub
        await ready(client, auth, store)
        await mailbox.send(AGENT, [HUMAN, AGENT], "to both", subject="s")
        note = (await mailbox.peek(HUMAN))[0]

        await mailbox.read(HUMAN, note.id)

        assert await mailbox.unread_count(HUMAN) == 0
        assert await mailbox.unread_count(AGENT) == 1, (
            "reading for the human consumed somebody else's copy"
        )


class TestLookingStillDoesNotConsume:
    """NFR-001, asserted *after* this change as well as before. This project has broken
    that boundary once already, by adding a caller where there was none."""

    async def test_observing_a_humans_mailbox_marks_nothing(
        self, hub: tuple[TestClient, AuthService, InMemoryStore, Mailbox]
    ) -> None:
        client, auth, store, mailbox = hub
        sid = await ready(client, auth, store)
        await mailbox.send(AGENT, [HUMAN], "unread please", subject="s")

        client.get(f"/observe/mailbox/{HUMAN}", cookies={SESSION_COOKIE: sid})

        assert await mailbox.unread_count(HUMAN) == 1, "looking consumed the message"

    async def test_observing_a_thread_marks_nothing_either(
        self, hub: tuple[TestClient, AuthService, InMemoryStore, Mailbox]
    ) -> None:
        client, auth, store, mailbox = hub
        sid = await ready(client, auth, store)
        await mailbox.send(AGENT, [HUMAN], "unread please", subject="s")
        note = (await mailbox.peek(HUMAN))[0]

        client.get(f"/observe/objects/{note.id}/thread", cookies={SESSION_COOKIE: sid})

        assert await mailbox.unread_count(HUMAN) == 1


class TestThereIsNoSecondInbox:
    def test_no_parallel_human_inbox_was_written(self) -> None:
        """The failure here is not a missing feature but a duplicated one that drifts.

        A human's inbox is their mailbox; the merge in WP01 is what made that true. If
        this ever fails, the right response is to delete the new thing rather than to
        update this test.
        """
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "src" / "agent_inbox"
        offenders = [
            path.name
            for path in source.rglob("*.py")
            for line in path.read_text().splitlines()
            if "class HumanInbox" in line or "def human_inbox" in line
        ]

        assert not offenders, f"a second inbox model appeared in {offenders}"


class TestTheConsoleShowsItToThem:
    """The wiring, proved apart from the question — for the third time today.

    Twice already a route existed and was never reached: the API prompt route, and the
    reply button that answered 404. Both times the tests around them passed. So the
    console half gets its own assertion rather than an assumption that `acting_for`
    is wired to the right client.
    """

    @staticmethod
    def _console(items: list[dict]) -> TestClient:
        from typing import Any

        from agent_inbox.client import Config, HubClient
        from agent_inbox.console import build_console

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub=HUB, name="console"))
                self.asked_as: list[str] = []

            def hub_info(self) -> dict[str, Any]:
                return {"name": "t", "version": "1.0.0", "authenticated": False}

            def with_session(self, session: str | None) -> Stub:
                return self

            def acting_as(self, name: str, session: str) -> Stub:
                self.asked_as.append(name)
                return self

            def whoami(self) -> str:
                return HUMAN

            def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
                return {"items": items, "unread": len(items), "cursor": ""}

        return TestClient(app=build_console(Stub()))

    def test_a_humans_mail_is_rendered(self) -> None:
        waiting = [
            {
                "id": f"{HUB}/objects/m1",
                "attributedTo": f"{HUB}/actors/{AGENT}",
                "summary": "a question for you",
                "published": "2026-08-05",
            }
        ]

        with self._console(waiting) as console:
            page = console.get("/inbox", cookies={SESSION_COOKIE: "s"}).text

        assert "a question for you" in page
        assert AGENT in page

    def test_it_reads_the_humans_mailbox_not_the_consoles(self) -> None:
        """The assertion that would have caught the `*` bug: the client is asked to act
        as the signed-in human, so the mail shown is theirs and not the console's."""
        from typing import Any

        from agent_inbox.client import Config, HubClient
        from agent_inbox.console import build_console

        asked_as: list[str] = []

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub=HUB, name="console"))

            def hub_info(self) -> dict[str, Any]:
                return {"name": "t", "version": "1.0.0", "authenticated": False}

            def with_session(self, session: str | None) -> Stub:
                return self

            def acting_as(self, name: str, session: str) -> Stub:
                asked_as.append(name)
                return self

            def whoami(self) -> str:
                return HUMAN

            def check_inbox(self, *a: Any, **kw: Any) -> dict[str, Any]:
                return {"items": [], "unread": 0, "cursor": ""}

        with TestClient(app=build_console(Stub())) as console:
            console.get("/inbox", cookies={SESSION_COOKIE: "s"})

        assert asked_as == [HUMAN], (
            f"the console read as {asked_as!r} rather than as the signed-in human"
        )
