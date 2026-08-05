"""More than one human can operate a hub, and all of them are admins.

The storage layer has been multi-user since it was written — `add_user`, `get_user`,
`any_users`, keyed by username. Nothing above it ever called `add_user` except
`bootstrap`, so in practice a hub had exactly one human. This is the missing half.

**There is no role column and no hierarchy**, which is the owner's rule: every human
here is an admin, and a second class of human would be a role by another name. The only
asymmetry is arithmetic — the list cannot become empty.
"""

from collections.abc import AsyncIterator

import pytest

from agent_inbox.auth.exceptions import (
    LastOperator,
    OperatorExists,
    UnknownOperator,
)
from agent_inbox.auth.records import ADMIN_GROUP, USER_GROUP, EnrolmentState
from agent_inbox.auth.service import AuthService
from agent_inbox.auth.store import InMemoryAuthStore
from agent_inbox.exceptions import NameUnavailable


@pytest.fixture
async def auth() -> AsyncIterator[AuthService]:
    service = AuthService(InMemoryAuthStore(), secret_key="k" * 44)
    await service.bootstrap()
    yield service


class TestInvitingAHuman:
    async def test_a_second_operator_can_be_added(self, auth: AuthService) -> None:
        await auth.add_operator("ludmila")
        assert {u.username for u in await auth.operators()} == {"admin", "ludmila"}

    async def test_the_invitation_returns_a_one_time_password(
        self, auth: AuthService
    ) -> None:
        password = await auth.add_operator("ludmila")
        assert password, "an invitation nobody can use is not an invitation"

    async def test_a_new_operator_must_set_up_before_acting(
        self, auth: AuthService
    ) -> None:
        """An invitation confers nothing until its holder enrols. The same state the
        seeded account starts in — one onboarding path, not two."""
        await auth.add_operator("ludmila")
        who = next(u for u in await auth.operators() if u.username == "ludmila")
        assert who.enrolment_state is EnrolmentState.MUST_CHANGE_AND_ENROL

    async def test_the_one_time_password_actually_works(
        self, auth: AuthService
    ) -> None:
        password = await auth.add_operator("ludmila")
        result = await auth.login("ludmila", password)
        assert result.enrolment_required, "and it lands them in enrolment, not in power"

    async def test_a_username_is_taken_once(self, auth: AuthService) -> None:
        await auth.add_operator("ludmila")
        with pytest.raises(OperatorExists):
            await auth.add_operator("ludmila")

    async def test_the_seeded_admin_is_not_special(self, auth: AuthService) -> None:
        """No founder, no owner. `admin` is just the first name issued."""
        with pytest.raises(OperatorExists):
            await auth.add_operator("admin")

    async def test_a_username_needs_to_be_something(self, auth: AuthService) -> None:
        # `NameUnavailable` rather than the bare `ValueError` this used to raise: it is
        # the type every other unusable name raises, and it carries the code the HTTP
        # layer turns into a status instead of a 500.
        with pytest.raises(NameUnavailable):
            await auth.add_operator("   ")


class TestAUsernameMustBeANameAMailboxCouldHold:
    """Owner, 2026-08-05, ahead of the namespace merge.

    An operator account and a mailbox are becoming one identity, so a username no actor
    could hold is an account that can never have an inbox. Refused at registration,
    where the person is present to fix it — not discovered later by somebody whose mail
    has nowhere to go.
    """

    @pytest.mark.parametrize(
        "username",
        [
            "sal.fadhley",  # a dot: what people type when they mean an email
            "sal-1",  # a hyphen: valid everywhere else, not here
            "sal fadhley",  # a space
            "_sal",  # must start with a letter or digit
            "sal_",  # and end with one
            "sal@example.com",  # an address, not a name
            "a" * 65,  # past the ceiling
        ],
    )
    async def test_a_username_no_actor_could_hold_is_refused(
        self, auth: AuthService, username: str
    ) -> None:
        with pytest.raises(NameUnavailable):
            await auth.add_operator(username)

        assert {u.username for u in await auth.operators()} == {"admin"}, (
            "the account was created anyway"
        )

    async def test_an_addressing_keyword_is_refused_to_humans_too(
        self, auth: AuthService
    ) -> None:
        """`everyone` as a username would make every broadcast ambiguous."""
        with pytest.raises(NameUnavailable):
            await auth.add_operator("everyone")

    async def test_a_standing_resident_is_not_refused(self, auth: AuthService) -> None:
        """The paired positive, and the point of the whole change.

        `admin` is withheld from agents precisely so the human who operates the hub can
        hold it. A rule that rejected it would lock out the one account the merge exists
        to serve — and this test is what stops a future tightening from doing that
        quietly. It gets as far as OperatorExists, which means the *name* was accepted.
        """
        with pytest.raises(OperatorExists):
            await auth.add_operator("admin")

    async def test_case_is_folded_rather_than_refused(self, auth: AuthService) -> None:
        """The one normalisation kept: every login system in the world folds case, and
        this one already did. Refusing `Ludmila` would be a change nobody asked for."""
        await auth.add_operator("Ludmila")

        assert "ludmila" in {u.username for u in await auth.operators()}

    async def test_a_good_username_still_works(self, auth: AuthService) -> None:
        """The paired positive for the whole class: without it, every assertion above
        would pass on an `add_operator` that had simply stopped working."""
        await auth.add_operator("sam_okonkwo")

        assert "sam_okonkwo" in {u.username for u in await auth.operators()}

    async def test_the_refusal_says_what_to_type_instead(
        self, auth: AuthService
    ) -> None:
        """A refusal a human cannot act on is a dead end, and this one reaches a human
        by definition — it is a person filling in a form."""
        with pytest.raises(NameUnavailable) as refusal:
            await auth.add_operator("sal.fadhley")

        assert "sal_fadhley" in str(refusal.value)


