"""The messaging rules, tested as pure functions.

One class per scenario in ``doc/messaging-rules.md``. No store, no clock, no I/O —
literals in, decisions out. That is the point of the split: the rules that have cost us
most in production are the ones that can now be checked by reading.
"""

from agent_inbox.records import ActorRecord, ObjectRecord
from agent_inbox.rules import (
    EVERYONE,
    expired_object_ids,
    expiring_threads,
    group_memberships,
    is_party_to,
    may_attach_to,
    recipients_of,
    resolve_audience,
    thread_members,
    thread_root,
    unread,
    visible_turns,
)
from agent_inbox.vocabulary import ActorType

ROSEMARY = "rosemary_nasrin"
TREVOR = "trevor_mahmood"
YITZHAK = "yitzhak_levin"
SAL = "sal"

ACTORS = (ROSEMARY, TREVOR, YITZHAK, SAL)
NO_GROUPS: dict[str, frozenset[str]] = {}


def note(
    ident: str,
    sender: str,
    to: tuple[str, ...] = (),
    *,
    cc: tuple[str, ...] = (),
    parent: str | None = None,
    body: str = "",
    when: str = "2026-07-24T12:00:00Z",
) -> ObjectRecord:
    return ObjectRecord(
        id=ident,
        attributed_to=sender,
        to=to,
        cc=cc,
        in_reply_to=parent,
        content=body,
        published=when,
    )


class TestScenario3Delivery:
    """Every actor addressed gets its own copy."""

    def test_direct_message_reaches_only_its_recipient(self) -> None:
        msg = note("m1", ROSEMARY, (TREVOR,))
        assert recipients_of(msg, ACTORS, NO_GROUPS) == {TREVOR}

    def test_cc_recipients_are_addressed_too(self) -> None:
        msg = note("m1", ROSEMARY, (TREVOR,), cc=(YITZHAK,))
        assert recipients_of(msg, ACTORS, NO_GROUPS) == {TREVOR, YITZHAK}

    def test_unknown_names_deliver_to_nobody_rather_than_raising(self) -> None:
        """Addressing is routing: a message to nobody is delivered to nobody."""
        msg = note("m1", ROSEMARY, ("nobody_here",))
        assert recipients_of(msg, ACTORS, NO_GROUPS) == frozenset()


class TestScenario6Groups:
    """A group is just an address, and you never get your own broadcast."""

    def test_everyone_reaches_the_whole_mailbox_except_the_sender(self) -> None:
        msg = note("m1", ROSEMARY, (EVERYONE,))
        assert recipients_of(msg, ACTORS, NO_GROUPS) == {TREVOR, YITZHAK, SAL}
        assert ROSEMARY not in recipients_of(msg, ACTORS, NO_GROUPS)

    def test_membership_comes_from_profiles_not_from_the_name(self) -> None:
        actors = (
            ActorRecord(name=ROSEMARY, profile={"groups": ["ops"]}),
            ActorRecord(name=TREVOR, profile={"groups": ["ops"]}),
            ActorRecord(name=YITZHAK, profile={"groups": ["legal"]}),
            ActorRecord(name="ops", actor_type=ActorType.GROUP),
        )
        memberships = group_memberships(actors)
        assert memberships["ops"] == {ROSEMARY, TREVOR}
        assert memberships["legal"] == {YITZHAK}

    def test_sender_excluded_from_a_group_it_belongs_to(self) -> None:
        memberships = {"ops": frozenset({ROSEMARY, TREVOR})}
        msg = note("m1", ROSEMARY, ("ops",))
        assert recipients_of(msg, ACTORS, memberships) == {TREVOR}

    def test_a_group_with_no_members_reaches_nobody(self) -> None:
        assert resolve_audience(("ops",), ACTORS, {"ops": frozenset()}) == frozenset()


