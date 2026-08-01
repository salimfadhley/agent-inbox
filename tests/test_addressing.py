"""Addressing: ``name@hub``, and the promise ``@local`` makes.

The parsing tests are pure. The round-trip tests run against both backends, and answer
the plainest question that can be asked of a mailbox: can ``a@local`` write to
``b@local``, and can ``b@local`` reply?
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_inbox.addressing import LOCAL, Address, local_name, parse, split_recipients
from agent_inbox.exceptions import (
    AddressError,
    DeliversToNobody,
    MailboxError,
    MalformedAddress,
    NameUnavailable,
    NoSuchMessage,
    RemoteMailbox,
    UnknownActor,
    UnknownRecipient,
)
from agent_inbox.mailbox import Mailbox
from agent_inbox.sqlite_store import SqliteStore
from agent_inbox.store import InMemoryStore


@pytest.fixture(params=("in_memory", "sqlite"))
async def mailbox(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Mailbox]:
    if request.param == "in_memory":
        yield Mailbox(InMemoryStore())
    else:
        async with SqliteStore(tmp_path / "mail.db") as store:
            yield Mailbox(store)


class TestParsing:
    def test_a_full_address_splits_into_name_and_hub(self) -> None:
        assert parse("trevor_mahmood@local") == Address("trevor_mahmood", "local")

    def test_a_bare_name_means_this_mailbox(self) -> None:
        """Bare names are the common case; meaning anything else would be a trap."""
        assert parse("trevor_mahmood") == Address("trevor_mahmood", LOCAL)

    def test_addresses_render_back(self) -> None:
        assert str(parse("trevor_mahmood")) == "trevor_mahmood@local"

    def test_case_is_normalised(self) -> None:
        assert parse("Trevor_Mahmood@LOCAL") == Address("trevor_mahmood", "local")

    @pytest.mark.parametrize(
        ("bad", "because"),
        [
            ("", "empty"),
            ("@local", "no name"),
            ("trevor@", "no hub"),
            ("a@b@c", "more than one"),
        ],
    )
    def test_malformed_addresses_say_what_is_wrong(
        self, bad: str, because: str
    ) -> None:
        with pytest.raises(AddressError, match=because):
            parse(bad)


class TestNonEgress:
    """``@local`` is a guarantee, not a default."""

    def test_local_can_never_leave(self) -> None:
        assert parse("trevor_mahmood@local").guarantees_non_egress

    def test_naming_the_hub_directly_carries_no_such_promise(self) -> None:
        """Equivalent for delivery today, but a hub's own name means something abroad.

        Only the literal `@local` is a promise, which is what makes containment
        checkable by reading the address.
        """
        assert not parse("trevor_mahmood@workshop").guarantees_non_egress

    def test_a_hub_answers_to_both_its_own_name_and_local(self) -> None:
        assert parse("t@local").is_local_to("workshop")
        assert parse("t@workshop").is_local_to("workshop")
        assert not parse("t@elsewhere").is_local_to("workshop")

    def test_another_mailbox_is_refused_loudly(self) -> None:
        """Not silently dropped: an agent must learn immediately.

        Federation later turns this error into a delivery, rather than changing what
        silence meant.
        """
        with pytest.raises(AddressError, match="does not carry mail between hubs"):
            local_name("trevor_mahmood@elsewhere")


class TestRoundTrip:
    """Can a@local message b@local, and can b@local reply?"""

    async def test_a_at_local_messages_b_at_local_and_b_replies(
        self, mailbox: Mailbox
    ) -> None:
        await mailbox.join("rosemary_nasrin")
        await mailbox.join("trevor_mahmood")

        sent = await mailbox.send(
            "rosemary_nasrin@local",
            "trevor_mahmood@local",
            "the payment suite fails one run in five. Any idea?",
            subject="flaky tests",
        )

        waiting = await mailbox.peek("trevor_mahmood@local")
        assert [m.summary for m in waiting] == ["flaky tests"]
        assert waiting[0].id == sent.id

        got = await mailbox.read("trevor_mahmood@local", sent.id)
        assert got.content.startswith("the payment suite")

        reply = await mailbox.reply(
            "trevor_mahmood@local", sent.id, "fixture ordering — I'll push a fix"
        )
        assert reply.to == ("rosemary_nasrin",)
        assert reply.in_reply_to == sent.id
        assert reply.summary == "Re: flaky tests"

        back = await mailbox.peek("rosemary_nasrin@local")
        assert [m.content for m in back] == ["fixture ordering — I'll push a fix"]

        thread = await mailbox.thread("rosemary_nasrin@local", sent.id)
        assert [m.summary for m in thread] == ["flaky tests", "Re: flaky tests"]

    async def test_addressed_and_bare_forms_are_the_same_actor(
        self, mailbox: Mailbox
    ) -> None:
        """`b` and `b@local` must never become two mailboxes."""
        await mailbox.join("rosemary_nasrin")
        await mailbox.join("trevor_mahmood")

        await mailbox.send("rosemary_nasrin", "trevor_mahmood@local", "one")
        await mailbox.send("rosemary_nasrin@local", "trevor_mahmood", "two")

        assert len(await mailbox.peek("trevor_mahmood")) == 2
        assert len(await mailbox.peek("trevor_mahmood@local")) == 2

    async def test_a_group_can_be_addressed_with_a_hub(self, mailbox: Mailbox) -> None:
        await mailbox.join("rosemary_nasrin")
        await mailbox.join("trevor_mahmood")
        await mailbox.send("rosemary_nasrin", "everyone@local", "all hands")
        assert len(await mailbox.peek("trevor_mahmood")) == 1

    async def test_sending_off_this_mailbox_is_refused(self, mailbox: Mailbox) -> None:
        await mailbox.join("rosemary_nasrin")
        with pytest.raises(AddressError, match="does not carry mail between hubs"):
            await mailbox.send("rosemary_nasrin", "someone@another_hub", "hello")

    async def test_a_hub_with_its_own_name_still_answers_to_local(
        self, tmp_path: Path
    ) -> None:
        mailbox = Mailbox(InMemoryStore(), hub_name="workshop")
        await mailbox.join("rosemary_nasrin")
        await mailbox.join("trevor_mahmood")

        await mailbox.send(
            "rosemary_nasrin@workshop", "trevor_mahmood@local", "either form works"
        )
        assert len(await mailbox.peek("trevor_mahmood@workshop")) == 1
        assert mailbox.address_of("trevor_mahmood") == "trevor_mahmood@local"


class TestDistinctFailures:
    """Different failures, different types — the remedies are different too."""

    async def test_a_mistyped_local_name_is_refused_not_silently_dropped(
        self, mailbox: Mailbox
    ) -> None:
        """The worst outcome for an agent is a send that succeeds and reaches nobody.

        It cannot notice the silence, and waits for a reply that is never coming.
        """
        await mailbox.join("rosemary_nasrin")
        with pytest.raises(UnknownRecipient, match="nobody here is called"):
            await mailbox.send("rosemary_nasrin", "trevor_mahmoood", "typo")

    async def test_an_unknown_local_name_and_a_remote_one_are_different_errors(
        self, mailbox: Mailbox
    ) -> None:
        """One says "fix the name"; the other says "this needs federation"."""
        await mailbox.join("rosemary_nasrin")

        with pytest.raises(UnknownRecipient) as local_miss:
            await mailbox.send("rosemary_nasrin", "nobody_here", "x")
        with pytest.raises(RemoteMailbox) as remote:
            await mailbox.send("rosemary_nasrin", "somebody@another_hub", "x")

        assert local_miss.value.code == "unknown_recipient"
        assert remote.value.code == "remote_mailbox"
        assert not isinstance(local_miss.value, RemoteMailbox)
        assert not isinstance(remote.value, UnknownRecipient)

    async def test_a_malformed_address_is_neither(self, mailbox: Mailbox) -> None:
        await mailbox.join("rosemary_nasrin")
        with pytest.raises(MalformedAddress) as exc:
            await mailbox.send("rosemary_nasrin", "a@b@c", "x")
        assert exc.value.code == "malformed_address"

    async def test_all_three_are_catchable_as_one(self, mailbox: Mailbox) -> None:
        """Catch AddressError when the difference does not matter."""
        await mailbox.join("rosemary_nasrin")
        for bad in ("nobody_here", "somebody@another_hub", "a@b@c"):
            with pytest.raises(AddressError):
                await mailbox.send("rosemary_nasrin", bad, "x")

    async def test_an_empty_group_reaches_nobody_and_says_so(
        self, mailbox: Mailbox
    ) -> None:
        """A group everyone has left is not a typo, but it is still a dead end.

        This used to succeed with an empty `to`. The name is real, so it is not
        `unknown_recipient` — but the caller was handed an object id indistinguishable
        from a delivery, for a message nobody would ever read.
        """
        await mailbox.join("rosemary_nasrin")
        await mailbox.update_profile("rosemary_nasrin", {"groups": ["ops"]})
        with pytest.raises(DeliversToNobody) as exc:
            await mailbox.send("rosemary_nasrin", "ops", "anyone there?")
        assert exc.value.code == "delivers_to_nobody"
        assert "'ops'" in str(exc.value)

    async def test_everyone_on_a_mailbox_of_one_reaches_nobody(
        self, mailbox: Mailbox
    ) -> None:
        await mailbox.join("rosemary_nasrin")
        with pytest.raises(DeliversToNobody) as exc:
            await mailbox.send("rosemary_nasrin", "everyone", "hello?")
        assert "only one here" in str(exc.value)

    async def test_everyone_still_works_once_somebody_else_joins(
        self, mailbox: Mailbox
    ) -> None:
        """The refusal is about reach, not about `everyone` being special."""
        await mailbox.join("rosemary_nasrin")
        await mailbox.join("trevor_mahmood")
        sent = await mailbox.send("rosemary_nasrin", "everyone", "hello?")
        assert sent.to == ("trevor_mahmood",)

    async def test_nothing_undeliverable_is_stored(self, mailbox: Mailbox) -> None:
        """The refusal happens before the write, so no orphan object is left behind."""
        await mailbox.join("rosemary_nasrin")
        before = len(tuple(await mailbox._store.objects()))
        with pytest.raises(DeliversToNobody):
            await mailbox.send("rosemary_nasrin", "everyone", "hello?")
        assert len(tuple(await mailbox._store.objects())) == before

    async def test_addressing_yourself_by_name_delivers(self, mailbox: Mailbox) -> None:
        """Writing your own name is deliberate, and has real uses.

        A note to yourself that outlives the session, or the stimulus for a test that
        needs mail to actually arrive. This is the case that reported the whole defect:
        a self-send returned success and delivered nothing, so an experiment built on it
        could only ever produce a false negative.
        """
        await mailbox.join("rosemary_nasrin")
        sent = await mailbox.send("rosemary_nasrin", "rosemary_nasrin", "note to self")
        assert sent.to == ("rosemary_nasrin",)
        waiting = await mailbox.peek("rosemary_nasrin")
        assert [obj.id for obj in waiting] == [sent.id]

    async def test_your_own_fan_out_still_does_not_come_back(
        self, mailbox: Mailbox
    ) -> None:
        """Explicit is delivered; incidental is not. Scenario 6 still holds."""
        await mailbox.join("rosemary_nasrin")
        await mailbox.join("trevor_mahmood")
        await mailbox.update_profile("rosemary_nasrin", {"groups": ["ops"]})
        await mailbox.update_profile("trevor_mahmood", {"groups": ["ops"]})
        sent = await mailbox.send("rosemary_nasrin", "ops", "morning all")
        assert sent.to == ("trevor_mahmood",)
        assert await mailbox.peek("rosemary_nasrin") == ()

    async def test_a_caller_who_never_joined_is_a_different_error_again(
        self, mailbox: Mailbox
    ) -> None:
        """About who is acting, not who is addressed — the fix is to join."""
        await mailbox.join("rosemary_nasrin")
        with pytest.raises(UnknownActor) as exc:
            await mailbox.send("ghost", "rosemary_nasrin", "boo")
        assert exc.value.code == "unknown_actor"
        assert not isinstance(exc.value, AddressError)

    async def test_every_error_carries_a_stable_code(self) -> None:
        """The code is what the API layer maps; the prose is for the agent."""
        codes = {
            MalformedAddress: "malformed_address",
            UnknownRecipient: "unknown_recipient",
            RemoteMailbox: "remote_mailbox",
            UnknownActor: "unknown_actor",
            NameUnavailable: "name_unavailable",
            NoSuchMessage: "no_such_message",
        }
        for error, code in codes.items():
            assert error.code == code
            assert issubclass(error, MailboxError)
        assert len(set(codes.values())) == len(codes), "codes must be distinct"


class TestSplittingRecipients:
    """The widening federation needs, kept out of `local_name`.

    `local_name` means "the local name, or refuse", and that is the boundary this module
    exists to keep. The fork happens above it so the rules below never learn that remote
    recipients exist.
    """

    def test_local_and_remote_are_separated(self) -> None:
        local, remote = split_recipients(
            ("alice", "bob@saltclub", "carol@beta.example"), "saltclub"
        )
        assert local == ("alice", "bob")
        assert remote == ("carol@beta.example",)

    def test_at_local_never_ends_up_remote(self) -> None:
        """The oldest guarantee in the mailbox, now that this hub can actually send.

        And it holds **by construction**: `@local` is local to every hub, so it resolves
        through the local branch. It is a property of the addressing model rather than a
        rule somebody has to remember, which is why it survives a step that added
        egress.
        """
        for hub in ("saltclub", "local", "anything_at_all"):
            local, remote = split_recipients(("alice@local",), hub)
            assert local == ("alice",), f"@local stopped being local on {hub!r}"
            assert remote == ()

    def test_a_hubs_own_name_is_local(self) -> None:
        local, remote = split_recipients(("alice@saltclub",), "saltclub")
        assert local == ("alice",)
        assert remote == ()

    def test_the_same_address_is_remote_to_a_different_hub(self) -> None:
        """The premise for the test above: `@saltclub` is not magic, it is *this*
        hub."""
        local, remote = split_recipients(("alice@saltclub",), "pepperclub")
        assert local == ()
        assert remote == ("alice@saltclub",)

    def test_an_address_may_carry_a_port(self) -> None:
        """`atlas@beta.example:5001` — which is what makes local multi-hub testing work.

        Several hubs on one machine differ only by port, so an address that could not
        carry one would make them mutually unaddressable and the whole two-hub harness
        impossible. Pinned because it is load-bearing for testing rather than obviously
        part of the addressing model.
        """
        address = parse("atlas@beta.example:5001")
        assert address.name == "atlas"
        assert address.hub == "beta.example:5001"
        assert str(address) == "atlas@beta.example:5001"

        local, remote = split_recipients(("atlas@beta.example:5001",), "saltclub")
        assert remote == ("atlas@beta.example:5001",)
        assert local == ()

    def test_two_hubs_differing_only_by_port_are_different_hubs(self) -> None:
        """The property that lets a laptop host a fleet."""
        _, remote = split_recipients(
            ("a@example:5001", "b@example:5002"), "example:5001"
        )
        assert remote == ("b@example:5002",), (
            "hubs on the same host but different ports must not be conflated"
        )

    def test_nothing_is_lost_or_duplicated(self) -> None:
        given = ("a", "b@local", "c@saltclub", "d@beta.example", "e@gamma.example")
        local, remote = split_recipients(given, "saltclub")
        assert len(local) + len(remote) == len(given)
