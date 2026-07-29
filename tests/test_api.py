"""The API end to end, over HTTP.

The engine is already tested exhaustively; what is checked here is translation — that
AS2 goes in and out intact, that errors become honest statuses, and that no messaging
decision has quietly migrated up into this layer.
"""

from __future__ import annotations

import ast
import contextlib
import urllib.parse
from collections.abc import Iterator
from pathlib import Path

import pytest
from litestar.testing import TestClient

from agent_inbox import api as api_module
from agent_inbox.api import IDENTITY_HEADER, build_api
from agent_inbox.house import House
from agent_inbox.mailbox import Mailbox
from agent_inbox.store import InMemoryStore

HUB = "http://hub.invalid"
ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"
YITZHAK = "yitzhak_levin"


@pytest.fixture
def client() -> Iterator[TestClient]:
    house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
    with TestClient(app=build_api(house, HUB)) as c:
        yield c


def as_(name: str) -> dict[str, str]:
    return {IDENTITY_HEADER: name}


def join(client: TestClient, name: str) -> dict:
    r = client.post("/actors", json={"preferredUsername": name})
    assert r.status_code == 201, r.text
    return r.json()


def note(to: list[str], content: str, **kw: object) -> dict:
    return {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Create",
        "object": {"type": "Note", "to": to, "content": content, **kw},
    }


