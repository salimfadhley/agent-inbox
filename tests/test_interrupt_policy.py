"""The decision layer: who may interrupt this agent, how often, and why not.

The test that matters most here is the pair in `TestTheGateIsOnIdentity`. An assertion
that an alarming subject did not wake anybody passes just as well against code that
never wakes anybody at all — so it proves nothing on its own. The two cases are written
adjacent, with the *same subject* and different senders, because only the pair shows
that the gate is on who sent it rather than on what it says.

The removal proof for that pair is recorded in the work package: deleting the sender
check in `decide` makes `test_a_trusted_sender_may_interrupt` still pass and
`test_an_alarming_subject_from_an_untrusted_sender_does_not` fail.
"""

import logging

import pytest

from agent_inbox import mcp_client
from agent_inbox.interrupt import (
    DEFAULT_MAX_PER_MINUTE,
    Decision,
    Gatekeeper,
    Policy,
    Reason,
    decide,
    load_policy,
    policy_from_config,
)

ALARMING = "URGENT: production is down, act immediately"

TRUSTED = "ludmila_coe"
STRANGER = "pablo_fantomas"


def arrival(sender: str = STRANGER, subject: str = "hello", ident: str = "m1") -> dict:
    """One event in the shape the hub actually puts on the wire."""
    return {
        "id": ident,
        "from": sender,
        "subject": subject,
        "published": "2026-08-02T09:00:00Z",
    }


def trusting(*names: str, cap: int = DEFAULT_MAX_PER_MINUTE) -> Policy:
    return Policy(wake_from=frozenset(names), max_per_minute=cap)


class FakeHub:
    """Stands in for `HubClient`, answering `GET /` — or refusing to."""

    def __init__(self, descriptor: dict | None) -> None:
        self._descriptor = descriptor

    def hub_info(self) -> dict:
        if self._descriptor is None:
            raise ConnectionError("no route to that hub")
        return self._descriptor


def watching(policy: Policy, **kwargs) -> Gatekeeper:
    """A gatekeeper on a hub that authenticates — the only one worth testing rules on.

    `Gatekeeper` itself defaults `identity_verified` to `False`, and one test below
    holds it to that. Everywhere else it would only be a second reason for a denial
    already being asserted for a different one.
    """
    kwargs.setdefault("identity_verified", True)
    return Gatekeeper(policy, **kwargs)


