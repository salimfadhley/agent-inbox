"""The thread as a reader sees it: nesting, a reply on every message, who is human.

**Asserted against the rendered page, never a helper.** A console test that exercises a
helper cannot tell a working guard from a missing call — that has already happened in
this repository and the test was green and worthless. So every assertion here goes
through the route.

The one exception is `thread_tree`, which is pure and is tested directly *as well*: it
is the ordering logic, and pinning it separately means a rendering change cannot quietly
alter the shape of a conversation.
"""

from typing import Any

from litestar.testing import TestClient

from agent_inbox.client import Config, HubClient
from agent_inbox.console import SESSION_COOKIE, build_console, thread_tree

HUB = "http://hub.invalid"
HUMAN = "admin"
AGENT = "rosemary_nasrin"


def turn(oid: str, frm: str, parent: str | None, when: str, body: str = "x") -> dict:
    made: dict[str, Any] = {
        "id": f"{HUB}/objects/{oid}",
        "attributedTo": f"{HUB}/actors/{frm}",
        "summary": f"subject {oid}",
        "content": body,
        "published": when,
    }
    if parent:
        made["inReplyTo"] = f"{HUB}/objects/{parent}"
    return made


class Hub(HubClient):
    """A hub with one thread in it, and a directory that knows who is a person."""

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        super().__init__(Config(hub=HUB, name="console"))
        self.turns = turns

    def hub_info(self) -> dict[str, Any]:
        return {"name": "testhub", "version": "1.0.0", "authenticated": False}

    def observe_thread(self, object_id: str) -> dict[str, Any]:
        return {"items": self.turns}

    def observe_object(self, object_id: str) -> dict[str, Any]:
        return {"readBy": []}

    def list_agents(self) -> dict[str, Any]:
        return {
            "items": [
                {"preferredUsername": HUMAN, "type": "Person"},
                {"preferredUsername": AGENT, "type": "Service"},
            ]
        }

    def with_session(self, session: str) -> Hub:
        return self

    def acting_as(self, name: str, session: str) -> Hub:
        return self

    def whoami(self) -> str:
        return HUMAN


def page(turns: list[dict[str, Any]], signed_in: bool = True) -> str:
    with TestClient(app=build_console(Hub(turns))) as console:
        cookies = {SESSION_COOKIE: "a-session"} if signed_in else {}
        # The leaf id, which is what the console links to and routes on.
        return console.get("/message/a", cookies=cookies).text


class TestNestingIsDerivedFromInReplyTo:
    def test_a_reply_is_rendered_inside_its_parent(self) -> None:
        rendered = page([turn("a", AGENT, None, "1"), turn("b", HUMAN, "a", "2")])

        assert 'class="nest"' in rendered, "a reply was not nested under its parent"

    def test_a_flat_thread_nests_nothing(self) -> None:
        """The paired negative. Without it the test above would pass on a console that
        indented every message it was given."""
        rendered = page([turn("a", AGENT, None, "1"), turn("b", HUMAN, None, "2")])

        assert 'class="nest"' not in rendered

    def test_depth_is_bounded(self) -> None:
        """A reddit thread can run twenty deep; a console column cannot. Past the cap
        replies keep the deepest indent rather than walking off the edge and taking
        their reply control with them."""
        chain = [turn("t0", AGENT, None, "0")]
        chain += [turn(f"t{n}", AGENT, f"t{n - 1}", str(n)) for n in range(1, 15)]

        depths = [depth for _, depth, _ in thread_tree(chain)]

        assert max(depths) <= 6
        assert depths[:4] == [0, 1, 2, 3], "nesting stopped working entirely"

    def test_every_turn_is_shown_even_in_a_cycle(self) -> None:
        """A malformed thread must not silently lose a message. Two turns naming each
        other is not something the hub should produce, but a view that quietly omitted
        one would be worse than a view that looks odd."""
        cyclic = [turn("a", AGENT, "b", "1"), turn("b", AGENT, "a", "2")]

        assert len(thread_tree(cyclic)) == 2