class TestHub:
    def test_the_hub_describes_itself(self, client: TestClient) -> None:
        body = client.get("/").json()
        assert body["type"] == "Service"
        assert body["name"] == "testhub"
        assert body["federates"] is False

    def test_it_says_out_loud_that_it_does_not_authenticate(
        self, client: TestClient
    ) -> None:
        """A hub that quietly does not authenticate is worse than one that says so."""
        body = client.get("/").json()
        assert body["authenticated"] is False
        assert "does not authenticate" in body["note"]

    def test_health_answers_without_the_store(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok"}


class TestIdentity:
    def test_a_missing_name_is_refused_with_advice(self, client: TestClient) -> None:
        r = client.get(f"/actors/{ROSEMARY}/inbox")
        assert r.status_code == 400
        assert IDENTITY_HEADER in r.json()["detail"]

    def test_an_unknown_caller_is_a_404(self, client: TestClient) -> None:
        r = client.get("/actors/ghost/inbox", headers=as_("ghost"))
        assert r.status_code == 404
        assert r.json()["code"] == "unknown_actor"


class TestActors:
    def test_joining_returns_an_actor_document(self, client: TestClient) -> None:
        actor = join(client, ROSEMARY)
        assert actor["preferredUsername"] == ROSEMARY
        assert actor["id"] == f"{HUB}/actors/{ROSEMARY}"
        assert actor["inbox"] == f"{HUB}/actors/{ROSEMARY}/inbox"
        assert actor["type"] == "Service"

    def test_joining_without_a_name_is_issued_one(self, client: TestClient) -> None:
        actor = client.post("/actors", json={}).json()
        assert "_" in actor["preferredUsername"]

    def test_a_taken_name_is_a_conflict(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        r = client.post("/actors", json={"preferredUsername": ROSEMARY})
        assert r.status_code == 409
        assert r.json()["code"] == "name_unavailable"

    def test_the_directory_lists_everyone(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        body = client.get("/actors").json()
        names = {a["preferredUsername"] for a in body["items"]}
        assert {ROSEMARY, TREVOR} <= names
        assert body["totalItems"] == len(body["items"])

    def test_standing_residents_are_present(self, client: TestClient) -> None:
        """admin and host exist before anyone joins."""
        names = {a["preferredUsername"] for a in client.get("/actors").json()["items"]}
        assert {"admin", "host"} <= names

    def test_an_unknown_actor_is_a_404(self, client: TestClient) -> None:
        assert client.get("/actors/nobody").status_code == 404


class TestMail:
    def test_the_whole_cycle(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)

        sent = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "one run in five", summary="flaky tests"),
            headers=as_(ROSEMARY),
        )
        assert sent.status_code == 201, sent.text
        posted = sent.json()
        assert posted["attributedTo"] == f"{HUB}/actors/{ROSEMARY}"
        assert posted["to"] == [f"{HUB}/actors/{TREVOR}"]
        assert posted["summary"] == "flaky tests"

        waiting = client.get(
            f"/actors/{TREVOR}/inbox?view=full", headers=as_(TREVOR)
        ).json()["items"]
        assert [n["summary"] for n in waiting] == ["flaky tests"]

        again = client.get(
            f"/actors/{TREVOR}/inbox?view=full", headers=as_(TREVOR)
        ).json()
        assert again["totalItems"] == 1, "peeking must not consume"

        object_id = posted["id"]
        read = client.post(
            f"/objects/{object_id.rsplit('/', 1)[-1]}/read", headers=as_(TREVOR)
        )
        assert read.status_code == 200
        assert (
            client.get(f"/actors/{TREVOR}/inbox?view=full", headers=as_(TREVOR)).json()[
                "totalItems"
            ]
            == 0
        )

    def test_a_bare_note_is_accepted_as_well_as_a_create(
        self, client: TestClient
    ) -> None:
        """A client posting what it means should not need to know AS2 wraps it."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json={"type": "Note", "to": [TREVOR], "content": "unwrapped"},
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 201, r.text

    def test_actor_uris_are_accepted_as_recipients(self, client: TestClient) -> None:
        """An agent that read an actor document will send the URI back."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([f"{HUB}/actors/{TREVOR}"], "by uri"),
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 201, r.text
        assert (
            client.get(f"/actors/{TREVOR}/inbox?view=full", headers=as_(TREVOR)).json()[
                "totalItems"
            ]
            == 1
        )

    def test_an_unknown_recipient_is_refused(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note(["nobody_here"], "typo"),
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 422
        assert r.json()["code"] == "unknown_recipient"

    def test_an_audience_that_reaches_nobody_is_refused(
        self, client: TestClient
    ) -> None:
        """422, not 500 and certainly not 201.

        Every name is real, so this is not `unknown_recipient`; it is still a send that
        would reach no one. The status matters as much as the refusal: an unmapped code
        falls through to 500, which would tell the caller the hub broke rather than that
        their audience was empty.

        A group is the case that reaches this over the API. `everyone` does not: a real
        hub always carries its reserved actors, so a broadcast is never truly empty.
        """
        join(client, ROSEMARY)
        client.put(
            f"/actors/{ROSEMARY}",
            json={"profile": {"groups": ["ops"]}},
            headers=as_(ROSEMARY),
        )
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note(["ops"], "anyone out there?"),
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 422
        assert r.json()["code"] == "delivers_to_nobody"

    def test_addressing_yourself_by_name_is_delivered(self, client: TestClient) -> None:
        """The deliberate case, over the API: it lands, and it is readable."""
        join(client, ROSEMARY)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([ROSEMARY], "note to self"),
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 201
        assert [t.rsplit("/", 1)[-1] for t in r.json()["to"]] == [ROSEMARY]
        waiting = client.get(
            f"/actors/{ROSEMARY}/inbox?view=full", headers=as_(ROSEMARY)
        ).json()["items"]
        assert [n["id"] for n in waiting] == [r.json()["id"]]

    def test_another_mailbox_is_refused_differently(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note(["someone@another_hub"], "abroad"),
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 422
        assert r.json()["code"] == "remote_mailbox"

    def test_reading_someone_elses_mail_is_a_404(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        join(client, YITZHAK)
        sent = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "private"),
            headers=as_(ROSEMARY),
        ).json()
        ident = sent["id"].rsplit("/", 1)[-1]
        r = client.post(f"/objects/{ident}/read", headers=as_(YITZHAK))
        assert r.status_code == 404
        assert r.json()["code"] == "no_such_message"


class TestThreads:
    def test_a_thread_shows_only_your_turns(self, client: TestClient) -> None:
        """Mission 0020, over HTTP."""
        for who in (ROSEMARY, TREVOR, YITZHAK):
            join(client, who)

        opening = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note(["everyone"], "pipeline down"),
            headers=as_(ROSEMARY),
        ).json()
        root = opening["id"].rsplit("/", 1)[-1]

        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "between us", inReplyTo=opening["id"]),
            headers=as_(ROSEMARY),
        )

        bystander = client.get(f"/objects/{root}/thread", headers=as_(YITZHAK)).json()
        assert [n["content"] for n in bystander["items"]] == ["pipeline down"]

        participant = client.get(f"/objects/{root}/thread", headers=as_(TREVOR)).json()
        assert participant["totalItems"] == 2

    def test_an_unknown_thread_is_a_404(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        r = client.get("/objects/nope/thread", headers=as_(ROSEMARY))
        assert r.status_code == 404


class TestObservation:
    """The operator's view (M2 FR-010) — the routes that replace impersonation.

    The property that matters is that these answer a *different* question from the
    agent routes: they show what is on the hub, take no caller, and consume nothing.
    """

    def _send(self, client: TestClient, frm: str, to: list[str], **kw: object) -> str:
        r = client.post(
            f"/actors/{frm}/outbox", json=note(to, "body", **kw), headers=as_(frm)
        )
        assert r.status_code == 201, r.text
        return r.json()["id"].rsplit("/", 1)[-1]

    def test_a_mailbox_can_be_observed_without_a_caller(
        self, client: TestClient
    ) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        self._send(client, ROSEMARY, [TREVOR], summary="first")
        r = client.get(f"/observe/mailbox/{TREVOR}")  # no X-Agent-Name at all
        assert r.status_code == 200
        assert [n["summary"] for n in r.json()["items"]] == ["first"]

    def test_observing_does_not_consume(self, client: TestClient) -> None:
        """The whole point: an operator looking must not mark the agent's mail read."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        self._send(client, ROSEMARY, [TREVOR], summary="untouched")
        client.get(f"/observe/mailbox/{TREVOR}")
        still = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert still["unread"] == 1, "observing stole the agent's mail"

    def test_observe_sees_a_whole_thread_no_participant_can(
        self, client: TestClient
    ) -> None:
        """The clearest way the operator view differs from an agent's.

        Rosemary broadcasts; Trevor replies to Rosemary privately. Yitzhak, a
        bystander on the broadcast, cannot see Trevor's reply — but the operator sees
        the conversation entire.
        """
        for who in (ROSEMARY, TREVOR, YITZHAK):
            join(client, who)
        root = self._send(client, ROSEMARY, [TREVOR, YITZHAK], summary="all hands")
        reply = client.post(
            f"/actors/{TREVOR}/outbox",
            json=note([ROSEMARY], "just you", inReplyTo=f"{HUB}/objects/{root}"),
            headers=as_(TREVOR),
        )
        assert reply.json()["inReplyTo"] == f"{HUB}/objects/{root}", (
            "the reply did not attach to the thread — the test would prove nothing"
        )
        # Yitzhak, party only to the opener, sees one turn.
        seen = client.get(f"/objects/{root}/thread", headers=as_(YITZHAK)).json()
        assert seen["totalItems"] == 1
        # The operator sees both.
        whole = client.get(f"/observe/objects/{root}/thread").json()
        assert whole["totalItems"] == 2

    def test_observe_object_reports_who_read_it(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        oid = self._send(client, ROSEMARY, [TREVOR], summary="ack me")
        before = client.get(f"/observe/objects/{oid}").json()
        assert before["readBy"] == []
        client.post(f"/objects/{oid}/read", headers=as_(TREVOR))
        after = client.get(f"/observe/objects/{oid}").json()
        assert after["readBy"] == [TREVOR]

    def test_stats_count_the_traffic(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        self._send(client, ROSEMARY, [TREVOR])
        self._send(client, ROSEMARY, [TREVOR])
        stats = client.get("/observe/stats").json()
        assert stats["messages"] == 2
        # flow is a list of [from, to, count]; one pair, twice.
        assert [ROSEMARY, TREVOR, 2] in [list(e) for e in stats["flow"]]

    def test_observing_an_absent_message_is_a_404(self, client: TestClient) -> None:
        assert client.get("/observe/objects/nope").status_code == 404
        assert client.get("/observe/objects/nope/thread").status_code == 404


class TestForeignProperties:
    def test_unknown_as2_properties_survive(self, client: TestClient) -> None:
        """ADR 0006: preserve what we do not understand.

        msgspec structs drop unmodelled fields, so the body is decoded twice. This is
        the test that catches it if that second decode is ever dropped.
        """
        join(client, ROSEMARY)
        join(client, TREVOR)
        body = note([TREVOR], "hello")
        body["object"]["sensitive"] = True
        body["object"]["x:mood"] = "cheerful"
        body["object"]["tag"] = [{"type": "Hashtag", "name": "#ops"}]

        sent = client.post(
            f"/actors/{ROSEMARY}/outbox", json=body, headers=as_(ROSEMARY)
        )
        assert sent.status_code == 201, sent.text

        ident = sent.json()["id"].rsplit("/", 1)[-1]
        assert client.get(f"/objects/{ident}", headers=as_(TREVOR)).status_code == 200

        # and the extras really are in the store, not merely accepted and dropped
        import asyncio

        mailbox = client.app.state.api.house.mailbox  # type: ignore[attr-defined]
        record = asyncio.run(mailbox.view(TREVOR, ident))
        assert record.document["x:mood"] == "cheerful"
        assert record.document["sensitive"] is True
        assert record.document["tag"] == [{"type": "Hashtag", "name": "#ops"}]


class TestFederationIsAbsent:
    def test_a_hub_that_does_not_federate_accepts_no_mail(
        self, client: TestClient
    ) -> None:
        """This used to assert a 501 — "the software cannot do this". It can now, so
        the claim changed even though the behaviour a caller sees did not: a hub that
        has not switched federation on still accepts nothing.
        """
        r = client.post(f"/actors/{ROSEMARY}/inbox", json={})
        assert r.status_code == 422
        assert "does not accept mail from other hubs" in r.text

    def test_the_refusal_does_not_say_whether_the_recipient_exists(
        self, client: TestClient
    ) -> None:
        """Same answer for a real actor and an invented one."""
        real = client.post(f"/actors/{ROSEMARY}/inbox", json={})
        invented = client.post("/actors/nobody_at_all/inbox", json={})
        assert real.status_code == invented.status_code
        assert real.json()["detail"] == invented.json()["detail"]


class TestNoLogicHere:
    """NFR-001: the API translates and does not decide."""

    def test_the_api_never_imports_the_rules(self) -> None:
        """A convenience shortcut here is how a second door opens (mission 0028)."""
        source = Path(api_module.__file__).read_text()
        imported = {
            node.module.split(".")[-1]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "rules" not in imported, "messaging decisions belong below this layer"

    def test_the_api_never_builds_a_record(self) -> None:
        """Constructing an ObjectRecord here would bypass send() and its policies."""
        source = Path(api_module.__file__).read_text()
        assert "ObjectRecord(" not in source
        assert "ActorRecord(" not in source


class TestReviewFindings:
    """Six defects found by outside review of this mission. Each has its shape here.

    All were invisible to a green test suite, because the tests were written by
    whoever wrote the routes — which is the argument for the review gate.
    """

    def test_the_path_owner_is_not_a_decoration(self, client: TestClient) -> None:
        """`/actors/alice/inbox` with Bob's header returned *Bob's* inbox, and a 200.

        The URL's owner meant nothing, and an authentication layer checking the path
        would have been checking nothing.
        """
        join(client, ROSEMARY)
        join(client, TREVOR)
        assert (
            client.get(f"/actors/{ROSEMARY}/inbox", headers=as_(TREVOR)).status_code
            == 403
        )
        assert (
            client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).status_code
            == 200
        )

    def test_you_cannot_post_as_somebody_else_via_the_path(
        self, client: TestClient
    ) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "not mine to send"),
            headers=as_(TREVOR),
        )
        assert r.status_code == 403

    def test_a_foreign_uri_stays_foreign(self, client: TestClient) -> None:
        """It used to be stripped to its last segment and delivered locally.

        `https://remote.example/actors/everyone` became a broadcast to this fleet.
        """
        join(client, ROSEMARY)
        join(client, TREVOR)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note(["https://remote.example/actors/everyone"], "meant for a peer"),
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 422
        assert r.json()["code"] == "remote_mailbox"
        assert (
            client.get(f"/actors/{TREVOR}/inbox?view=full", headers=as_(TREVOR)).json()[
                "totalItems"
            ]
            == 0
        )

    def test_in_reply_to_is_not_an_existence_oracle(self, client: TestClient) -> None:
        """A forbidden parent came back cleared; a nonexistent one was echoed.

        So a caller could tell "real but not yours" from "no such thing" by reading
        its own successful response — the probe refused everywhere else.
        """
        for who in (ROSEMARY, TREVOR, YITZHAK):
            join(client, who)
        private = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "private"),
            headers=as_(ROSEMARY),
        ).json()

        forbidden = client.post(
            f"/actors/{YITZHAK}/outbox",
            json=note([TREVOR], "x", inReplyTo=private["id"]),
            headers=as_(YITZHAK),
        ).json()
        absent = client.post(
            f"/actors/{YITZHAK}/outbox",
            json=note([TREVOR], "x", inReplyTo=f"{HUB}/objects/never-existed"),
            headers=as_(YITZHAK),
        ).json()
        assert forbidden["inReplyTo"] == absent["inReplyTo"] is None

    def test_a_bare_in_reply_to_is_a_real_reply(self, client: TestClient) -> None:
        """It used to return 201 with `to: []` and reach nobody — silent success."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        original = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "q", summary="flaky"),
            headers=as_(ROSEMARY),
        ).json()

        reply = client.post(
            f"/actors/{TREVOR}/outbox",
            json={"type": "Note", "content": "a", "inReplyTo": original["id"]},
            headers=as_(TREVOR),
        ).json()

        assert reply["to"] == [f"{HUB}/actors/{ROSEMARY}"]
        assert reply["summary"] == "Re: flaky"
        assert (
            client.get(f"/actors/{ROSEMARY}/inbox", headers=as_(ROSEMARY)).json()[
                "unread"
            ]
            == 1
        )

    def test_what_was_stored_is_what_comes_back(self, client: TestClient) -> None:
        """Audience and unknown properties were kept and then not returned."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        body = {
            "type": "Create",
            "x:onTheActivity": "kept",
            "object": {
                "type": "Note",
                "to": ["everyone"],
                "content": "hi",
                "x:mood": "cheerful",
            },
        }
        sent = client.post(
            f"/actors/{ROSEMARY}/outbox", json=body, headers=as_(ROSEMARY)
        ).json()
        assert sent["audience"] == ["everyone"]
        assert sent["extra"]["x:mood"] == "cheerful"
        assert sent["extra"]["x:onTheActivity"] == "kept", (
            "properties on the Create were dropped before storage"
        )


class TestSecondReviewFindings:
    """Three more, from a review of the *fixes*. One was caused by them."""

    def test_blind_addressing_is_refused_not_echoed(self, client: TestClient) -> None:
        """`bto`/`bcc` were preserved as unknown properties and rendered back.

        A recipient was shown exactly the list bcc exists to hide — a leak introduced
        by the "render unknown properties back" fix, which is why the review ran twice.
        Refusing is the only honest answer: silently dropping would leave the sender
        believing a blind recipient received it.
        """
        join(client, ROSEMARY)
        join(client, TREVOR)
        join(client, YITZHAK)
        r = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json={
                "type": "Note",
                "to": [TREVOR],
                "bto": [YITZHAK],
                "bcc": ["admin"],
                "content": "x",
            },
            headers=as_(ROSEMARY),
        )
        assert r.status_code == 422
        assert "blind addressing" in r.json()["detail"]

    def test_the_audience_cannot_be_spoofed(self, client: TestClient) -> None:
        """Inbound `audience` used to override what the hub computed.

        No content leaked, but a recipient could be shown false routing metadata —
        "this went to everyone" when it went to one person — and act on it.
        """
        join(client, ROSEMARY)
        join(client, TREVOR)
        sent = client.post(
            f"/actors/{ROSEMARY}/outbox",
            json={
                "type": "Note",
                "to": [TREVOR],
                "audience": ["everyone"],
                "content": "x",
            },
            headers=as_(ROSEMARY),
        ).json()
        assert sent["audience"] == [TREVOR], (
            "the hub decides the audience, not the sender"
        )

    def test_a_refused_view_is_observable(self, client: TestClient) -> None:
        """Failed views escaped before any observer saw them.

        Refused reads were recorded and refused views were not, so a prober could
        enumerate with GET instead of POST and stay invisible — contradicting
        ProbeDetector's own docstring.
        """
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox
        from agent_inbox.policy import ProbeDetector, StandingResidents
        from agent_inbox.store import InMemoryStore

        detector = ProbeDetector(threshold=99)
        house = House(Mailbox(InMemoryStore()), [StandingResidents(), detector])
        with TestClient(app=build_api(house, HUB)) as c:
            for who in (ROSEMARY, TREVOR, YITZHAK):
                c.post("/actors", json={"preferredUsername": who})
            private = c.post(
                f"/actors/{ROSEMARY}/outbox",
                json=note([TREVOR], "private"),
                headers=as_(ROSEMARY),
            ).json()
            ident = private["id"].rsplit("/", 1)[-1]

            assert c.get(f"/objects/{ident}", headers=as_(YITZHAK)).status_code == 404
            assert detector.refusals_for(YITZHAK) == 1, "a refused view must be seen"


class TestCompactInbox:
    """Triage without paying for the mail — mission compact-inbox-and-unread-triage.

    The old inbox returned every waiting message in full, so the cheapest thing an
    agent does — glance at its mailbox — was the most expensive call in the API, and it
    charged again for the same unread broadcast on every poll.
    """

    def _seed(self, client: TestClient, count: int = 3, body: str = "x" * 4000) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        for n in range(count):
            r = client.post(
                f"/actors/{ROSEMARY}/outbox",
                json=note([TREVOR], body, summary=f"subject {n}"),
                headers=as_(ROSEMARY),
            )
            assert r.status_code == 201, r.text

    def test_a_count_carries_no_mail_at_all(self, client: TestClient) -> None:
        """SC-001: learn the unread count without receiving any message body."""
        self._seed(client)
        body = client.get(
            f"/actors/{TREVOR}/inbox?view=count", headers=as_(TREVOR)
        ).json()

        assert body["unread"] == 3
        assert "items" not in body
        assert "x" * 100 not in repr(body), "a count leaked message content"

    def test_a_summary_says_who_and_what_but_never_the_words(
        self, client: TestClient
    ) -> None:
        """SC-002: sender, subject, id and time — enough to choose from, no bodies."""
        self._seed(client)
        body = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()

        assert body["unread"] == 3
        row = body["items"][0]
        assert row["attributedTo"].endswith(f"/actors/{ROSEMARY}")
        assert row["summary"] == "subject 0"
        assert row["published"] and row["id"]
        assert row["chars"] == 4000, "the size hint should describe the body"
        assert "content" not in row and "x" * 100 not in repr(body)

    def test_the_default_is_dramatically_cheaper(self, client: TestClient) -> None:
        """The point of the mission, stated as a number rather than a hope."""
        self._seed(client, count=5)
        summary = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).content
        full = client.get(
            f"/actors/{TREVOR}/inbox?view=full", headers=as_(TREVOR)
        ).content

        assert len(summary) * 10 < len(full), (
            f"summary {len(summary)}B vs full {len(full)}B — "
            "the compact path is not compact"
        )

    def test_a_cursor_hides_what_you_have_already_seen(
        self, client: TestClient
    ) -> None:
        """SC-003: ask for what is new and do not re-read old unread broadcasts."""
        self._seed(client, count=2)
        first = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        cursor = first["cursor"]

        again = client.get(
            f"/actors/{TREVOR}/inbox?since={_q(cursor)}", headers=as_(TREVOR)
        ).json()
        assert again["unread"] == 0, "the cursor did not filter what was already seen"

        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "new", summary="after the cursor"),
            headers=as_(ROSEMARY),
        )
        fresh = client.get(
            f"/actors/{TREVOR}/inbox?since={_q(cursor)}", headers=as_(TREVOR)
        ).json()
        assert [r["summary"] for r in fresh["items"]] == ["after the cursor"]

    def test_a_shared_timestamp_cannot_swallow_a_message(
        self, client: TestClient
    ) -> None:
        """Two messages in the same instant: neither may be hidden.

        Raised by ludmila_coe in review. On a timestamp-only cursor the second message
        of a tie is never greater than the cursor, so it is hidden permanently — and
        mail that vanished is indistinguishable from mail that never arrived. The cursor
        carries the message id for exactly this case.
        """
        self._seed(client, count=2, body="short")
        page = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        stamps = [row["published"] for row in page["items"]]

        # Walk the inbox one message at a time, as a session resuming from its cursor
        # does. Every message must be seen exactly once, ties or no ties.
        seen: list[str] = []
        cursor = ""
        for _ in range(5):  # bounded: a cursor that never advances must fail, not hang
            query = f"?since={_q(cursor)}" if cursor else ""
            step = client.get(
                f"/actors/{TREVOR}/inbox{query}", headers=as_(TREVOR)
            ).json()
            if not step["items"]:
                break
            seen.append(step["items"][0]["id"])
            cursor = _cursor_through(step["items"][0])

        assert len(seen) == len(set(seen)) == 2, (
            f"walked {seen} for stamps {stamps} — a message was hidden or repeated"
        )

    def test_threads_group_unread_without_revealing_hidden_turns(
        self, client: TestClient
    ) -> None:
        """SC-004: thread-level summaries, built only from what the caller can see."""
        self._seed(client, count=1, body="opening")
        opening = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()[
            "items"
        ][0]["id"]
        # Addressed *and* in-reply-to: a second turn of the same conversation landing
        # in Trevor's mailbox. A bare inReplyTo would go back to the original sender —
        # who here is Rosemary herself — and never reach him.
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note(
                [TREVOR],
                "and another thing",
                summary="Re: subject 0",
                inReplyTo=opening,
            ),
            headers=as_(ROSEMARY),
        )

        body = client.get(
            f"/actors/{TREVOR}/inbox?view=threads", headers=as_(TREVOR)
        ).json()

        assert len(body["threads"]) == 1, "two turns of one thread listed separately"
        group = body["threads"][0]
        assert group["unread"] == 2
        assert group["lastFrom"] == ROSEMARY
        assert group["subject"] == "subject 0"
        assert group["broadcast"] is False
        assert "opening" not in repr(body), "a thread summary carried a body"

    def test_nothing_compact_consumes_and_full_bodies_need_an_explicit_read(
        self, client: TestClient
    ) -> None:
        """SC-003/SC-005: triage is free; only `read` marks mail handled."""
        self._seed(client, count=1, body="the actual words")
        for query in ("", "?view=count", "?view=threads", "?view=full"):
            client.get(f"/actors/{TREVOR}/inbox{query}", headers=as_(TREVOR))

        page = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert page["unread"] == 1, "looking consumed the message"
        ident = page["items"][0]["id"].rsplit("/", 1)[-1]

        peeked = client.get(f"/objects/{ident}", headers=as_(TREVOR)).json()
        assert peeked["content"] == "the actual words"
        assert (
            client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()["unread"]
            == 1
        ), "peeking consumed the message"

        read = client.post(f"/objects/{ident}/read", headers=as_(TREVOR)).json()
        assert read["content"] == "the actual words"
        assert (
            client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()["unread"]
            == 0
        ), "reading did not consume the message"


def _cursor_through(row: dict) -> str:
    """The cursor a caller holds after being shown exactly this row."""
    return f"{row['published']}|{row['id'].rsplit('/', 1)[-1]}"


def _q(cursor: str) -> str:
    """A cursor, safe in a query string.

    Timestamps carry `+00:00`, and a raw `+` in a query string decodes to a space — so
    an unquoted cursor silently compares as a different, earlier instant. HubClient
    quotes it; a test that does not would be testing something the product never does.
    """
    return urllib.parse.quote(cursor, safe="")


class TestCompactInboxPaging:
    def test_a_neglected_mailbox_answers_in_one_bounded_page(
        self, client: TestClient
    ) -> None:
        """NFR-002: a glance costs a bounded amount however long you have ignored it.

        The cap is only safe because the cursor exists: what is left out is next, not
        lost. `unread` still reports the true backlog, because a count that quietly
        meant "up to fifty" would let a pile-up look handled.
        """
        from agent_inbox.api import PAGE

        join(client, ROSEMARY)
        join(client, TREVOR)
        for n in range(PAGE + 7):
            client.post(
                f"/actors/{ROSEMARY}/outbox",
                json=note([TREVOR], "hello", summary=f"subject {n}"),
                headers=as_(ROSEMARY),
            )

        first = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert first["unread"] == PAGE + 7, "the backlog was under-reported"
        assert len(first["items"]) == PAGE
        assert first["more"] == 7

        rest = client.get(
            f"/actors/{TREVOR}/inbox?since={_q(first['cursor'])}", headers=as_(TREVOR)
        ).json()
        assert len(rest["items"]) == 7, "the cursor did not reach the rest"
        assert "more" not in rest
        assert not {r["id"] for r in first["items"]} & {r["id"] for r in rest["items"]}


class TestAnOlderClientCanStillReadItsMail:
    """Upgrading the hub must not empty every already-running agent's mailbox.

    It did. The first version of the compact manifest invented `from` and `subject` and
    dropped `totalItems`, so a client older than the route looked for the
    ActivityStreams names, found none, and reported `0 waiting` against a mailbox
    holding eight messages — with rows of `?` and `None` for the mail it could not
    describe. Mail that looks like it is not there is the exact failure this mission
    exists to prevent, and the mission introduced it.

    Clients and hubs are upgraded separately and always will be. A summary is therefore
    a Note with its `content` withheld, in the same vocabulary as a full one.
    """

    def _old_client_reading(self, page: dict) -> tuple[int, list[tuple[str, str]]]:
        """Exactly what a pre-0.17 client does with an inbox response."""
        waiting = page.get("totalItems", 0)
        rows = [
            (
                (note.get("attributedTo") or "").rsplit("/", 1)[-1],
                note.get("summary") or "",
            )
            for note in page.get("items", [])
        ]
        return waiting, rows

    def test_the_count_and_the_rows_survive(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        for n in range(3):
            client.post(
                f"/actors/{ROSEMARY}/outbox",
                json=note(
                    [TREVOR], "a body an old client will not get", summary=f"s{n}"
                ),
                headers=as_(ROSEMARY),
            )

        page = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        waiting, rows = self._old_client_reading(page)

        assert waiting == 3, "an old client saw an empty mailbox"
        assert rows == [(ROSEMARY, "s0"), (ROSEMARY, "s1"), (ROSEMARY, "s2")], (
            "an old client saw rows it could not describe"
        )

    def test_a_count_view_is_readable_too(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        join(client, TREVOR)
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "x", summary="s"),
            headers=as_(ROSEMARY),
        )
        page = client.get(
            f"/actors/{TREVOR}/inbox?view=count", headers=as_(TREVOR)
        ).json()
        assert page["totalItems"] == page["unread"] == 1

    def test_the_body_is_still_withheld(self, client: TestClient) -> None:
        """Compatibility must not quietly restore the cost the mission removed."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "the expensive part", summary="s"),
            headers=as_(ROSEMARY),
        )
        page = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert "the expensive part" not in repr(page)
        assert "content" not in page["items"][0]