class TestScenario4Peeking:
    """Peek never consumes; unread is a question about state."""

    def test_unread_lists_only_what_was_routed_to_you(self) -> None:
        objects = (
            note("m1", ROSEMARY, (TREVOR,)),
            note("m2", ROSEMARY, (YITZHAK,)),
        )
        assert [o.id for o in unread(objects, TREVOR, (), ACTORS, NO_GROUPS)] == ["m1"]

    def test_already_read_messages_drop_out(self) -> None:
        objects = (note("m1", ROSEMARY, (TREVOR,)),)
        assert unread(objects, TREVOR, ("m1",), ACTORS, NO_GROUPS) == ()

    def test_read_state_is_per_reader(self) -> None:
        """Trevor consuming his copy must not consume Yitzhak's."""
        objects = (note("m1", ROSEMARY, (TREVOR, YITZHAK)),)
        assert unread(objects, TREVOR, ("m1",), ACTORS, NO_GROUPS) == ()
        assert len(unread(objects, YITZHAK, (), ACTORS, NO_GROUPS)) == 1


class TestScenario5Threading:
    """Parent pointers, not thread labels."""

    def test_root_of_an_opening_message_is_itself(self) -> None:
        objects = (note("m1", ROSEMARY, (TREVOR,)),)
        assert thread_root(objects, "m1") == "m1"

    def test_root_is_found_through_a_chain_of_replies(self) -> None:
        objects = (
            note("m1", ROSEMARY, (TREVOR,)),
            note("m2", TREVOR, (ROSEMARY,), parent="m1"),
            note("m3", ROSEMARY, (TREVOR,), parent="m2"),
        )
        assert thread_root(objects, "m3") == "m1"
        assert [o.id for o in thread_members(objects, "m1")] == ["m1", "m2", "m3"]

    def test_a_missing_parent_starts_a_new_thread(self) -> None:
        """A reply whose parent has expired is a root, not an orphan."""
        objects = (note("m2", TREVOR, (ROSEMARY,), parent="gone"),)
        assert thread_root(objects, "m2") == "m2"

    def test_a_cycle_terminates(self) -> None:
        """Correct use cannot produce one; a corrupt store or a peer could."""
        objects = (
            note("m1", ROSEMARY, (TREVOR,), parent="m2"),
            note("m2", TREVOR, (ROSEMARY,), parent="m1"),
        )
        assert thread_root(objects, "m1") in {"m1", "m2"}


class TestScenario7Visibility:
    """You see the turns you are party to — never the whole thread."""

    OBJECTS = (
        note("m1", ROSEMARY, (EVERYONE,), body="pipeline down", when="...01"),
        note(
            "m2",
            ROSEMARY,
            (TREVOR,),
            parent="m1",
            body="my bad migration",
            when="...02",
        ),
        note(
            "m3", TREVOR, (ROSEMARY,), parent="m2", body="keep it quiet", when="...03"
        ),
    )

    def test_bystander_sees_only_the_broadcast(self) -> None:
        """The exact shape of a disclosure bug that reached production (0020)."""
        seen = visible_turns(self.OBJECTS, "m1", YITZHAK, ACTORS, NO_GROUPS)
        assert [o.content for o in seen] == ["pipeline down"]

    def test_participants_see_the_whole_conversation(self) -> None:
        for who in (ROSEMARY, TREVOR):
            seen = visible_turns(self.OBJECTS, "m1", who, ACTORS, NO_GROUPS)
            assert len(seen) == 3, f"{who} should see every turn"

    def test_a_stranger_sees_nothing(self) -> None:
        assert visible_turns(self.OBJECTS, "m1", "outsider", ACTORS, NO_GROUPS) == ()

    def test_absent_and_forbidden_are_indistinguishable(self) -> None:
        """Both empty, so nobody can probe which threads exist."""
        forbidden = visible_turns(self.OBJECTS, "m1", "outsider", ACTORS, NO_GROUPS)
        absent = visible_turns(
            self.OBJECTS, "no-such-thread", ROSEMARY, ACTORS, NO_GROUPS
        )
        assert forbidden == absent == ()

    def test_being_party_to_one_turn_grants_nothing_about_the_others(self) -> None:
        assert is_party_to(self.OBJECTS[0], YITZHAK, ACTORS, NO_GROUPS)
        assert not is_party_to(self.OBJECTS[1], YITZHAK, ACTORS, NO_GROUPS)


