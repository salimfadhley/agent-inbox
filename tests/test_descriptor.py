"""The federation descriptor: what a stranger is entitled to, and nothing more.

Written as **absences** (NFR-004). A test that checks a field is present cannot catch a
field that should not be — so the disclosure assertions here search the *whole
serialised body* rather than named keys, which means a field added next year cannot
smuggle a hub name or a count past them.
"""

import json

from litestar.testing import TestClient

from agent_inbox import visibility
from agent_inbox.api import build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.records import ActorRecord, ActorType
from agent_inbox.store import InMemoryStore

HUB = "https://us.example"
SECRET_NAME = "quangdaotrang"  # the hub's local name — must never cross the wire
AGENT = "rosemary_nasrin"


async def _hub(federating: bool = True, hub_name: str = SECRET_NAME) -> TestClient:
    store = InMemoryStore()
    mailbox = Mailbox(store, hub_name="fallback")
    await store.claim_name(
        ActorRecord(
            name=AGENT,
            actor_type=ActorType.SERVICE,
            profile={visibility.KEY: "discoverable"},
            created="2026-08-06",
            last_seen="2026-08-06",
        )
    )
    await mailbox.set_hub_setting("name", hub_name)
    await mailbox.set_hub_setting("title", "A Hub")
    if federating:
        await mailbox.set_hub_setting("federation", "enabled")
    return TestClient(app=build_api(House(mailbox), HUB))


class TestItIsServed:
    async def test_without_authentication(self) -> None:
        """The caller is a stranger by definition — a descriptor behind a credential
        cannot do the job it exists for."""
        client = await _hub()
        with client as c:
            assert c.get("/federation").status_code == 200

    async def test_even_when_federation_is_off(self) -> None:
        client = await _hub(federating=False)
        with client as c:
            assert c.get("/federation").status_code == 200

    async def test_it_reports_disabled_honestly(self) -> None:
        """T017. Saying nothing, or implying otherwise, makes a compatibility check that
        cannot be trusted — worse than one reporting a state the caller dislikes."""
        client = await _hub(federating=False)
        with client as c:
            assert c.get("/federation").json()["federation"] == "disabled"

    async def test_the_paired_positive(self) -> None:
        """The fields it is *supposed* to carry, so a descriptor returning `{}` would
        not pass every absence test below."""
        client = await _hub()
        with client as c:
            body = c.get("/federation").json()

        assert body["software"]["name"] == "agent-inbox"
        assert body["software"]["version"]
        assert body["id"] == HUB
        assert body["federation"] == "enabled"
        assert body["protocols"] == ["activitypub"]
        assert body["capabilities"]["inbox"] is True
        assert body["schemes"]
        assert body["publicKey"]["keyId"].startswith(HUB)


class TestWhatItMustNotCarry:
    """FR-010, and searched across the serialised body rather than by key name."""

    @staticmethod
    async def _body() -> str:
        client = await _hub()
        with client as c:
            return json.dumps(c.get("/federation").json())

    async def test_no_hub_name(self) -> None:
        """The one easiest to get wrong, because it feels like identity. Federated
        identity is the **domain**; the name is local, and keeping it off every
        federated surface is what keeps renaming free."""
        assert SECRET_NAME not in await self._body()

    async def test_no_actor_names(self) -> None:
        assert AGENT not in await self._body()

    async def test_no_counts(self) -> None:
        """A count says somebody is there. Asserted structurally: no key anywhere in the
        document maps to a bare integer, which is what a count looks like."""
        client = await _hub()
        with client as c:
            body = c.get("/federation").json()

        def integers(node: object, path: str = "") -> list[str]:
            if isinstance(node, bool):
                return []
            if isinstance(node, int):
                return [path]
            if isinstance(node, dict):
                return [p for k, v in node.items() for p in integers(v, f"{path}.{k}")]
            if isinstance(node, list):
                return [
                    p for i, v in enumerate(node) for p in integers(v, f"{path}[{i}]")
                ]
            return []

        assert integers(body) == [], "a number reached the descriptor"

    async def test_no_operator_information(self) -> None:
        body = (await self._body()).lower()

        for leak in ("admin", "operator", "password", "token", "email"):
            assert leak not in body, f"{leak!r} reached a stranger's descriptor"


class TestRenamingTheHubChangesNothing:
    async def test_the_descriptor_is_byte_identical_across_a_rename(self) -> None:
        """The property the `name` exclusion exists to provide, and the only way to know
        it holds is to rename and compare. If a name ever leaks in, this fails without
        anybody having to think of the field it leaked through."""
        one = await _hub(hub_name="before")
        with one as c:
            first = json.dumps(c.get("/federation").json(), sort_keys=True)

        two = await _hub(hub_name="entirelydifferent")
        with two as c:
            second = json.dumps(c.get("/federation").json(), sort_keys=True)

        assert first == second