class TestPurgeRoutes:
    """The operator's view of expiry: look first, then act.

    Retention was written and never called — no message on any hub had ever been
    removed, while the onboarding prompt told agents mail expires after a fortnight.
    These routes are the operator half of fixing that; `purge_forever` is the other.
    """

    @pytest.fixture
    def aged(self) -> Iterator[TestClient]:
        """A hub holding one conversation that has gone quiet and one that has not.

        The clock is injected rather than the rows backdated. The API deliberately
        offers no way to send into the past, and adding one for a test would be a door
        into the store that nothing else has.
        """
        from datetime import UTC, datetime, timedelta

        class Clock:
            def __init__(self) -> None:
                self.now = datetime.now(UTC)

            def __call__(self) -> datetime:
                return self.now

        clock = Clock()
        house = House(
            Mailbox(InMemoryStore(), hub_name="testhub", retention_days=1, clock=clock)
        )
        with TestClient(app=build_api(house, HUB)) as client:
            join(client, ROSEMARY)
            join(client, TREVOR)
            client.post(
                f"/actors/{ROSEMARY}/outbox",
                json=note([TREVOR], "old", summary="gone quiet"),
                headers=as_(ROSEMARY),
            )
            clock.now += timedelta(days=30)
            client.post(
                f"/actors/{ROSEMARY}/outbox",
                json=note([TREVOR], "new", summary="still talking"),
                headers=as_(ROSEMARY),
            )
            yield client

    def test_the_preview_names_what_would_go_and_removes_nothing(
        self, aged: TestClient
    ) -> None:
        first = aged.get("/observe/purge", headers=as_(ROSEMARY)).json()
        assert first["threadCount"] == 1
        assert first["messageCount"] == 1
        assert first["threads"][0]["subject"] == "gone quiet"

        again = aged.get("/observe/purge", headers=as_(ROSEMARY)).json()
        assert again == first, "the preview consumed or changed something"

    def test_purging_removes_exactly_what_the_preview_named(
        self, aged: TestClient
    ) -> None:
        preview = aged.get("/observe/purge", headers=as_(ROSEMARY)).json()
        done = aged.post("/observe/purge", headers=as_(ROSEMARY)).json()

        assert done["removed"] == preview["messageCount"] == 1
        assert done["threads"] == preview["threads"], (
            "the purge did not do what the preview said it would — "
            "a preview that can disagree is worse than none, because it is trusted"
        )
        after = aged.get("/observe/purge", headers=as_(ROSEMARY)).json()
        assert after["threadCount"] == 0, "purging twice would remove it twice"

    def test_the_live_thread_survives(self, aged: TestClient) -> None:
        aged.post("/observe/purge", headers=as_(ROSEMARY))
        waiting = aged.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert waiting["unread"] == 1
        assert waiting["items"][0]["summary"] == "still talking"

    def test_retention_off_means_nothing_is_ever_named(self) -> None:
        """`retention_days = 0` disables expiry, whatever any schedule says.

        A maintenance feature that ignores its own off switch is the worst bug
        available here, because the operator believes they have turned it off.
        """
        house = House(Mailbox(InMemoryStore(), hub_name="testhub", retention_days=0))
        with TestClient(app=build_api(house, HUB)) as client:
            join(client, ROSEMARY)
            body = client.get("/observe/purge", headers=as_(ROSEMARY)).json()
            assert body["threads"] == []
            assert body["threadCount"] == body["messageCount"] == 0