class TestScenario8Intrusion:
    """You cannot attach a turn to a conversation you cannot see."""

    OBJECTS = (
        note("m1", ROSEMARY, (TREVOR,), body="private"),
        note("m2", TREVOR, (ROSEMARY,), parent="m1"),
    )

    def test_a_participant_may_reply(self) -> None:
        assert may_attach_to(self.OBJECTS, TREVOR, "m1", ACTORS, NO_GROUPS)

    def test_an_outsider_may_not(self) -> None:
        assert not may_attach_to(self.OBJECTS, YITZHAK, "m1", ACTORS, NO_GROUPS)

    def test_a_new_thread_is_always_allowed(self) -> None:
        assert may_attach_to(self.OBJECTS, YITZHAK, None, ACTORS, NO_GROUPS)

    def test_an_unknown_parent_is_refused_like_a_forbidden_one(self) -> None:
        """Both clear the parent, so the answer is not an existence oracle.

        Allowing an unknown parent let a caller distinguish "real but not yours" from
        "no such thing" by reading its own successful response — the probe the
        visibility rules refuse to answer everywhere else. Found by outside review.
        """
        assert not may_attach_to(
            self.OBJECTS, YITZHAK, "never-existed", ACTORS, NO_GROUPS
        )
        assert not may_attach_to(self.OBJECTS, YITZHAK, "m1", ACTORS, NO_GROUPS)


class TestScenario9Expiry:
    """Mail expires by conversation, not by message."""

    def test_a_live_thread_survives_however_old_its_root(self) -> None:
        """Mission 0016: per-message expiry decapitated live conversations."""
        objects = (
            note("m1", ROSEMARY, (TREVOR,), when="2026-07-01T00:00:00Z"),
            note("m2", TREVOR, (ROSEMARY,), parent="m1", when="2026-07-24T00:00:00Z"),
        )
        assert expired_object_ids(objects, "2026-07-10T00:00:00Z") == frozenset()

    def test_an_idle_thread_is_removed_whole(self) -> None:
        objects = (
            note("m1", ROSEMARY, (TREVOR,), when="2026-06-01T00:00:00Z"),
            note("m2", TREVOR, (ROSEMARY,), parent="m1", when="2026-06-02T00:00:00Z"),
        )
        assert expired_object_ids(objects, "2026-07-10T00:00:00Z") == {"m1", "m2"}

    def test_threads_expire_independently(self) -> None:
        objects = (
            note("old1", ROSEMARY, (TREVOR,), when="2026-06-01T00:00:00Z"),
            note("new1", ROSEMARY, (TREVOR,), when="2026-07-24T00:00:00Z"),
        )
        assert expired_object_ids(objects, "2026-07-10T00:00:00Z") == {"old1"}

    def test_nothing_stored_expires_nothing(self) -> None:
        assert expired_object_ids((), "2026-07-10T00:00:00Z") == frozenset()


class TestPurity:
    """The rules must stay free of hidden inputs — that is what makes them checkable."""

    def test_rules_take_no_clock(self) -> None:
        """Expiry is given a cutoff, so it can be tested at any date."""
        import inspect

        assert "cutoff" in inspect.signature(expired_object_ids).parameters

    def test_repeated_calls_agree(self) -> None:
        objects = TestScenario7Visibility.OBJECTS
        first = visible_turns(objects, "m1", YITZHAK, ACTORS, NO_GROUPS)
        second = visible_turns(objects, "m1", YITZHAK, ACTORS, NO_GROUPS)
        assert first == second


class TestRetroactiveMembership:
    """Joining a group must not grant access to what it was sent before you arrived.

    Found by an outside review of M1. Group membership was resolved when a thread was
    *read* rather than when a message was *sent*, and since an agent declares its own
    groups, anyone could add themselves to a group and retroactively read its history —
    then attach turns to private threads rooted in it. The 0020 disclosure, through a
    different door.

    The fix restores ActivityStreams: `to` holds the resolved recipients, decided at
    send time. Storing the unresolved audience there was our deviation, and the
    deviation was the bug.
    """

    def test_resolution_is_a_snapshot_not_a_query(self) -> None:
        """The rule itself is unchanged — what matters is *when* it is applied."""
        present = ("rosemary_nasrin", "trevor_mahmood")
        at_send = resolve_audience(("ops",), present, {"ops": frozenset(present)})
        assert at_send == {"rosemary_nasrin", "trevor_mahmood"}

        # a later arrival changes the membership map, but not a message already sent
        later = (*present, "yitzhak_levin")
        at_read = resolve_audience(("ops",), later, {"ops": frozenset(later)})
        assert "yitzhak_levin" in at_read
        assert "yitzhak_levin" not in at_send

    def test_a_stored_message_names_actors_not_groups(self) -> None:
        """Once `to` holds actors, membership cannot change who a message reached."""
        already_resolved = note("m1", ROSEMARY, (TREVOR,))
        for memberships in ({}, {"ops": frozenset({YITZHAK})}):
            assert recipients_of(already_resolved, ACTORS, memberships) == {TREVOR}