class TestTheEmailAddress:
    """Collected now for a password-recovery flow that does not exist yet.

    Asking for it *after* someone is locked out is too late, which is the whole reason
    it is stored before there is anything to use it for.
    """

    async def test_an_address_is_kept(self, auth: AuthService) -> None:
        await auth.add_operator("ludmila", "ludmila@example.com")
        who = next(u for u in await auth.operators() if u.username == "ludmila")
        assert who.email == "ludmila@example.com"

    async def test_it_is_optional(self, auth: AuthService) -> None:
        """Nothing consumes it yet, so refusing an invitation for want of an address
        would be a gate in front of a door that is not built."""
        await auth.add_operator("ludmila")
        who = next(u for u in await auth.operators() if u.username == "ludmila")
        assert who.email == ""


class TestRemoval:
    async def test_any_operator_can_be_removed(self, auth: AuthService) -> None:
        await auth.add_operator("ludmila")
        await auth.remove_operator("ludmila")
        assert {u.username for u in await auth.operators()} == {"admin"}

    async def test_including_the_one_who_set_the_hub_up(
        self, auth: AuthService
    ) -> None:
        """All humans are equal, so `admin` enjoys no protection the others lack. The
        consequence of the owner's rule, asserted rather than left implied."""
        await auth.add_operator("ludmila")
        await auth.remove_operator("admin")
        assert {u.username for u in await auth.operators()} == {"ludmila"}

    async def test_the_last_operator_cannot_be_removed(self, auth: AuthService) -> None:
        """The one asymmetry, and it is arithmetic rather than status."""
        with pytest.raises(LastOperator):
            await auth.remove_operator("admin")
        assert await auth.operators(), "and they are still there afterwards"

    async def test_removing_a_stranger_says_so(self, auth: AuthService) -> None:
        await auth.add_operator("ludmila")
        with pytest.raises(UnknownOperator):
            await auth.remove_operator("nobody_here")

    async def test_a_removed_operator_cannot_sign_in(self, auth: AuthService) -> None:
        from agent_inbox.auth.exceptions import BadCredentials

        password = await auth.add_operator("ludmila")
        await auth.remove_operator("ludmila")
        with pytest.raises(BadCredentials):
            await auth.login("ludmila", password)

    async def test_their_session_stops_working_immediately(
        self, auth: AuthService
    ) -> None:
        """Removal that waits until they next sign in is not removal — the case it
        exists for is someone who should lose access *now*."""
        password = await auth.add_operator("ludmila")
        await auth.login("ludmila", password)
        session = await auth.open_full_session("ludmila")

        await auth.remove_operator("ludmila")
        assert await auth.resolve_session(session.id) is None


class TestGroupsAreAStub:
    """`group` is recorded, displayed, and **enforced nowhere**.

    These tests exist to keep that honest. A field that reads like a permission and is
    not one invites somebody to demote a colleague and believe it took effect, so the
    absence of enforcement is asserted rather than left to be discovered.

    **When the checks land, these tests should fail** — that is the point of them.
    """

    async def test_a_group_is_recorded(self, auth: AuthService) -> None:
        await auth.add_operator("ludmila", group=USER_GROUP)
        who = next(u for u in await auth.operators() if u.username == "ludmila")
        assert who.group == USER_GROUP

    async def test_admin_is_the_default(self, auth: AuthService) -> None:
        """Because every human is an admin today, the default must be the powerful one
        — a default of `user` would imply a restraint that does not exist."""
        await auth.add_operator("ludmila")
        who = next(u for u in await auth.operators() if u.username == "ludmila")
        assert who.group == ADMIN_GROUP

    async def test_an_unknown_group_falls_back_rather_than_refusing(
        self, auth: AuthService
    ) -> None:
        await auth.add_operator("ludmila", group="wizard")
        who = next(u for u in await auth.operators() if u.username == "ludmila")
        assert who.group == ADMIN_GROUP

    async def test_a_user_group_member_can_still_do_everything(
        self, auth: AuthService
    ) -> None:
        """**The stub, stated out loud.** Marked `user`, and can still add and remove
        operators — because nothing reads the field. The day this fails is the day
        groups became real."""
        await auth.add_operator("ludmila", group=USER_GROUP)
        await auth.add_operator("pablo", group=USER_GROUP)

        # Acting *as* a `user`-group account is not even expressible: no call takes the
        # acting operator, because no call cares who is acting.
        await auth.remove_operator("pablo")
        assert {u.username for u in await auth.operators()} == {"admin", "ludmila"}

    async def test_the_seeded_admin_is_in_the_admin_group(
        self, auth: AuthService
    ) -> None:
        who = next(u for u in await auth.operators() if u.username == "admin")
        assert who.group == ADMIN_GROUP