class TestTheScheduler:
    """The loop that was missing for the life of the project.

    `expire()` was written, tested, documented as running "on every mailbox open", and
    never called by anything. These pin the three properties that make a scheduled
    deleter safe to leave running unattended.
    """

    async def test_it_sleeps_before_its_first_run(self) -> None:
        """A restart is not a decision to delete.

        Purging at startup would tie an unbounded, irreversible deletion to whoever
        happened to restart the container — at the moment nobody is watching, and
        without them knowing they had decided anything.
        """
        import asyncio

        from agent_inbox.api import purge_forever

        purges = 0

        class Counting:
            async def purge(self) -> tuple[()]:
                nonlocal purges
                purges += 1
                return ()

        task = asyncio.create_task(purge_forever(Counting(), minutes=60))
        await asyncio.sleep(0.05)  # far longer than startup, far shorter than an hour
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert purges == 0, "the hub deleted something the moment it came up"

    async def test_a_failed_purge_does_not_stop_the_next_one(self) -> None:
        """Housekeeping must not take the hub down.

        On 2026-07-26 an unrelated failure left an abandoned transaction and stopped all
        mail for eleven minutes. A purge that kills the hub it maintains would be that
        same mistake in a different coat.
        """
        import asyncio

        from agent_inbox.api import purge_forever

        attempts = 0

        class Failing:
            async def purge(self) -> tuple[()]:
                nonlocal attempts
                attempts += 1
                raise RuntimeError("the store said no")

        # A minute expressed in fractions, so the test does not wait for one.
        task = asyncio.create_task(purge_forever(Failing(), minutes=0.001))
        await asyncio.sleep(0.25)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert attempts > 1, "one failure stopped the schedule for good"

    async def test_it_stops_with_the_app(self) -> None:
        """Nothing should be left purging a store that is closing."""
        import asyncio

        from agent_inbox.api import purge_forever

        class Idle:
            async def purge(self) -> tuple[()]:
                return ()

        task = asyncio.create_task(purge_forever(Idle(), minutes=0.001))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.done()

    def test_interval_zero_starts_no_schedule(self) -> None:
        """The off switch must win, and the operator routes must still work.

        Disabling the schedule is a decision to purge by hand, not a decision to forget
        retention exists.
        """
        house = House(Mailbox(InMemoryStore(), hub_name="testhub", retention_days=1))
        with TestClient(app=build_api(house, HUB, purge_interval_minutes=0)) as client:
            join(client, ROSEMARY)
            assert (
                client.get("/observe/purge", headers=as_(ROSEMARY)).status_code == 200
            )


