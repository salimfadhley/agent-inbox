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

from agent_mailbox import api as api_module
from agent_mailbox.api import IDENTITY_HEADER, build_api
from agent_mailbox.house import House
from agent_mailbox.mailbox import Mailbox
from agent_mailbox.store import InMemoryStore

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
    def test_the_federation_inbox_says_not_yet(self, client: TestClient) -> None:
        r = client.post(f"/actors/{ROSEMARY}/inbox", json={})
        assert r.status_code == 501
        assert "does not federate" in r.json()["detail"]


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
        from agent_mailbox.house import House
        from agent_mailbox.mailbox import Mailbox
        from agent_mailbox.policy import ProbeDetector, StandingResidents
        from agent_mailbox.store import InMemoryStore

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
        from agent_mailbox.api import PAGE

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

        from agent_mailbox.api import purge_forever

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

        from agent_mailbox.api import purge_forever

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

        from agent_mailbox.api import purge_forever

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

        from agent_mailbox.api import _complain_if_it_died

        async def dies() -> None:
            raise RuntimeError("the event loop went away")

        task = asyncio.create_task(dies())
        with contextlib.suppress(RuntimeError):
            await task
        with caplog.at_level(logging.CRITICAL, logger="agent_mailbox.api"):
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

        from agent_mailbox.api import _complain_if_it_died

        async def returns() -> None:
            return None

        task = asyncio.create_task(returns())
        await task
        with caplog.at_level(logging.CRITICAL, logger="agent_mailbox.api"):
            _complain_if_it_died(task)

        assert caplog.records
        assert "no longer running" in caplog.records[0].message.lower()

    async def test_shutdown_is_silent(self, caplog) -> None:
        """Cancellation is the one way it is meant to end. Crying wolf at every
        shutdown would train everyone to ignore the message that matters."""
        import asyncio
        import logging

        from agent_mailbox.api import _complain_if_it_died

        async def forever() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(forever())
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with caplog.at_level(logging.CRITICAL, logger="agent_mailbox.api"):
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

        from agent_mailbox.api import SETTLE_MINUTES, purge_forever

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

        from agent_mailbox.api import purge_forever

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

        from agent_mailbox.api import PurgeStatus, purge_forever

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

        from agent_mailbox.api import PurgeStatus, purge_forever

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