class TestAMissingParentStaysLegible:
    def test_an_orphan_says_its_parent_is_absent(self) -> None:
        """The parent may be on another hub, may be one the reader cannot see, or —
        once retraction ships — may be a message whose body is gone. Presenting it as
        the start of a conversation would be a lie about who spoke first."""
        rendered = page([turn("b", HUMAN, "missing", "2")])

        assert "not shown here" in rendered

    def test_a_present_parent_is_not_labelled_that_way(self) -> None:
        rendered = page([turn("a", AGENT, None, "1"), turn("b", HUMAN, "a", "2")])

        assert "not shown here" not in rendered


class TestAHumansMessageIsVisiblyAHumans:
    def test_a_human_sender_is_marked(self) -> None:
        rendered = page([turn("a", HUMAN, None, "1")])

        assert 'class="human"' in rendered

    def test_an_agent_sender_is_not(self) -> None:
        """The paired negative, and the distinction the marker exists for."""
        rendered = page([turn("a", AGENT, None, "1")])

        assert 'class="human"' not in rendered

    def test_the_mark_does_not_read_as_authority(self) -> None:
        """FR-007 as a rendering rule. It says *who is speaking*, never *listen to this
        one* — a badge saying "operator" or "admin" would turn a fact into an order."""
        rendered = page([turn("a", HUMAN, None, "1")]).lower()

        for shouted in ("operator", "authority", "official", "important"):
            assert shouted not in rendered, f"the human marker reads as {shouted!r}"


class TestAReplyControlOnEveryMessage:
    def test_each_message_carries_its_own(self) -> None:
        """FR-004 is *reply to any individual message*. One control on the thread would
        make every reply a sibling and nesting impossible."""
        rendered = page([turn("a", AGENT, None, "1"), turn("b", AGENT, None, "2")])

        assert rendered.count("/reply'") == 2

    def test_it_posts_to_the_message_it_sits_under(self) -> None:
        rendered = page([turn("a", AGENT, None, "1")])

        assert "/message/a/reply" in rendered

    def test_nothing_is_offered_to_somebody_not_signed_in(self) -> None:
        """Not a decision about who may post — the hub refuses that regardless
        (NFR-002). This only avoids offering a control that cannot work."""
        rendered = page([turn("a", AGENT, None, "1")], signed_in=False)

        assert "/reply" not in rendered


class TestPressingTheReplyButtonActuallyWorks:
    """Reported by the owner, 2026-08-05: **Send Reply gave a 404.**

    The route existed and was never added to the console's `route_handlers`, so it was
    dead code with a button pointing at it. Every test in this file passed anyway,
    because they all assert the control *renders* — not that pressing it does anything.
    That is the same shape as the API prompt route earlier today, which was also written
    and never registered, and it is why a rendering test is not a substitute for
    exercising the thing it renders.
    """

    def test_a_reply_is_accepted_and_sent(self) -> None:
        sent: list[tuple[str, str]] = []

        class Replying(Hub):
            def reply_message(
                self, object_id: str, body: str, subject: str | None = None
            ) -> dict[str, Any]:
                sent.append((object_id, body))
                return {"id": f"{HUB}/objects/new"}

        with TestClient(
            app=build_console(Replying([turn("a", AGENT, None, "1")]))
        ) as c:
            answer = c.post(
                "/message/a/reply",
                data={"body": "my reply"},
                cookies={SESSION_COOKIE: "a-session"},
                follow_redirects=False,
            )

        assert answer.status_code != 404, "the reply route is not registered"
        assert answer.status_code == 303, answer.status_code
        assert sent == [("a", "my reply")], "the reply never reached the hub"

    def test_it_returns_to_the_thread_rather_than_rendering(self) -> None:
        """A reply is a POST. A page that re-submitted it on reload would send the
        message twice, which is not something a reader can undo."""

        class Replying(Hub):
            def reply_message(
                self, object_id: str, body: str, subject: str | None = None
            ) -> dict[str, Any]:
                return {"id": f"{HUB}/objects/new"}

        with TestClient(
            app=build_console(Replying([turn("a", AGENT, None, "1")]))
        ) as c:
            answer = c.post(
                "/message/a/reply",
                data={"body": "my reply"},
                cookies={SESSION_COOKIE: "a-session"},
                follow_redirects=False,
            )

        assert answer.headers["location"] == "/message/a"

    def test_an_empty_reply_sends_nothing(self) -> None:
        """The paired negative. An accidental submit must not post a blank message into
        somebody's thread."""
        sent: list[str] = []

        class Replying(Hub):
            def reply_message(
                self, object_id: str, body: str, subject: str | None = None
            ) -> dict[str, Any]:
                sent.append(body)
                return {}

        with TestClient(
            app=build_console(Replying([turn("a", AGENT, None, "1")]))
        ) as c:
            c.post(
                "/message/a/reply",
                data={"body": "   "},
                cookies={SESSION_COOKIE: "a-session"},
                follow_redirects=False,
            )

        assert sent == []


