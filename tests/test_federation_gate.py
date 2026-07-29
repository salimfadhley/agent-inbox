"""The federation switch, and the one rule guarding it.

Federation itself is not built. What is tested here is that it cannot be switched on by
a hub with no name of its own, and that the descriptor stops claiming `federates: false`
when it is switched on.
"""

from __future__ import annotations

import pytest
from litestar.testing import TestClient

from agent_inbox.api import build_api
from agent_inbox.exceptions import MailboxError
from agent_inbox.federation import (
    DISABLED,
    ENABLED,
    LOCAL,
    FederationRefused,
    check_may_enable_federation,
    federates,
)
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"


def a_hub(name: str = LOCAL) -> House:
    return House(Mailbox(InMemoryStore(), hub_name=name))


def _federating(house: House, actor: str, **fields: object) -> None:
    """Switch federation on and put an actor in the store, through public surfaces.

    Joining goes through `house.join`, which is what an agent does, rather than reaching
    into the store — a test that bypasses the code under test proves less than it looks.
    """
    import asyncio

    async def _setup() -> None:
        await house.mailbox.set_hub_setting("federation", ENABLED)
        record = await house.join(actor)
        if fields:
            await house.update_profile(record.name, dict(fields.get("profile") or {}))

    asyncio.run(_setup())


class TestTheRule:
    def test_local_cannot_enable(self) -> None:
        with pytest.raises(FederationRefused) as caught:
            check_may_enable_federation(LOCAL)
        assert "told apart" in str(caught.value), "the refusal must say why"

    @pytest.mark.parametrize("name", ["LOCAL", " local ", "Local"])
    def test_the_rule_is_not_dodged_by_spelling(self, name: str) -> None:
        with pytest.raises(FederationRefused):
            check_may_enable_federation(name)

    def test_a_named_hub_may_enable(self) -> None:
        check_may_enable_federation("saltclub")

    def test_it_is_a_MailboxError(self) -> None:
        """So the API's generic handler maps it, rather than turning it into a 500."""
        assert issubclass(FederationRefused, MailboxError)


class TestTheSetting:
    def test_off_unless_something_says_otherwise(self) -> None:
        assert federates({}) is False
        assert federates({"federation": DISABLED}) is False
        assert federates({"federation": ENABLED}) is True


class TestTheSwitch:
    def test_a_fresh_hub_does_not_federate(self) -> None:
        with TestClient(app=build_api(a_hub(), HUB)) as c:
            assert c.get("/").json()["federates"] is False

    def test_enabling_on_an_unnamed_hub_is_refused(self) -> None:
        with TestClient(app=build_api(a_hub(), HUB)) as c:
            r = c.put("/hub", json={"federation": ENABLED})
            assert r.status_code == 409, r.text
            assert "told apart" in r.text
            assert c.get("/").json()["federates"] is False

    def test_naming_then_enabling_works(self) -> None:
        with TestClient(app=build_api(a_hub(), HUB)) as c:
            assert c.put("/hub", json={"name": "saltclub"}).status_code == 200
            assert c.put("/hub", json={"federation": ENABLED}).status_code == 200
            assert c.get("/").json()["federates"] is True

    def test_naming_and_enabling_in_one_request_works(self) -> None:
        """Judged on the outcome, not the starting point. Refusing this would make the
        rule about the order of keys in a JSON object, which is not a rule."""
        with TestClient(app=build_api(a_hub(), HUB)) as c:
            r = c.put("/hub", json={"name": "saltclub", "federation": ENABLED})
            assert r.status_code == 200, r.text
            assert c.get("/").json()["federates"] is True

    def test_an_unknown_mode_is_refused(self) -> None:
        with TestClient(app=build_api(a_hub("saltclub"), HUB)) as c:
            assert c.put("/hub", json={"federation": "open"}).status_code == 400

    def test_disabling_always_works(self) -> None:
        """Turning it off must never be gated. An operator locked into federation by a
        rule about names would have no way out."""
        with TestClient(app=build_api(a_hub("saltclub"), HUB)) as c:
            c.put("/hub", json={"federation": ENABLED})
            assert c.put("/hub", json={"federation": DISABLED}).status_code == 200
            assert c.get("/").json()["federates"] is False