class TestTheSchedulerDoesNotDieQuietly:
    """The whole argument against a sidecar was that its death would be invisible.

    Moving the loop inside the hub does not by itself fix that — an in-process task can
    stop just as silently, and the symptom would be identical: mail quietly not
    expiring, which is the symptom this project had from the start and nobody noticed.
    Raised by ludmila_coe, who pointed out I had made the argument and not the fix.
    """

    async def test_a_loop_that_dies_says_so_at_critical(self, caplog) -> None:
        import asyncio
        import logging

        from agent_inbox.api import _complain_if_it_died

        async def dies() -> None:
            raise RuntimeError("the event loop went away")

        task = asyncio.create_task(dies())
        with contextlib.suppress(RuntimeError):
            await task
        with caplog.at_level(logging.CRITICAL, logger="agent_inbox.api"):
            _complain_if_it_died(task)

        assert caplog.records, "the purge loop died and nothing said anything"
        (record,) = caplog.records
        assert record.levelno == logging.CRITICAL
        assert "NO LONGER" in record.message, (
            "the operator must be told retention stopped, not just that a task did"
        )

    async def test_a_loop_that_returns_also_says_so(self, caplog) -> None:
        """`while True` cannot return — so if it ever does, something is very wrong."""
        import asyncio
        import logging

        from agent_inbox.api import _complain_if_it_died

        async def returns() -> None:
            return None

        task = asyncio.create_task(returns())
        await task
        with caplog.at_level(logging.CRITICAL, logger="agent_inbox.api"):
            _complain_if_it_died(task)

        assert caplog.records
        assert "no longer running" in caplog.records[0].message.lower()

    async def test_shutdown_is_silent(self, caplog) -> None:
        """Cancellation is the one way it is meant to end. Crying wolf at every
        shutdown would train everyone to ignore the message that matters."""
        import asyncio
        import logging

        from agent_inbox.api import _complain_if_it_died

        async def forever() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(forever())
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with caplog.at_level(logging.CRITICAL, logger="agent_inbox.api"):
            _complain_if_it_died(task)

        assert not caplog.records, "a normal shutdown logged a crisis"