class TestComposeSuggestsNames:
    """Reported by the owner as a regression, 2026-08-05. **It was not one** — the
    console has never had this; `datalist` appears nowhere in the file's history and the
    `To:` input has not changed since long before today. What they were seeing was the
    browser's own form history, which is per-origin and was lost when the hub moved.

    A fair thing to expect, so it exists now. A `<datalist>` rather than script: the
    browser already does typeahead better than anything written here would, the console
    has no build step, and with the list unavailable the field degrades to the ordinary
    text input it was yesterday.
    """

    @staticmethod
    def _console(actors: list[dict] | None = None, fail: bool = False) -> TestClient:

        from agent_inbox.client import ClientError, Config, HubClient
        from agent_inbox.console import build_console

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub=HUB, name="console"))

            def hub_info(self) -> dict[str, Any]:
                return {"name": "t", "version": "1.0.0", "authenticated": False}

            def with_session(self, session: str | None) -> Stub:
                return self

            def acting_as(self, name: str, session: str) -> Stub:
                return self

            def whoami(self) -> str:
                return HUMAN

            def list_agents(self) -> dict[str, Any]:
                if fail:
                    raise ClientError("the hub is not answering")
                return {"items": actors or []}

        return TestClient(app=build_console(Stub()))

    def test_every_name_on_the_hub_is_offered(self) -> None:
        who = [
            {"preferredUsername": AGENT, "type": "Service"},
            {"preferredUsername": HUMAN, "type": "Person"},
        ]

        with self._console(who) as console:
            page = console.get("/compose", cookies={SESSION_COOKIE: "s"}).text

        assert 'list="who"' in page, "the field is not wired to a list"
        assert f'<option value="{AGENT}">' in page
        assert f'<option value="{HUMAN}">' in page, "humans are addressable too"

    def test_everyone_is_offered_and_offered_last(self) -> None:
        """The address people forget exists — and deliberately at the bottom, because a
        broadcast costs every recipient a turn none of them can decline."""
        with self._console([{"preferredUsername": AGENT}]) as console:
            page = console.get("/compose", cookies={SESSION_COOKIE: "s"}).text

        assert '<option value="everyone">' in page
        assert page.index(f'value="{AGENT}"') < page.index('value="everyone"')

    def test_a_hub_that_will_not_answer_costs_the_suggestions_not_the_page(
        self,
    ) -> None:
        """The paired negative. Suggestions are a convenience; the compose form is not,
        and a reader who cannot send mail because a nicety failed is worse off than one
        typing a name in full."""
        with self._console(fail=True) as console:
            answer = console.get("/compose", cookies={SESSION_COOKIE: "s"})

        assert answer.status_code == 200, "a failed lookup broke the compose page"
        assert 'name="to"' in answer.text, "the field itself is gone"


