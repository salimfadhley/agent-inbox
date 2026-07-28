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