class TestFrequentRestartsDoNotStarveThePurge:
    """A hub restarted more often than its interval must still purge.

    Found by asking why no scheduled cycle had appeared in production. The hub had been
    redeployed roughly every fifteen minutes that evening, and the loop slept a full
    hour before its first run — so retention would have run exactly never, while the
    startup log cheerfully reported it as scheduled. That is the silent non-expiry this
    mission exists to end, rebuilt inside the fix for it.
    """

    async def test_the_first_cycle_does_not_wait_a_whole_interval(self) -> None:
        import asyncio

        from agent_inbox.api import SETTLE_MINUTES, purge_forever

        slept: list[float] = []
        real_sleep = asyncio.sleep

        async def record(seconds: float) -> None:
            slept.append(seconds)
            await real_sleep(0)

        class Idle:
            async def purge(self) -> tuple[()]:
                return ()

        asyncio.sleep = record  # type: ignore[assignment]
        try:
            task = asyncio.create_task(purge_forever(Idle(), minutes=60))
            await real_sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            asyncio.sleep = real_sleep  # type: ignore[assignment]

        assert slept, "the loop never slept at all"
        assert slept[0] == SETTLE_MINUTES * 60, (
            f"the first cycle waited {slept[0] / 60:.0f} minutes; a hub redeployed "
            "more often than that would never purge"
        )
        assert slept[0] > 60, "the first cycle is close enough to startup to be startup"
        assert slept[1] == 60 * 60, "later cycles should use the configured interval"

    async def test_a_short_interval_is_not_lengthened(self) -> None:
        """An operator asking for every minute must not silently get every five."""
        import asyncio

        from agent_inbox.api import purge_forever

        slept: list[float] = []
        real_sleep = asyncio.sleep

        async def record(seconds: float) -> None:
            slept.append(seconds)
            await real_sleep(0)

        class Idle:
            async def purge(self) -> tuple[()]:
                return ()

        asyncio.sleep = record  # type: ignore[assignment]
        try:
            task = asyncio.create_task(purge_forever(Idle(), minutes=1))
            await real_sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            asyncio.sleep = real_sleep  # type: ignore[assignment]

        assert slept[0] == 60, "a one-minute interval was stretched to the settle time"


class TestThePurgeHeartbeat:
    """Proof the loop reached its first cycle, not merely that it was started.

    ludmila_coe's point after the 0.18.1 starvation bug: the CRITICAL log catches a loop
    that dies, but nothing caught a loop that never arrived. The startup line said
    "scheduled" for hours while retention did not run once. An absent timestamp is the
    only thing that distinguishes scheduled-and-working from scheduled-and-starving.
    """

    async def test_a_completed_cycle_is_visible_to_an_operator(self) -> None:
        import asyncio

        from agent_inbox.api import PurgeStatus, purge_forever

        status = PurgeStatus()
        assert status.as_dict()["lastCycle"] is None, "claimed a cycle before running"

        class Idle:
            async def purge(self) -> tuple[()]:
                return ()

        task = asyncio.create_task(purge_forever(Idle(), minutes=0.001, status=status))
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert status.as_dict()["lastCycle"] is not None, (
            "the loop ran and left no evidence — which is the 0.18.1 bug's signature"
        )
        assert status.as_dict()["cycles"] >= 1

    async def test_a_failing_cycle_is_reported_not_hidden(self) -> None:
        import asyncio

        from agent_inbox.api import PurgeStatus, purge_forever

        status = PurgeStatus()

        class Failing:
            async def purge(self) -> tuple[()]:
                raise RuntimeError("the store said no")

        task = asyncio.create_task(
            purge_forever(Failing(), minutes=0.001, status=status)
        )
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert status.as_dict()["lastError"] is not None
        assert "the store said no" in status.as_dict()["lastError"]
        assert status.as_dict()["lastCycle"] is None, (
            "a failed cycle must not look like a successful one"
        )

    def test_the_preview_route_carries_the_heartbeat(self, client: TestClient) -> None:
        join(client, ROSEMARY)
        body = client.get("/observe/purge", headers=as_(ROSEMARY)).json()
        assert "schedule" in body
        assert body["schedule"]["lastCycle"] is None
        assert body["schedule"]["cycles"] == 0