class TestNodeInfo:
    """The discovery document the fediverse already agreed on.

    Served **only when federation is enabled**. An earlier version served it always, on
    a bootstrap-deadlock argument that turned out to be wrong: enabling federation is a
    local act needing no peer, so two fresh hubs each enable and then add the other.
    Serving it unconditionally disclosed a private hub's roster size, title and
    description to anyone. Found by outside review, 2026-07-29.
    """

    def test_the_index_points_at_the_document(self) -> None:
        house = a_hub("saltclub")
        with TestClient(app=build_api(house, HUB)) as c:
            _federating(house, "alice")
            body = c.get("/.well-known/nodeinfo").json()
        assert body["links"][0]["rel"].endswith("/2.1")
        assert body["links"][0]["href"] == f"{HUB}/nodeinfo/2.1"

    def test_it_carries_every_field_the_schema_requires(self) -> None:
        """All seven are required by the published schema, so none may be omitted even
        where the honest answer is empty."""
        house = a_hub("saltclub")
        with TestClient(app=build_api(house, HUB)) as c:
            _federating(house, "alice")
            body = c.get("/nodeinfo/2.1").json()
        for field in (
            "version",
            "software",
            "protocols",
            "services",
            "openRegistrations",
            "usage",
            "metadata",
        ):
            assert field in body, f"nodeinfo is missing the required field {field!r}"
        assert body["version"] == "2.1"
        assert body["software"]["name"] == "agent-inbox"
        assert body["protocols"] == ["activitypub"]

    def test_a_hub_that_does_not_federate_has_no_nodeinfo(self) -> None:
        """The roster size, title and description of a private hub are not public.

        Both the index and the document are silent, rather than the index advertising a
        document that then refuses — that would say "something is here" to exactly the
        caller who should learn nothing.
        """
        with TestClient(app=build_api(a_hub("saltclub"), HUB)) as c:
            assert c.get("/.well-known/nodeinfo").status_code == 404
            assert c.get("/nodeinfo/2.1").status_code == 404

    def test_the_roster_size_is_not_disclosed_before_federating(self) -> None:
        house = a_hub("saltclub")
        with TestClient(app=build_api(house, HUB)) as c:
            import asyncio

            asyncio.run(house.join("alice"))
            asyncio.run(house.join("bob"))
            assert "2" not in c.get("/nodeinfo/2.1").text

    def test_our_own_fields_live_in_metadata(self) -> None:
        """Where the schema explicitly puts software-specific values, rather than in a
        parallel document of our own invention."""
        with TestClient(app=build_api(a_hub("saltclub"), HUB)) as c:
            c.put("/hub", json={"title": "The Salt Club", "federation": ENABLED})
            meta = c.get("/nodeinfo/2.1").json()["metadata"]
        assert meta["title"] == "The Salt Club"
        assert meta["federation"] == ENABLED

    def test_it_never_carries_the_hub_name(self) -> None:
        """The name does not cross the wire — that is what makes renaming free."""
        house = a_hub("saltclub")
        with TestClient(app=build_api(house, HUB)) as c:
            _federating(house, "alice")
            assert "saltclub" not in c.get("/nodeinfo/2.1").text