class TestObservationRules:
    """Traffic and flow — the operator's numbers, computed purely from records.

    These feed the console dashboard. They take no clock (``since`` is passed in), so
    the same messages always give the same answer.
    """

    def test_traffic_is_counted_per_day(self) -> None:
        from agent_inbox.rules import traffic_by_day

        msgs = (
            note("a", ROSEMARY, (TREVOR,), when="2026-07-24T09:00:00Z"),
            note("b", ROSEMARY, (TREVOR,), when="2026-07-24T17:00:00Z"),
            note("c", TREVOR, (ROSEMARY,), when="2026-07-25T08:00:00Z"),
        )
        assert traffic_by_day(msgs) == (("2026-07-24", 2), ("2026-07-25", 1))

    def test_since_excludes_older_traffic(self) -> None:
        from agent_inbox.rules import traffic_by_day

        msgs = (
            note("a", ROSEMARY, (TREVOR,), when="2026-07-01T00:00:00Z"),
            note("b", ROSEMARY, (TREVOR,), when="2026-07-24T00:00:00Z"),
        )
        assert traffic_by_day(msgs, since="2026-07-10T00:00:00Z") == (
            ("2026-07-24", 1),
        )

    def test_flow_counts_one_edge_per_recipient(self) -> None:
        """A fan-out to three is three edges, not one — the honest reading."""
        from agent_inbox.rules import flow_edges

        msgs = (note("a", ROSEMARY, (TREVOR, YITZHAK), cc=(SAL,)),)
        edges = dict(((frm, to), n) for frm, to, n in flow_edges(msgs))
        assert edges == {
            (ROSEMARY, TREVOR): 1,
            (ROSEMARY, YITZHAK): 1,
            (ROSEMARY, SAL): 1,
        }

    def test_flow_ignores_a_copy_of_your_own_broadcast(self) -> None:
        """Self-exclusion holds here too: talking to yourself is not correspondence."""
        from agent_inbox.rules import flow_edges

        msgs = (note("a", ROSEMARY, (ROSEMARY, TREVOR)),)
        assert flow_edges(msgs) == ((ROSEMARY, TREVOR, 1),)

    def test_flow_orders_busiest_first(self) -> None:
        from agent_inbox.rules import flow_edges

        msgs = (
            note("a", ROSEMARY, (TREVOR,)),
            note("b", ROSEMARY, (TREVOR,)),
            note("c", ROSEMARY, (YITZHAK,)),
        )
        assert flow_edges(msgs)[0] == (ROSEMARY, TREVOR, 2)

    def test_correspondents_count_both_directions_as_one_relationship(self) -> None:
        from agent_inbox.rules import correspondents

        msgs = (
            note("a", ROSEMARY, (TREVOR,)),
            note("b", TREVOR, (ROSEMARY,)),
            note("c", ROSEMARY, (YITZHAK,)),
        )
        assert dict(correspondents(msgs, ROSEMARY)) == {TREVOR: 2, YITZHAK: 1}