class TestAskingWhetherHousekeepingIsAlive:
    """The health of retention is not a secret; what is about to be deleted is.

    Found by trying to verify the heartbeat on the live hub and being refused by my own
    guard. Correctly refused, and uselessly: needing the credential that can delete
    every message in order to ask whether deletion is running is how a check stops being
    performed at all.
    """

    def test_an_agent_can_ask_whether_retention_is_running(
        self, client: TestClient
    ) -> None:
        join(client, ROSEMARY)
        body = client.get("/observe/purge/status", headers=as_(ROSEMARY)).json()
        assert set(body) == {
            "lastCycle",
            "cycles",
            "lastRemovedThreads",
            "lastRemovedObjects",
            "lastError",
        }

    def test_it_carries_no_mail_and_no_subjects(self, client: TestClient) -> None:
        """The preview lists what is about to die. This must not."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "a private body", summary="a private subject"),
            headers=as_(ROSEMARY),
        )
        body = client.get("/observe/purge/status", headers=as_(ROSEMARY)).text
        assert "private subject" not in body
        assert "private body" not in body
        assert "threads" not in body


class TestThePublishedSchema:
    """`the-api` FR-014, which shipped with every other requirement in that mission
    except this one — and stayed marked `proposed` for months, indistinguishable from
    work nobody had started.

    A generated schema is nearly free. The part worth testing is the part a generator
    cannot produce: the AS2 *profile*. A client author in another language can read the
    route signatures for themselves; what they cannot infer is which properties survive
    a round trip, which addressing is refused, and which call consumes.
    """

    def _schema(self, client: TestClient) -> dict:
        response = client.get("/schema/openapi.json")
        assert response.status_code == 200, "no schema is published"
        return response.json()

    def test_it_is_openapi_3_1(self, client: TestClient) -> None:
        assert self._schema(client)["openapi"].startswith("3.1")

    def test_it_covers_the_routes_that_carry_mail(self, client: TestClient) -> None:
        paths = self._schema(client)["paths"]
        for required in (
            "/actors/{name}/inbox",
            "/actors/{name}/outbox",
            "/objects/{object_id}",
            "/objects/{object_id}/read",
        ):
            assert required in paths, f"{required} is undocumented"

    def test_it_describes_what_a_generator_cannot(self, client: TestClient) -> None:
        """The profile: what we accept, emit, ignore, and refuse.

        Asserted on meaning rather than wording, so rephrasing the prose does not fail
        the test — but removing a *subject* does.
        """
        described = " ".join(self._schema(client)["info"]["description"].split())

        assert "bto" in described and "bcc" in described, (
            "blind addressing is refused with 422 and the schema does not say so"
        )
        assert "consumes nothing" in described, (
            "the schema does not say that reading the inbox is free"
        )
        assert "survives a round trip" in described, (
            "unknown AS2 properties are preserved (ADR 0006) and the schema is silent"
        )
        assert "X-Agent-Name" in described, "the identity header is undocumented"
        assert "404" in described, (
            "absent and forbidden are deliberately the same answer; a client author "
            "who does not know that will read a 404 as a bug"
        )

    def test_it_names_the_running_version(self, client: TestClient) -> None:
        from agent_inbox import __version__

        assert self._schema(client)["info"]["version"] == __version__


class TestACursorAlwaysMeansSomething:
    """The cold-start case: a quiet mailbox on the very first poll.

    That poll is exactly when a caller starts persisting the cursor, and it used to hand
    back an empty string. Stored and returned, `""` is falsy and reads as "no filter",
    the next poll serves everything and the caller re-reads mail it had accounted for. A
    bookmark that means "everything" is worse than none, because it looks like one.
    """

    def test_an_empty_inbox_still_yields_a_usable_cursor(
        self, client: TestClient
    ) -> None:
        join(client, TREVOR)
        page = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()
        assert page["unread"] == 0
        assert page["cursor"], "an empty inbox must still hand back a bookmark"

    def test_that_cursor_does_not_behave_as_no_filter(self, client: TestClient) -> None:
        """The failure the empty string invited, asserted directly."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        cold = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()[
            "cursor"
        ]

        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "sent before the second poll", summary="one"),
            headers=as_(ROSEMARY),
        )
        again = client.get(
            f"/actors/{TREVOR}/inbox?since={_q(cold)}", headers=as_(TREVOR)
        ).json()
        assert again["unread"] == 1, "mail sent after the bookmark must still arrive"

    def test_the_cold_cursor_survives_a_quiet_poll(self, client: TestClient) -> None:
        join(client, TREVOR)
        first = client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()[
            "cursor"
        ]
        second = client.get(
            f"/actors/{TREVOR}/inbox?since={_q(first)}", headers=as_(TREVOR)
        ).json()
        assert second["unread"] == 0
        assert second["cursor"], "a quiet poll must not erase the bookmark"

    def test_count_view_agrees_with_the_manifest(self, client: TestClient) -> None:
        """FR-003, which was already true — and nothing said it had to stay true."""
        join(client, TREVOR)
        counted = client.get(
            f"/actors/{TREVOR}/inbox?view=count", headers=as_(TREVOR)
        ).json()
        assert counted["cursor"], "count must advertise a cursor of the same kind"

    def test_an_empty_since_is_still_tolerated(self, client: TestClient) -> None:
        """FR-006: an older client sends "" and must not be broken by this change."""
        join(client, ROSEMARY)
        join(client, TREVOR)
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "body", summary="visible"),
            headers=as_(ROSEMARY),
        )
        page = client.get(f"/actors/{TREVOR}/inbox?since=", headers=as_(TREVOR)).json()
        assert page["unread"] == 1, "an empty since must mean no filter, not no mail"


class TestACursorSurvivesBeingPutInAUrl:
    """Our timestamps contain `+`, and `+` in a query string means a space.

    A caller that pastes back the opaque string it was handed sends something different
    from what it received. The mangled value sorts *below* every real one, so a filter
    meant to exclude what has been seen matched everything instead — and said nothing.

    The property under test is not "the fix is applied" but "raw and escaped agree".
    That survives a change of mechanism, which an assertion about `.replace` would not.
    """

    def _seed_one(self, client: TestClient) -> str:
        join(client, ROSEMARY)
        join(client, TREVOR)
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "body", summary="already seen"),
            headers=as_(ROSEMARY),
        )
        return client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR)).json()[
            "cursor"
        ]

    def test_a_cursor_pasted_raw_still_filters(self, client: TestClient) -> None:
        """The defect, stated as its symptom: mail must not be served twice."""
        cursor = self._seed_one(client)
        assert "+" in cursor, "precondition: the cursor carries a UTC offset"

        raw = client.get(
            f"/actors/{TREVOR}/inbox?since={cursor}", headers=as_(TREVOR)
        ).json()
        assert raw["unread"] == 0, (
            "a cursor pasted into a URL unescaped re-served mail already accounted for"
        )

    def test_raw_and_escaped_agree(self, client: TestClient) -> None:
        cursor = self._seed_one(client)
        raw = client.get(
            f"/actors/{TREVOR}/inbox?since={cursor}", headers=as_(TREVOR)
        ).json()
        escaped = client.get(
            f"/actors/{TREVOR}/inbox?since={_q(cursor)}", headers=as_(TREVOR)
        ).json()
        assert raw["unread"] == escaped["unread"]
        assert raw["cursor"] == escaped["cursor"]

    def test_new_mail_still_arrives_through_a_raw_cursor(
        self, client: TestClient
    ) -> None:
        """Tolerating the mangling must not turn the filter into a wall."""
        cursor = self._seed_one(client)
        client.post(
            f"/actors/{ROSEMARY}/outbox",
            json=note([TREVOR], "body", summary="after the cursor"),
            headers=as_(ROSEMARY),
        )
        fresh = client.get(
            f"/actors/{TREVOR}/inbox?since={cursor}", headers=as_(TREVOR)
        ).json()
        assert [r["summary"] for r in fresh["items"]] == ["after the cursor"]

    def test_a_nonsense_cursor_still_degrades_rather_than_raising(
        self, client: TestClient
    ) -> None:
        """FR-004: tolerance must not make the parser strict."""
        self._seed_one(client)
        for junk in ("banana", "|||", "2026-13-45T99:99", " "):
            got = client.get(
                f"/actors/{TREVOR}/inbox?since={_q(junk)}", headers=as_(TREVOR)
            )
            assert got.status_code == 200, f"{junk!r} should degrade, not raise"

    def test_the_survey_timestamp_gets_the_same_treatment(
        self, client: TestClient
    ) -> None:
        """A guard, and honestly labelled as one: this passes with the fix removed.

        `/observe/stats?since=` takes a bare timestamp and, measured, does **not**
        currently misbehave on a mangled one — it compares `published >= since` on a
        string, and no real timestamp sorts between `...+00:00` and `... 00:00`. An
        earlier version of this test claimed otherwise and passed for that reason, which
        is the vacuous-check shape `AGENTS.md` is about.

        It stays because the route is one operator away from the inbox's bug — `>=` to
        `>` — and this pins the property that would break first. Do not read a passing
        run here as evidence the normalisation is doing work today.
        """
        self._seed_one(client)
        stamp = (
            client.get(f"/actors/{TREVOR}/inbox", headers=as_(TREVOR))
            .json()["cursor"]
            .split("|")[0]
        )
        assert "+" in stamp

        raw = client.get(f"/observe/stats?since={stamp}").json()
        escaped = client.get(f"/observe/stats?since={_q(stamp)}").json()
        assert raw["messages_since"] == escaped["messages_since"], (
            "a raw timestamp counted differently from an escaped one"
        )


