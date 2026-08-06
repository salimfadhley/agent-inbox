"""What visibility actually withholds — asserted as absences, not presences.

NFR-004 is the rule this file is written under: **a test that checks a field is present
cannot catch a field that should not be.** So the assertions here are mostly negative,
and each negative is paired with a positive that would fail if the filter simply hid
everything.

The second theme is that a refusal must not be an oracle. A `local` actor and a name
nobody holds produce the *same* answer — because a differently-worded refusal, asked a
thousand times, is a directory.
"""

from typing import Any

from litestar.testing import TestClient

from agent_inbox import visibility
from agent_inbox.api import build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.records import ActorRecord, ActorType
from agent_inbox.store import InMemoryStore

HUB = "https://us.example"
STAMP = "2026-08-06"

HIDDEN = "klara_dmitrieva"
UNLISTED = "rosemary_nasrin"
LISTED = "trevor_bakshi"


async def _hub(federating: bool = True) -> tuple[TestClient, InMemoryStore]:
    store = InMemoryStore()
    mailbox = Mailbox(store, hub_name="testhub")
    for name, level in (
        (HIDDEN, "local"),
        (UNLISTED, "normal"),
        (LISTED, "discoverable"),
    ):
        await store.claim_name(
            ActorRecord(
                name=name,
                actor_type=ActorType.SERVICE,
                profile={visibility.KEY: level},
                created=STAMP,
                last_seen=STAMP,
            )
        )
    if federating:
        await mailbox.set_hub_setting("federation", "enabled")
        await mailbox.set_hub_setting("name", "us")
    return TestClient(app=build_api(House(mailbox), HUB)), store


class TestWebfinger:
    async def test_an_unlisted_actor_still_resolves(self) -> None:
        """The paired positive, and the whole point of the middle level: `normal` is
        addressable. Without this a filter that hid everyone would pass the rest."""
        client, _ = await _hub()
        with client as c:
            answer = c.get(
                f"/.well-known/webfinger?resource=acct:{UNLISTED}@us.example"
            )

        assert answer.status_code == 200, answer.text

    async def test_a_local_actor_does_not_resolve(self) -> None:
        client, _ = await _hub()
        with client as c:
            answer = c.get(f"/.well-known/webfinger?resource=acct:{HIDDEN}@us.example")

        assert answer.status_code != 200

    async def test_the_refusal_is_indistinguishable_from_absence(self) -> None:
        """T013, asserted directly. If these two differ by so much as a word, asking for
        a thousand names tells you which ones exist."""
        client, _ = await _hub()
        with client as c:
            hidden = c.get(f"/.well-known/webfinger?resource=acct:{HIDDEN}@us.example")
            unknown = c.get(
                "/.well-known/webfinger?resource=acct:nobody_has_ever_held_this@us.example"
            )

        assert hidden.status_code == unknown.status_code
        # Compared with the requested name substituted out. The refusals *do* differ by
        # that name — and they must, because it is the name the caller just supplied, so
        # echoing it tells them nothing they did not write. What would be an oracle is
        # any *other* difference: a different code, a different shape, a different
        # sentence. That is what this pins.
        assert self._anonymised(hidden.json(), HIDDEN) == self._anonymised(
            unknown.json(), "nobody_has_ever_held_this"
        ), "a hidden actor's refusal differs from an unknown name's — that is an oracle"

    @staticmethod
    def _anonymised(payload: dict[str, Any], name: str) -> dict[str, Any]:
        return {
            key: (value.replace(name, "<name>") if isinstance(value, str) else value)
            for key, value in payload.items()
        }


class TestTheFederatedDirectory:
    @staticmethod
    def _names(payload: dict[str, Any]) -> set[str]:
        return {
            str(item.get("preferredUsername") or item.get("id", "")).rsplit("/", 1)[-1]
            for item in payload.get("items", [])
        }

    async def test_a_stranger_sees_the_discoverable(self) -> None:
        """The paired positive."""
        client, _ = await _hub()
        with client as c:
            names = self._names(c.get("/actors").json())

        assert LISTED in names

    async def test_a_stranger_does_not_see_the_unlisted(self) -> None:
        """`normal` is addressable but unlisted — the middle level doing its job."""
        client, _ = await _hub()
        with client as c:
            names = self._names(c.get("/actors").json())

        assert UNLISTED not in names

    async def test_a_stranger_does_not_see_the_local(self) -> None:
        client, _ = await _hub()
        with client as c:
            names = self._names(c.get("/actors").json())

        assert HIDDEN not in names

    async def test_a_hub_that_does_not_federate_still_lists_everyone(self) -> None:
        """Hub mode first (T012). With no outside to withhold from, the directory is a
        local tool and hiding half of it would break the product to protect against a
        stranger who cannot reach the port.

        This is the case that caught the first version of the filter, which gated on
        verification and emptied the directory on every `AUTH_MODE=off` deployment.
        """
        client, _ = await _hub(federating=False)
        with client as c:
            names = self._names(c.get("/actors").json())

        assert {HIDDEN, UNLISTED, LISTED} <= names


class TestTheActorDocument:
    async def test_an_unlisted_actor_is_served(self) -> None:
        """The paired positive: addressable means addressable."""
        client, _ = await _hub()
        with client as c:
            assert c.get(f"/actors/{UNLISTED}").status_code == 200

    async def test_a_local_actor_is_not(self) -> None:
        client, _ = await _hub()
        with client as c:
            assert c.get(f"/actors/{HIDDEN}").status_code == 404

    async def test_and_is_refused_exactly_as_an_unknown_name(self) -> None:
        client, _ = await _hub()
        with client as c:
            hidden = c.get(f"/actors/{HIDDEN}")
            unknown = c.get("/actors/nobody_has_ever_held_this")

        assert hidden.status_code == unknown.status_code


class TestVisibilityIsACeilingNeverAGrant:
    """FR-016. Asking to be found does not override the operator's decision not to
    federate at all — the field can only ever withhold."""

    async def test_a_discoverable_actor_is_unreachable_on_a_hub_that_does_not_federate(
        self,
    ) -> None:
        client, _ = await _hub(federating=False)
        with client as c:
            answer = c.get(f"/.well-known/webfinger?resource=acct:{LISTED}@us.example")

        assert answer.status_code != 200


class TestThePublicCount:
    async def test_a_local_actor_is_not_counted(self) -> None:
        """A count is a smaller disclosure than a name and is still one: it says
        somebody is there.

        **Differential rather than absolute.** The first version asserted a fixed number
        and was wrong for a reason worth keeping: `house.open()` installs the standing
        residents, so the total is never just the actors a test created. Counting the
        change when one actor's visibility flips proves the filter without depending on
        who else lives here.
        """
        client, store = await _hub()
        with client as c:
            before = c.get("/nodeinfo/2.1").json()["usage"]["users"]["total"]

            hidden = await store.get_actor(HIDDEN)
            assert hidden is not None
            await store.put_actor(
                ActorRecord(
                    name=hidden.name,
                    actor_type=hidden.actor_type,
                    profile={visibility.KEY: "normal"},
                    created=hidden.created,
                    last_seen=hidden.last_seen,
                )
            )
            after = c.get("/nodeinfo/2.1").json()["usage"]["users"]["total"]

        assert after == before + 1, (
            "un-hiding an actor did not change the public count — the filter is not "
            "reading visibility at all"
        )