class TestExpiringThreads:
    """The dry run, and the cases where a purge could take something it should not.

    Expiry leaves no tombstone: afterwards a purged conversation is indistinguishable
    from one that never existed. There is no undo and no record, so every one of these
    is a case where being wrong is permanent.
    """

    CUTOFF = "2026-07-10T00:00:00Z"

    def _obj(self, ident, published, parent=None, summary="s"):
        return ObjectRecord(
            id=ident,
            attributed_to="rosemary_nasrin",
            to=("trevor_mahmood",),
            cc=(),
            content="x",
            summary=summary,
            published=published,
            in_reply_to=parent,
        )

    def test_a_live_thread_is_kept_however_old_its_root(self) -> None:
        """The bug this whole area exists for: old root, fresh reply, keep it all."""
        objects = (
            self._obj("root", "2026-07-01T00:00:00Z"),
            self._obj("reply", "2026-07-20T00:00:00Z", parent="root"),
        )
        assert expiring_threads(objects, self.CUTOFF) == ()
        assert expired_object_ids(objects, self.CUTOFF) == frozenset()

    def test_an_idle_thread_goes_whole_and_is_described(self) -> None:
        objects = (
            self._obj("root", "2026-07-01T00:00:00Z", summary="DNS"),
            self._obj("reply", "2026-07-02T00:00:00Z", parent="root"),
        )
        (doomed,) = expiring_threads(objects, self.CUTOFF)
        assert doomed.subject == "DNS", "the operator needs to know what is going"
        assert doomed.messages == 2
        assert doomed.last_published == "2026-07-02T00:00:00Z"
        assert set(doomed.ids) == {"root", "reply"}

    def test_a_thread_landing_exactly_on_the_cutoff_is_kept(self) -> None:
        """Boundary equality is where a `<` rule fails, and it had never been tested."""
        objects = (self._obj("solo", self.CUTOFF),)
        assert expiring_threads(objects, self.CUTOFF) == ()

    def test_an_orphaned_reply_becomes_its_own_root(self) -> None:
        """A parent outside the store must not miscompute the thread it belongs to."""
        recent = (self._obj("orphan", "2026-07-20T00:00:00Z", parent="long_gone"),)
        assert expiring_threads(recent, self.CUTOFF) == ()

        old = (self._obj("orphan", "2026-07-01T00:00:00Z", parent="long_gone"),)
        (doomed,) = expiring_threads(old, self.CUTOFF)
        assert doomed.ids == ("orphan",)

    def test_a_cycle_terminates(self) -> None:
        """Impossible from correct use; a corrupt store could still produce one.

        A purge that spins is worse than a purge that is wrong, because the hub stops.
        """
        objects = (
            self._obj("a", "2026-07-01T00:00:00Z", parent="b"),
            self._obj("b", "2026-07-01T00:00:00Z", parent="a"),
        )
        doomed = expiring_threads(objects, self.CUTOFF)
        assert sum(t.messages for t in doomed) == 2

    def test_the_preview_and_the_purge_never_disagree(self) -> None:
        """`expired_object_ids` is the preview with the descriptions thrown away.

        Two functions each working out their own answer would agree until they did not,
        and the moment they disagreed would be the moment somebody had trusted the
        preview and pressed the button.
        """
        objects = (
            self._obj("live_root", "2026-07-01T00:00:00Z"),
            self._obj("live_reply", "2026-07-20T00:00:00Z", parent="live_root"),
            self._obj("dead_root", "2026-07-01T00:00:00Z"),
            self._obj("dead_reply", "2026-07-03T00:00:00Z", parent="dead_root"),
            self._obj("orphan", "2026-07-02T00:00:00Z", parent="vanished"),
        )
        from_preview = {
            i for t in expiring_threads(objects, self.CUTOFF) for i in t.ids
        }
        assert from_preview == expired_object_ids(objects, self.CUTOFF)
        assert from_preview == {"dead_root", "dead_reply", "orphan"}

    def test_roots_are_resolved_once_not_once_per_message(self) -> None:
        """NFR-001: purging was O(n^2) and took 4.5 s on 10,000 messages.

        `thread_root` rebuilt its index on every call and expiry called it twice per
        message. This asserts the shape rather than a wall-clock threshold, because a
        threshold alone passes on a fast machine and leaves the quadratic for someone
        else's machine to find.
        """
        import time

        def store(n: int):
            out, prev = [], None
            for i in range(n):
                root = i % 5 == 0
                out.append(
                    self._obj(
                        f"m{i}",
                        f"2026-07-{(i % 20) + 1:02d}T00:00:00Z",
                        parent=None if root else prev,
                    )
                )
                prev = f"m{i}"
            return tuple(out)

        def timed(n: int) -> float:
            objects = store(n)
            start = time.perf_counter()
            expired_object_ids(objects, self.CUTOFF)
            return time.perf_counter() - start

        timed(500)  # warm
        small, large = timed(1000), timed(4000)
        # Four times the messages must not cost anything like sixteen times the work.
        assert large < small * 8, (
            f"1k took {small * 1000:.1f} ms, 4k took {large * 1000:.1f} ms — "
            "expiry looks quadratic again"
        )