class TestHubSettings:
    """Name, title and description: reported, changed, and refused.

    The hub here does not authenticate, so `provide_operator` admits the caller — the
    same posture the console's `_gate` already has. Operator gating under `enforce` is
    covered in the auth suite; what is asserted here is the behaviour of the routes.
    """

    def test_unset_fields_are_absent_from_the_descriptor(
        self, client: TestClient
    ) -> None:
        """Every hub in existence looked like this before these fields, so it is the
        base case, not the edge case. `""` would be a value someone chose."""
        body = client.get("/").json()
        assert "title" not in body
        assert "description" not in body

    def test_settings_report_value_and_source(self, client: TestClient) -> None:
        body = client.get("/hub/settings").json()
        assert body["name"] == {"value": "testhub", "source": "default"}
        assert body["title"] == {"value": None, "source": "default"}

    def test_a_write_takes_effect_and_shows_in_the_descriptor(
        self, client: TestClient
    ) -> None:
        r = client.put("/hub", json={"title": "The Salt Club"})
        assert r.status_code == 200, r.text
        assert r.json()["title"] == {"value": "The Salt Club", "source": "stored"}
        assert client.get("/").json()["title"] == "The Salt Club"

    def test_an_omitted_field_is_left_alone(self, client: TestClient) -> None:
        """A partial body is the normal case, not an edge case."""
        client.put("/hub", json={"title": "The Salt Club"})
        client.put("/hub", json={"description": "Rare and obscure salts"})
        body = client.get("/").json()
        assert body["title"] == "The Salt Club"
        assert body["description"] == "Rare and obscure salts"

    def test_an_explicit_null_clears(self, client: TestClient) -> None:
        client.put("/hub", json={"title": "The Salt Club"})
        client.put("/hub", json={"title": None})
        assert "title" not in client.get("/").json()

    def test_an_invalid_name_is_refused_with_422(self, client: TestClient) -> None:
        """Asserted at the wire, not on the exception type. A code missing from
        STATUS_BY_CODE becomes a 500 and the generic handler makes it look handled —
        this repo has shipped exactly that."""
        r = client.put("/hub", json={"name": "The Salt Club"})
        assert r.status_code == 422, r.text
        assert "saltclub" in r.text

    def test_a_hostname_is_refused_as_a_name(self, client: TestClient) -> None:
        r = client.put("/hub", json={"name": "hub.thesaltclub.xyz"})
        assert r.status_code == 422, r.text
        assert "address" in r.text

    def test_a_valid_name_is_accepted(self, client: TestClient) -> None:
        r = client.put("/hub", json={"name": "saltclub"})
        assert r.status_code == 200, r.text
        assert client.get("/").json()["name"] == "saltclub"

    def test_unknown_keys_are_refused(self, client: TestClient) -> None:
        r = client.put("/hub", json={"public_url": "https://elsewhere.invalid"})
        assert r.status_code == 400, r.text


class TestIdentitySurvivesTheAddress:
    """NFR-003, and the mission in one line.

    Two agents on one hub, reaching it by different addresses, concluded they were on
    different hubs. That is what this mission exists to prevent, so it is asserted
    rather than stated.
    """

    def test_changing_the_public_url_does_not_change_the_name(self) -> None:
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        with TestClient(app=build_api(house, "http://one.invalid")) as first:
            first.put("/hub", json={"name": "saltclub"})
            before = first.get("/").json()

        # Same store, same hub — a different address. This is a proxy being added, a
        # port changing, a machine being renamed.
        with TestClient(app=build_api(house, "http://two.invalid:8081")) as second:
            after = second.get("/").json()

        assert before["id"] != after["id"], "the premise: the address really changed"
        assert before["name"] == after["name"] == "saltclub"

    def test_two_addresses_one_hub_report_the_same_name(self) -> None:
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        with TestClient(app=build_api(house, "http://machine.invalid")) as a:
            a.put("/hub", json={"name": "saltclub"})
            by_short = a.get("/").json()["name"]
        with TestClient(app=build_api(house, "http://machine.example:8081")) as b:
            by_long = b.get("/").json()["name"]
        assert by_short == by_long == "saltclub"


class TestTheEnvironmentGoverns:
    """Precedence at the wire, and the two ways a stored value could be destroyed."""

    def test_a_governed_field_reports_its_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_INBOX_HUB_TITLE", "Set By Deployment")
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        with TestClient(app=build_api(house, HUB)) as c:
            title = c.get("/hub/settings").json()["title"]
        assert title == {
            "value": "Set By Deployment",
            "source": "environment",
            "variable": "AGENT_INBOX_HUB_TITLE",
        }

    def test_writing_a_governed_field_is_refused_with_409(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refused, not accepted-and-ignored. Accepting a write the next read would
        override is a change that reports success and does nothing."""
        monkeypatch.setenv("AGENT_INBOX_HUB_TITLE", "Set By Deployment")
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        with TestClient(app=build_api(house, HUB)) as c:
            # The premise: it really is governed before we assert the refusal.
            assert c.get("/hub/settings").json()["title"]["source"] == "environment"
            r = c.put("/hub", json={"title": "Something Else"})
        assert r.status_code == 409, r.text
        assert "AGENT_INBOX_HUB_TITLE" in r.text

    def test_an_override_does_not_erase_the_stored_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set, shadow, unset — and the operator's own value comes back."""
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        with TestClient(app=build_api(house, HUB)) as c:
            c.put("/hub", json={"title": "The Salt Club"})

        monkeypatch.setenv("AGENT_INBOX_HUB_TITLE", "Set By Deployment")
        with TestClient(app=build_api(house, HUB)) as c:
            assert c.get("/").json()["title"] == "Set By Deployment"

        monkeypatch.delenv("AGENT_INBOX_HUB_TITLE")
        with TestClient(app=build_api(house, HUB)) as c:
            assert c.get("/").json()["title"] == "The Salt Club"

    def test_an_environment_value_is_never_written_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-011, found by outside review on 2026-07-28.

        The sequence: a client renders the effective value while the environment
        governs; the variable is then removed; the client submits what it rendered.
        Startup was guarded against erasure and this path was not — and it is the path
        an operator actually uses.
        """
        house = House(Mailbox(InMemoryStore(), hub_name="testhub"))
        with TestClient(app=build_api(house, HUB)) as c:
            c.put("/hub", json={"title": "The Salt Club"})

        monkeypatch.setenv("AGENT_INBOX_HUB_TITLE", "Ops Title")
        with TestClient(app=build_api(house, HUB)) as c:
            page = c.get("/hub/settings").json()
        rendered, version = page["title"]["value"], page["version"]
        assert rendered == "Ops Title", "the premise: the client saw the env value"

        # The variable goes away, and the stale page submits what it rendered, saying
        # which state it read — as any client that participates in the guard does.
        monkeypatch.delenv("AGENT_INBOX_HUB_TITLE")
        with TestClient(app=build_api(house, HUB)) as c:
            r = c.put("/hub", json={"title": rendered, "version": version})
            assert r.status_code == 409, r.text
            assert c.get("/").json()["title"] == "The Salt Club"

    def test_a_write_carrying_the_current_version_is_accepted(
        self, client: TestClient
    ) -> None:
        """The guard must not block ordinary writes, or clients will stop sending it."""
        version = client.get("/hub/settings").json()["version"]
        r = client.put("/hub", json={"title": "The Salt Club", "version": version})
        assert r.status_code == 200, r.text