class TestWithdrawingFromTheConsole:
    """Retraction shipped with an API and no control; the owner asked for both, with a
    confirmation step.

    The tests are about the three ways this could be wrong: the button not being wired
    (which has happened four times in this codebase), a withdrawn message still showing
    its body, and the control appearing where it should not.
    """

    @staticmethod
    def _console(turns: list[dict], sink: list[tuple[str, str]] | None = None):

        from agent_inbox.client import Config, HubClient
        from agent_inbox.console import build_console

        class Stub(HubClient):
            def __init__(self) -> None:
                super().__init__(Config(hub=HUB, name="console"))

            def hub_info(self) -> dict[str, Any]:
                return {"name": "t", "version": "1.0.0", "authenticated": False}

            def observe_thread(self, object_id: str) -> dict[str, Any]:
                return {"items": turns}

            def observe_object(self, object_id: str) -> dict[str, Any]:
                return {"readBy": []}

            def list_agents(self) -> dict[str, Any]:
                return {"items": []}

            def with_session(self, session: str) -> Stub:
                return self

            def acting_as(self, name: str, session: str) -> Stub:
                return self

            def whoami(self) -> str:
                return HUMAN

            def retract_message(self, object_id: str) -> dict[str, Any]:
                if sink is not None:
                    sink.append(("message", object_id))
                return {"retracted": True}

            def retract_thread(self, object_id: str) -> dict[str, Any]:
                if sink is not None:
                    sink.append(("thread", object_id))
                return {"retracted": [object_id], "refused": []}

        return TestClient(app=build_console(Stub()))

    def test_pressing_withdraw_reaches_the_hub(self) -> None:
        """The wiring, proved separately from the rendering — a control that renders and
        does nothing has shipped from this project four times."""
        sink: list[tuple[str, str]] = []
        with self._console([turn("a", AGENT, None, "1")], sink) as c:
            answer = c.post(
                "/message/a/retract",
                cookies={SESSION_COOKIE: "s"},
                follow_redirects=False,
            )

        assert answer.status_code == 303, answer.status_code
        assert sink == [("message", "a")]

    def test_pressing_withdraw_the_thread_reaches_the_hub(self) -> None:
        sink: list[tuple[str, str]] = []
        with self._console([turn("a", AGENT, None, "1")], sink) as c:
            answer = c.post(
                "/message/a/retract-thread",
                cookies={SESSION_COOKIE: "s"},
                follow_redirects=False,
            )

        assert answer.status_code == 303
        assert sink == [("thread", "a")]

    def test_a_withdrawn_message_shows_no_body(self) -> None:
        """The point of the whole feature. If the body survives the tombstone, the
        retraction happened and the console undid it."""
        gone = turn("a", AGENT, None, "1", body="the words that were withdrawn")
        gone["retracted"] = {"by": HUMAN, "at": "2026-08-06"}

        with self._console([gone]) as c:
            page = c.get("/message/a", cookies={SESSION_COOKIE: "s"}).text

        assert "the words that were withdrawn" not in page
        # Asserted on the rendered *body element*, not on the page. The first version
        # searched the whole document and passed with the tombstone renderer deleted,
        # because the confirmation prose contains the word `[deleted]` too — caught by
        # the removal proof, which is the only reason it is not still passing.
        body = page.split('class="b gone">', 1)
        assert len(body) == 2, "the body was not rendered as withdrawn"
        assert body[1].startswith("[deleted]")

    def test_an_ordinary_message_still_shows_its_body(self) -> None:
        """The paired positive: a renderer that hid every body would pass the test
        above."""
        with self._console([turn("a", AGENT, None, "1", body="perfectly fine")]) as c:
            page = c.get("/message/a", cookies={SESSION_COOKIE: "s"}).text

        assert "perfectly fine" in page

    def test_a_body_that_merely_reads_deleted_is_not_marked_withdrawn(self) -> None:
        """The mark is on the record, not in the text — somebody writing `[deleted]` as
        a joke has not retracted anything, and must not be shown as having done so."""
        joker = turn("a", AGENT, None, "1", body="[deleted]")

        with self._console([joker]) as c:
            page = c.get("/message/a", cookies={SESSION_COOKIE: "s"}).text

        assert "gone" not in page.split('class="b')[1][:40], (
            "an ordinary message was styled as withdrawn"
        )

    def test_the_control_is_gone_once_the_message_is(self) -> None:
        """Offering to withdraw something already withdrawn is an invitation to wonder
        whether the first one worked."""
        gone = turn("a", AGENT, None, "1")
        gone["retracted"] = {"by": HUMAN, "at": "2026-08-06"}

        with self._console([gone]) as c:
            page = c.get("/message/a", cookies={SESSION_COOKIE: "s"}).text

        assert "/message/a/retract'" not in page

    def test_nothing_is_offered_to_somebody_not_signed_in(self) -> None:
        with self._console([turn("a", AGENT, None, "1")]) as c:
            page = c.get("/message/a").text

        assert "/retract" not in page

    def test_the_confirmation_says_it_cannot_be_undone(self) -> None:
        """The reason the control is behind a `<details>` at all: the moment somebody
        most wants this is the moment they should be slowed down."""
        with self._console([turn("a", AGENT, None, "1")]) as c:
            page = c.get("/message/a", cookies={SESSION_COOKIE: "s"}).text

        assert "cannot be undone" in page
        assert "not withdrawn" in page, "the local-only scope is not stated"