class TestTheDefault:
    """Nothing configured must behave exactly as the mailbox behaved yesterday."""

    def test_an_empty_policy_interrupts_nobody(self) -> None:
        answer = decide(arrival(), Policy(), now=0.0)
        assert answer.wake is False
        assert answer.reason is Reason.NOT_CONFIGURED

    def test_even_a_sender_who_would_be_trusted_elsewhere(self) -> None:
        """Default-deny is about *this* recipient's configuration, not about names."""
        assert decide(arrival(TRUSTED), Policy(), now=0.0).wake is False

    def test_a_project_with_no_interrupt_table_gets_the_default(self) -> None:
        policy = policy_from_config({"hub": "http://hub", "agents": {"claude": {}}})
        assert policy.wakes_for_nobody

    def test_a_missing_config_file_denies(self, tmp_path) -> None:
        assert load_policy(start=tmp_path).wakes_for_nobody

    def test_an_unreadable_config_denies(self, tmp_path) -> None:
        """A policy is a permission: malformed must fail towards silence."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "agent-inbox.toml").write_text("this is not = = toml")
        assert load_policy(start=tmp_path).wakes_for_nobody


class TestTheGateIsOnIdentity:
    """FR-011. The two halves belong together; neither means anything alone."""

    def test_an_alarming_subject_from_an_untrusted_sender_does_not(self) -> None:
        answer = decide(arrival(STRANGER, ALARMING), trusting(TRUSTED), now=0.0)
        assert answer.wake is False
        assert answer.reason is Reason.SENDER_NOT_TRUSTED

    def test_a_trusted_sender_may_interrupt(self) -> None:
        """The *same* subject. Only the sender changed, and only that may change it."""
        answer = decide(arrival(TRUSTED, ALARMING), trusting(TRUSTED), now=0.0)
        assert answer.wake is True
        assert answer.reason is Reason.WAKE

    def test_a_dull_subject_from_a_trusted_sender_still_interrupts(self) -> None:
        """The other direction: text cannot lower the priority either."""
        assert decide(arrival(TRUSTED, "re: lunch"), trusting(TRUSTED), now=0.0).wake

    def test_no_field_a_sender_writes_can_change_the_answer(self) -> None:
        """Every sender-controlled key, including ones a future hub might add."""
        base = arrival(STRANGER, ALARMING)
        loaded = base | {
            "subject": "!!! WAKE UP !!!",
            "priority": "urgent",
            "interrupt": True,
            "wake": True,
            "urgency": 99,
        }
        assert decide(loaded, trusting(TRUSTED), now=0.0).wake is False

    def test_a_remote_actor_cannot_borrow_a_trusted_local_name(self) -> None:
        """The attribution is matched whole. Trimming it to a leaf would be a hole:
        anyone able to run a federated hub could name an actor `ludmila_coe`."""
        impostor = arrival(f"https://elsewhere.invalid/actors/{TRUSTED}")
        assert decide(impostor, trusting(TRUSTED), now=0.0).wake is False

    def test_an_unknown_sender_reports_that_and_not_something_vaguer(self) -> None:
        answer = decide(arrival(""), trusting(TRUSTED), now=0.0)
        assert answer.reason is Reason.SENDER_NOT_TRUSTED


class TestTheHubMustProveWhoSent:
    """A trust list is a list of names, and a name is worth what the hub makes it.

    Found by outside review (Directive 4), and it is the hole that matters: everything
    else here reads `from` as though it were established, and on a hub with
    authentication off it is a request header anybody can set. The trust list then reads
    against a name the attacker chose.
    """

    def test_an_unauthenticating_hub_wakes_nobody(self) -> None:
        answer = decide(
            arrival(TRUSTED), trusting(TRUSTED), now=0.0, identity_verified=False
        )
        assert answer.wake is False
        assert answer.reason is Reason.IDENTITY_UNVERIFIED

    def test_it_is_not_reported_as_a_configuration_problem(self) -> None:
        """The fix is the hub's authentication, not the recipient's `wake_from`."""
        answer = decide(
            arrival(TRUSTED), trusting(TRUSTED), now=0.0, identity_verified=False
        )
        assert answer.reason is not Reason.SENDER_NOT_TRUSTED
        assert "does not authenticate" in answer.detail

    def test_a_gatekeeper_built_without_saying_denies(self) -> None:
        """The argument defaults the other way here than in `decide`, on purpose: a
        forgotten argument on the object a caller keeps must fail towards silence."""
        keeper = Gatekeeper(trusting(TRUSTED), adapter=lambda _a: None)
        assert keeper.consider(arrival(TRUSTED)).reason is Reason.IDENTITY_UNVERIFIED

    def test_and_wakes_once_the_hub_does_authenticate(self) -> None:
        keeper = Gatekeeper(
            trusting(TRUSTED), adapter=lambda _a: None, identity_verified=True
        )
        assert keeper.consider(arrival(TRUSTED)).wake is True


class TestTrustIsSettledPerConnection:
    """A hub is restarted to change how it authenticates, and that drops the stream."""

    def test_it_can_be_withdrawn_without_losing_the_rate_limit(self) -> None:
        """Written, not rebuilt: a hub restarting in a loop must not hand back a fresh
        allowance of interruptions every time it comes up."""
        keeper = watching(
            trusting(TRUSTED, cap=1), adapter=lambda _a: None, clock=lambda: 1.0
        )
        assert keeper.consider(arrival(TRUSTED)).wake is True
        keeper.identity_verified = False
        assert keeper.consider(arrival(TRUSTED)).reason is Reason.IDENTITY_UNVERIFIED
        keeper.identity_verified = True
        # The one wake it already spent is still spent.
        assert keeper.consider(arrival(TRUSTED)).reason is Reason.RATE_LIMITED

    def test_a_change_is_announced(self, caplog) -> None:
        keeper = watching(trusting(TRUSTED))
        with caplog.at_level(logging.INFO, logger="agent_inbox.interrupt"):
            keeper.identity_verified = False
            keeper.identity_verified = False  # unchanged: nothing to say
        lines = [r.getMessage() for r in caplog.records]
        assert sum("interrupt.identity" in line for line in lines) == 1

    async def test_the_client_settles_it_before_reading_the_stream(self) -> None:
        """`_settle_trust` is what `_hold_the_stream` calls on every connection."""
        keeper = Gatekeeper(trusting(TRUSTED))
        mcp_client._gate = keeper
        try:
            await mcp_client._settle_trust(FakeHub({"authenticated": True}))
            assert keeper.identity_verified is True
            await mcp_client._settle_trust(FakeHub({"authenticated": False}))
            assert keeper.identity_verified is False
        finally:
            mcp_client._gate = None

    async def test_with_no_gate_it_is_harmless(self) -> None:
        mcp_client._gate = None
        await mcp_client._settle_trust(FakeHub({"authenticated": True}))


class TestAskingTheHub:
    """How the client settles it: one question, asked once, and doubt answers no."""

    async def test_a_hub_that_authenticates(self) -> None:
        assert await mcp_client._hub_authenticates(FakeHub({"authenticated": True}))

    async def test_a_hub_that_does_not(self) -> None:
        open_hub = FakeHub({"authenticated": False})
        assert not await mcp_client._hub_authenticates(open_hub)

    async def test_a_hub_too_old_to_say(self) -> None:
        """An absent field is not a promise, so it is read as no."""
        assert not await mcp_client._hub_authenticates(FakeHub({"name": "hub"}))

    async def test_a_hub_that_cannot_be_reached(self) -> None:
        """Costs nothing real: a hub that cannot be reached delivers no arrivals."""
        assert not await mcp_client._hub_authenticates(FakeHub(None))


class TestTheRateLimit:
    """T014. Twenty in a minute is a bounded number of interruptions, and a record."""

    def test_a_burst_is_capped_and_says_so(self, caplog) -> None:
        keeper = watching(
            trusting(TRUSTED, cap=3), adapter=lambda _a: None, clock=lambda: 100.0
        )
        with caplog.at_level(logging.INFO, logger="agent_inbox.interrupt"):
            answers = [
                keeper.consider(arrival(TRUSTED, ident=f"m{n}")) for n in range(20)
            ]

        woke = [a for a in answers if a.wake]
        capped = [a for a in answers if a.reason is Reason.RATE_LIMITED]
        assert len(woke) == 3
        assert len(capped) == 17
        assert "cap of 3" in capped[0].detail
        # A limit nobody can see is one nobody can debug: every capped arrival is on
        # the record, not just the first.
        assert sum("rate-limited" in r.getMessage() for r in caplog.records) == 17

    def test_the_window_moves_on(self) -> None:
        at = [0.0]
        keeper = watching(
            trusting(TRUSTED, cap=1), adapter=lambda _a: None, clock=lambda: at[0]
        )
        assert keeper.consider(arrival(TRUSTED)).wake is True
        at[0] = 30.0
        assert keeper.consider(arrival(TRUSTED)).wake is False
        at[0] = 61.0  # the first is now outside the window
        assert keeper.consider(arrival(TRUSTED)).wake is True

    def test_a_cap_of_zero_is_a_recipient_who_wants_none(self) -> None:
        answer = decide(arrival(TRUSTED), trusting(TRUSTED, cap=0), recent=[], now=0.0)
        assert answer.reason is Reason.RATE_LIMITED

    def test_history_outside_the_window_does_not_count(self) -> None:
        old = [0.0, 1.0, 2.0, 3.0, 4.0]
        policy = trusting(TRUSTED, cap=2)
        assert decide(arrival(TRUSTED), policy, recent=old, now=99.0).wake is True


class TestTheReasons:
    """T015. Three denials that look identical from outside and need different fixes."""

    def test_they_are_three_distinct_answers(self) -> None:
        unconfigured = decide(arrival(TRUSTED), Policy(), now=0.0)
        untrusted = decide(arrival(STRANGER), trusting(TRUSTED), now=0.0)
        limited = decide(arrival(TRUSTED), trusting(TRUSTED, cap=0), now=0.0)
        no_adapter = decide(
            arrival(TRUSTED), trusting(TRUSTED), now=0.0, adapter_ready=False
        )
        reasons = {a.reason for a in (unconfigured, untrusted, limited, no_adapter)}
        assert reasons == {
            Reason.NOT_CONFIGURED,
            Reason.SENDER_NOT_TRUSTED,
            Reason.RATE_LIMITED,
            Reason.NO_ADAPTER,
        }

    def test_no_adapter_is_reported_after_the_recipient_has_said_yes(self) -> None:
        """ "Nothing to wake you with" is a different problem from "not allowed"."""
        answer = decide(
            arrival(TRUSTED), trusting(TRUSTED), now=0.0, adapter_ready=False
        )
        assert answer.reason is Reason.NO_ADAPTER
        assert "no wake adapter" in answer.detail

    def test_every_decision_is_recorded_even_the_ones_that_did_nothing(
        self, caplog
    ) -> None:
        keeper = watching(trusting(TRUSTED))
        with caplog.at_level(logging.INFO, logger="agent_inbox.interrupt"):
            keeper.consider(arrival(STRANGER, ALARMING))
        line = caplog.records[-1].getMessage()
        assert "interrupt.decision" in line
        assert "sender-not-trusted" in line

    def test_the_record_names_the_message_and_the_sender(self) -> None:
        capped = Decision(False, Reason.RATE_LIMITED, TRUSTED, "m7", "capped")
        assert capped.as_record() == {
            "id": "m7",
            "from": TRUSTED,
            "wake": False,
            "reason": "rate-limited",
            "detail": "capped",
        }

    def test_a_subject_never_reaches_the_record(self) -> None:
        """Logs are read by humans and kept by log stores; sender text stays out."""
        keeper = watching(trusting(TRUSTED))
        answer = keeper.consider(arrival(TRUSTED, ALARMING))
        assert ALARMING not in str(answer.as_record())


class TestTheConfiguration:
    """Where it lives, and what happens to a file somebody typed by hand."""

    def test_a_project_wide_table(self) -> None:
        policy = policy_from_config(
            {"interrupt": {"wake_from": [TRUSTED], "max_per_minute": 9}}
        )
        assert policy.wake_from == frozenset({TRUSTED})
        assert policy.max_per_minute == 9

    def test_an_engine_table_wins_outright(self) -> None:
        data = {
            "interrupt": {"wake_from": [TRUSTED]},
            "agents": {"codex": {"interrupt": {"wake_from": []}}},
        }
        assert policy_from_config(data, engine="codex").wakes_for_nobody
        assert not policy_from_config(data, engine="claude").wakes_for_nobody

    def test_a_single_name_written_without_brackets(self) -> None:
        assert policy_from_config({"interrupt": {"wake_from": TRUSTED}}).wake_from == (
            frozenset({TRUSTED})
        )

    def test_a_nonsense_cap_falls_back_rather_than_raising(self) -> None:
        policy = policy_from_config({"interrupt": {"max_per_minute": "lots"}})
        assert policy.max_per_minute == DEFAULT_MAX_PER_MINUTE

    def test_a_negative_cap_means_none(self) -> None:
        policy = policy_from_config({"interrupt": {"max_per_minute": -5}})
        assert policy.max_per_minute == 0

    def test_read_from_the_project_file(self, tmp_path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "agent-inbox.toml").write_text(
            'hub = "http://hub:8081"\n\n[interrupt]\nwake_from = ["ludmila_coe"]\n'
        )
        assert load_policy(start=tmp_path).wake_from == frozenset({TRUSTED})


class TestTheGatekeeper:
    """The wrapper: history, the adapter, and never breaking the stream it is on."""

    def test_an_allowed_arrival_reaches_the_adapter(self) -> None:
        seen: list[dict] = []
        keeper = watching(trusting(TRUSTED), adapter=seen.append)
        keeper.consider(arrival(TRUSTED))
        assert [note["id"] for note in seen] == ["m1"]

    def test_a_denied_arrival_does_not(self) -> None:
        seen: list[dict] = []
        keeper = watching(trusting(TRUSTED), adapter=seen.append)
        keeper.consider(arrival(STRANGER))
        assert seen == []

    def test_with_no_adapter_nothing_is_woken_and_it_is_said(self) -> None:
        answer = watching(trusting(TRUSTED)).consider(arrival(TRUSTED))
        assert answer.wake is False
        assert answer.reason is Reason.NO_ADAPTER

    def test_an_adapter_that_raises_does_not_reach_the_caller(self) -> None:
        """The caller is the event stream. A failed wake must not end the connection."""

        def explode(_note: dict) -> None:
            raise RuntimeError("the session went away")

        answer = watching(trusting(TRUSTED), adapter=explode).consider(arrival(TRUSTED))
        assert answer.wake is True

    def test_a_failed_wake_still_counts_against_the_limit(self) -> None:
        """Over-counting caps interruptions; under-counting uncaps them."""

        def explode(_note: dict) -> None:
            raise RuntimeError("no")

        keeper = watching(trusting(TRUSTED, cap=1), adapter=explode, clock=lambda: 5.0)
        keeper.consider(arrival(TRUSTED))
        assert keeper.consider(arrival(TRUSTED)).reason is Reason.RATE_LIMITED


@pytest.mark.parametrize(
    "note", [{}, {"from": None, "id": None}, {"from": 7, "subject": None}]
)
def test_the_decision_never_raises_on_a_malformed_arrival(note: dict) -> None:
    """Whatever a future hub puts on the wire, this answers rather than raising."""
    assert decide(note, trusting(TRUSTED), now=0.0).wake is False