class TestWebFinger:
    """Resolution, and the silence that is the point of it."""

    def _hub_with_alice(self, base: str = "http://hub.example:8081"):
        house = a_hub("saltclub")
        return build_api(house, base)

    def test_a_hub_that_does_not_federate_resolves_nobody(self) -> None:
        with TestClient(app=self._hub_with_alice()) as c:
            c.post("/actors", json={"preferredUsername": "alice"})
            r = c.get("/.well-known/webfinger?resource=acct:alice@hub.example")
        assert r.status_code == 404, "a default hub must be silent here"

    def test_it_resolves_once_federation_is_on(self) -> None:
        with TestClient(app=self._hub_with_alice()) as c:
            c.post("/actors", json={"preferredUsername": "alice"})
            c.put("/hub", json={"federation": ENABLED})
            body = c.get(
                "/.well-known/webfinger?resource=acct:alice@hub.example"
            ).json()
        assert body["subject"] == "acct:alice@hub.example"
        link = body["links"][0]
        assert link["rel"] == "self"
        assert link["type"] == "application/activity+json"
        assert link["href"].endswith("/actors/alice")

    def test_the_port_is_part_of_the_address_not_the_identity(self) -> None:
        """A hub reached as `hub.example:8081` answers for `alice@hub.example` too."""
        with TestClient(app=self._hub_with_alice()) as c:
            c.post("/actors", json={"preferredUsername": "alice"})
            c.put("/hub", json={"federation": ENABLED})
            with_port = c.get(
                "/.well-known/webfinger?resource=acct:alice@hub.example:8081"
            )
            without = c.get("/.well-known/webfinger?resource=acct:alice@hub.example")
        assert with_port.status_code == without.status_code == 200

    def test_every_refusal_looks_the_same(self) -> None:
        """Absent, not this hub, malformed — one answer. Distinguishing them would tell
        a stranger which is true, and the first two are what should stay unsaid."""
        with TestClient(app=self._hub_with_alice()) as c:
            c.post("/actors", json={"preferredUsername": "alice"})
            c.put("/hub", json={"federation": ENABLED})
            codes = {
                c.get(f"/.well-known/webfinger?resource={r}").status_code
                for r in (
                    "acct:nobody@hub.example",
                    "acct:alice@elsewhere.invalid",
                    "alice",
                    "acct:alice",
                )
            }
        assert codes == {404}


class TestTheThinActorDocument:
    """Three audiences at one URL, and they are not the same.

    An **agent on this hub** presents a device token and gets the full document. A
    **peer hub** presents nothing and gets only what addressing requires. Anyone else,
    on a hub that does not federate, is refused exactly as before.
    """

    @staticmethod
    def _enforcing(hub_name: str = "saltclub"):
        from agent_inbox.auth.service import AuthService
        from agent_inbox.auth.store import InMemoryAuthStore

        house = a_hub(hub_name)
        auth = AuthService(InMemoryAuthStore(), secret_key="k" * 32)
        return build_api(house, HUB, auth=auth, auth_mode="enforce"), house

    def test_a_stranger_is_refused_when_the_hub_does_not_federate(self) -> None:
        app, house = self._enforcing()
        with TestClient(app=app) as c:
            assert c.get("/actors/anyone").status_code == 401

    def test_a_stranger_gets_barebones_once_it_federates(self) -> None:
        app, house = self._enforcing()
        with TestClient(app=app) as c:
            _federating(house, "alice")
            body = c.get("/actors/alice").json()

        assert body["preferredUsername"] == "alice"
        assert body["inbox"].endswith("/actors/alice/inbox")

    def test_barebones_means_barebones(self) -> None:
        """The disclosures a full document carries must not be in the public one.

        This is the assertion that stands between federation and publishing a private
        hub's roster: absence, not presence, is the security property.
        """
        app, house = self._enforcing()
        with TestClient(app=app) as c:
            _federating(
                house,
                "alice",
                profile={"project": "billing", "purpose": "secret work"},
                last_seen="2026-07-29T00:00:00Z",
            )
            body = c.get("/actors/alice").json()

        # The premise: the *rich* document really does carry these, so their absence
        # below is the gate working rather than the fields never existing.
        import asyncio

        from agent_inbox.api import Api

        rich = asyncio.run(Api(house, HUB).actor("alice"))
        assert rich.profile, "premise failed: the rich document carries no profile"
        assert rich.last_seen, "premise failed: the rich document has no last_seen"

        for leaked in ("profile", "lastSeen", "outbox", "summary"):
            assert leaked not in body, f"the public document leaks {leaked!r}"
        assert "billing" not in str(body)
        assert "secret work" not in str(body)

    def test_a_non_enforcing_hub_that_federates_still_serves_barebones(self) -> None:
        """A hub that cannot tell its own agents from strangers must assume stranger.

        With AUTH_MODE=off nobody is verified — the identity header is taken at face
        value, and a remote peer can send it too. So once federation is on, the public
        actor route is barebones for everyone.

        Found by the two-hub harness: before this, a non-enforcing hub with federation
        enabled published every agent's profile to the world.
        """
        house = a_hub("saltclub")
        with TestClient(app=build_api(house, HUB)) as c:
            _federating(house, "alice", profile={"project": "billing"})
            body = c.get("/actors/alice").json()
        assert body["preferredUsername"] == "alice"
        assert "profile" not in body
        assert "billing" not in str(body)

    def test_a_non_enforcing_hub_that_does_not_federate_is_unchanged(self) -> None:
        """The common case today, and it must keep working exactly as it did."""
        house = a_hub("saltclub")
        with TestClient(app=build_api(house, HUB)) as c:
            c.post("/actors", json={"preferredUsername": "alice"})
            body = c.get("/actors/alice").json()
        assert "profile" in body, "a LAN hub's own console still needs the full record"


