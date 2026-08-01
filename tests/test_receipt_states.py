"""The third delivery state, and the one existing answer it would otherwise spoil —
WP01 of mission `retry-delivery-to-a-sleeping-peer-01KYWFWB` (federation step 7).

Step 6 delivered once: a receipt was `delivered` or `failed`, and `Sent.reached_nobody`
could read the boolean and be right. Step 7 lets a message *wait*, and a waiting receipt
has `delivered=False` — so the guard that decides whether the API refuses a send would
have called an ordinary sleeping peer a failure.

**The row that matters here is the one that was already correct.** A fix that makes
`reached_nobody` lenient in general passes the new cases and destroys the old one — and
the old one is the guard `api.py` relies on to avoid "a silent success, which is the
worst failure shape we have".
"""

from agent_inbox.delivery import NOT_DURABLE, Receipt, Sent
from agent_inbox.records import ObjectRecord

ALICE = "alice_okonkwo"
SLEEPY = "https://sleepy.example/actors/atlas"
AWAKE = "https://awake.example/actors/bruno"


def _record() -> ObjectRecord:
    return ObjectRecord(
        id="urn:test:1",
        attributed_to=ALICE,
        to=(SLEEPY,),
        content="are you there",
        summary="a question",
    )


def _sent(*receipts: Receipt, local: tuple[str, ...] = ()) -> Sent:
    return Sent(record=_record(), receipts=receipts, local_recipients=local)


class TestTheThreeStates:
    def test_delivered(self) -> None:
        assert Receipt(SLEEPY, delivered=True).state == "delivered"

    def test_failed(self) -> None:
        assert Receipt(SLEEPY, delivered=False).state == "failed"

    def test_queued(self) -> None:
        assert Receipt.waiting(SLEEPY).state == "queued"

    def test_an_existing_construction_is_unchanged(self) -> None:
        """The new field defaults, so no call site written before step 7 changes
        meaning."""
        assert Receipt(SLEEPY, delivered=False, detail="refused").state == "failed"


class TestTheDisclosure:
    """FR-008(a). The queue does not survive a restart, and we deploy on every release,
    so a sender told `queued` must be told that too."""

    def test_a_queued_receipt_says_the_wait_is_not_durable(self) -> None:
        assert Receipt.waiting(SLEEPY).detail == NOT_DURABLE
        assert "does not survive a restart" in NOT_DURABLE

    def test_the_disclosure_cannot_be_left_off(self) -> None:
        """`waiting` is the only constructor for a queued receipt, so the disclosure is
        structural rather than a rule someone has to remember."""
        assert Receipt.waiting(SLEEPY).queued
        assert Receipt.waiting(SLEEPY).detail


class TestReachedNobody:
    """The four rows. `api.py` refuses a 201 when this is true, so both directions of
    wrongness are expensive — and only one of them is obvious."""

    def test_all_queued_is_not_nobody(self) -> None:
        assert not _sent(Receipt.waiting(SLEEPY)).reached_nobody

    def test_all_failed_is_still_nobody(self) -> None:
        """**The row that was already right.**

        If a change to `reached_nobody` makes this pass by making the property lenient,
        the guard has been replaced rather than extended. Delete the `queued` branch and
        this must still pass; make the property `return False` and it must fail.
        """
        assert _sent(Receipt(SLEEPY, delivered=False)).reached_nobody

    def test_some_queued_and_some_failed_is_not_nobody(self) -> None:
        """Something may still arrive, so the send has not yet reached nobody."""
        assert not _sent(
            Receipt.waiting(SLEEPY), Receipt(AWAKE, delivered=False)
        ).reached_nobody

    def test_any_delivered_is_not_nobody(self) -> None:
        assert not _sent(Receipt(AWAKE, delivered=True)).reached_nobody

    def test_a_local_recipient_still_settles_it(self) -> None:
        """Unchanged by step 7: a stored local copy is a delivery that cannot fail."""
        assert not _sent(Receipt.waiting(SLEEPY), local=("bob_hansson",)).reached_nobody

    def test_no_receipts_at_all_is_not_nobody(self) -> None:
        """A purely local send has no remote receipts and must not be judged by them."""
        assert not _sent(local=("bob_hansson",)).reached_nobody
