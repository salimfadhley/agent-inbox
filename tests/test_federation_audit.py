"""The federation audit — including the refusals nobody typed.

Two properties, and the second is the harder one to keep:

1. Automated refusals are recorded, because *"why did that peer not get my mail"* is a
   question about something no human did.
2. **Nothing sensitive is ever in an entry**, asserted as an absence over the whole
   serialised record rather than field by field — a field-by-field check passes an entry
   that has since gained one, and this is a record designed to grow fields.
"""

import json
import logging

import pytest

from agent_inbox import fedaudit

SECRET = "s3cr3t-token-value"
BODY = "the private contents of somebody's message"


def _said(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(r.getMessage() for r in caplog.records)


class TestItRecordsBothKinds:
    def test_a_deliberate_act(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="agent_inbox.federation.audit"):
            fedaudit.record(
                "block.add", "https://peer.example", by="admin", reason="spam"
            )

        said = _said(caplog)
        assert "block.add" in said
        assert "peer.example" in said
        assert "admin" in said

    def test_an_automated_refusal_with_no_actor(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The half an audit of human actions misses entirely."""
        with caplog.at_level(logging.WARNING, logger="agent_inbox.federation.audit"):
            fedaudit.record(
                "delivery.refused", "https://peer.example", reason="blocked by this hub"
            )

        said = _said(caplog)
        assert "delivery.refused" in said
        assert "blocked by this hub" in said

    def test_an_absent_actor_is_empty_not_invented(self) -> None:
        """A refusal has no `by`, and writing one in would be worse than the gap."""
        entry = fedaudit.record("delivery.refused", "https://peer.example")

        assert entry.by == ""


class TestItNeverCarriesASecret:
    @pytest.mark.parametrize(
        "key",
        ["token", "secret", "password", "signing_key", "content", "body", "message"],
    )
    def test_a_sensitive_value_is_withheld(self, key: str) -> None:
        entry = fedaudit.record("x", "y", detail={key: SECRET})

        assert SECRET not in json.dumps(entry.as_dict())

    def test_it_is_withheld_rather_than_dropped(self) -> None:
        """ "Nothing was passed" and "something was passed and withheld" are different
        facts about the same request, and an audit that conflates them is misleading in
        the direction of looking cleaner than it was."""
        entry = fedaudit.record("x", "y", detail={"token": SECRET})

        assert entry.detail["token"] == fedaudit.REDACTED

    def test_the_check_is_case_insensitive(self) -> None:
        entry = fedaudit.record("x", "y", detail={"Token": SECRET, "SECRET": SECRET})

        assert SECRET not in json.dumps(entry.as_dict())

    def test_an_ordinary_detail_survives(self) -> None:
        """The paired positive. A redactor that withheld everything would satisfy every
        assertion above and make the audit useless."""
        entry = fedaudit.record("x", "y", detail={"message_id": "m-17"})

        assert entry.detail["message_id"] == "m-17"

    def test_the_whole_entry_is_searched_not_named_fields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """NFR-004's shape: assert the absence over everything serialised, so a field
        added next year cannot smuggle a secret past a list of field names."""
        with caplog.at_level(logging.WARNING, logger="agent_inbox.federation.audit"):
            fedaudit.record("x", "y", reason="fine", detail={"content": BODY})

        assert BODY not in _said(caplog)


class TestTheRefusalsAreWiredIn:
    """The module working is not the same as the refusals reaching it — the failure
    that has appeared five times in this codebase."""

    async def test_a_refused_delivery_is_audited(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from agent_inbox import outbound
        from agent_inbox.delivery import FederatedDelivery
        from agent_inbox.house import House
        from agent_inbox.mailbox import Mailbox
        from agent_inbox.records import ObjectRecord
        from agent_inbox.store import InMemoryStore

        store = InMemoryStore()
        await store.add_block("https://peer.example", "2026-08-06", "spam")
        house = House(Mailbox(store, hub_name="t"))
        courier = FederatedDelivery(house.mailbox, "https://us.example")
        resolved = outbound.RemoteRecipient(
            handle="them@peer.example",
            actor_uri="https://peer.example/actors/them",
            inbox="https://peer.example/actors/them/inbox",
        )

        with (
            caplog.at_level(logging.WARNING, logger="agent_inbox.federation.audit"),
            pytest.raises(outbound.DeliveryRefused),
        ):
            await courier.deliver(
                resolved,
                ObjectRecord(
                    id="m-17", attributed_to="us", content=BODY, published="x"
                ),
            )

        said = _said(caplog)
        assert "delivery.refused" in said, "the refusal reached nobody's audit"
        assert "m-17" in said, "which message was refused is not recorded"
        assert BODY not in said, "the message body reached the audit"