class TestDoctorIsNotAnExistenceOracle:
    """`/doctor` is deliberately unguarded, and that made it a roster oracle.

    It is unguarded for a good reason: the caller who most needs it is the one whose
    credential is missing or revoked, and refusing them would answer with the very
    status they came to understand. But on an enforcing hub it reported whether a
    claimed name existed, so a stranger could enumerate agents by guessing.

    Found by outside review, 2026-07-29. The route's own docstring already promised
    "never who else is here"; this makes that true.
    """

    @staticmethod
    def _enforcing_with(actor: str):
        import asyncio

        from agent_inbox.auth.service import AuthService
        from agent_inbox.auth.store import InMemoryAuthStore

        house = a_hub("saltclub")
        asyncio.run(house.join(actor))
        auth = AuthService(InMemoryAuthStore(), secret_key="k" * 32)
        return build_api(house, HUB, auth=auth, auth_mode="enforce")

    def test_a_real_name_and_a_made_up_one_are_indistinguishable(self) -> None:
        app = self._enforcing_with("alice")
        with TestClient(app=app) as c:
            real = c.get("/doctor", headers={"X-Agent-Name": "alice"}).json()
            fake = c.get("/doctor", headers={"X-Agent-Name": "nobody_here"}).json()

        assert real["you"]["known"] == fake["you"]["known"]
        assert real["verdict"] == fake["verdict"]

    def test_it_says_it_will_not_say_rather_than_saying_no(self) -> None:
        """`null` is not `false`. A caller debugging a name deserves the difference."""
        app = self._enforcing_with("alice")
        with TestClient(app=app) as c:
            body = c.get("/doctor", headers={"X-Agent-Name": "alice"}).json()
        assert body["you"]["known"] is None

    def test_it_still_answers_at_all(self) -> None:
        """The reason it is unguarded must survive the fix."""
        app = self._enforcing_with("alice")
        with TestClient(app=app) as c:
            body = c.get("/doctor", headers={"X-Agent-Name": "alice"}).json()
        assert body["hub"]["authMode"] == "enforce"
        assert body["you"]["token"] == "not presented"
        assert body["verdict"]

    def test_a_lan_hub_is_unchanged(self) -> None:
        """A hub with auth off has no roster to protect that the header does not
        already give away, and its agents still need doctor to be useful."""
        import asyncio

        house = a_hub("lan")
        asyncio.run(house.join("bob"))
        with TestClient(app=build_api(house, HUB)) as c:
            assert c.get("/doctor", headers={"X-Agent-Name": "bob"}).json()["you"][
                "known"
            ]
            assert (
                c.get("/doctor", headers={"X-Agent-Name": "ghost"}).json()["you"][
                    "known"
                ]
                is False
            )
