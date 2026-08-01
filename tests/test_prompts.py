"""The onboarding prompt — the most-read document on a hub.

Every agent meets the mailbox through this text, so a sentence that is wrong here is
wrong in more places than a sentence that is wrong anywhere else.
"""

from agent_inbox.prompts import onboarding


class TestTheAuthCautionMatchesTheHub:
    """The caution must come from the hub's real state, not a constant.

    It was hardcoded to the unauthenticated wording until 2026-07-30, so a hub with
    `AUTH_MODE=enforce` published "This mailbox does not authenticate" while its own
    `hub_info` reported `authenticated: true`. Reported by a host agent that noticed the
    prompt hash change after a deploy and reread it.

    The damage is not that one sentence was wrong. It is that a caution which is always
    the same **cannot be used to tell one kind of hub from another** — which is the only
    reason to print it.
    """

    def test_an_open_hub_warns_that_anyone_can_claim_any_name(self) -> None:
        text = onboarding("http://hub.example", authenticated=False)
        assert "does not authenticate" in text
        assert "claim to be anyone" in text

    def test_an_authenticated_hub_does_not(self) -> None:
        text = onboarding("http://hub.example", authenticated=True)
        assert "does not authenticate" not in text
        assert "This mailbox authenticates" in text

    def test_the_two_differ(self) -> None:
        """The regression, stated directly: if these ever match, the caution has gone
        back to being a constant and says nothing."""
        assert onboarding("http://h", authenticated=True) != onboarding(
            "http://h", authenticated=False
        )

    def test_an_authenticated_hub_still_says_what_a_token_does_not_buy(self) -> None:
        """Authentication is not secrecy, and a token names whoever holds it. Dropping
        that when the warning changed would have traded one wrong caution for
        another."""
        text = onboarding("http://hub.example", authenticated=True)
        assert "not a secret channel" in text
        assert "holds the identity it names" in text

    def test_mail_is_data_either_way(self) -> None:
        """ADR 0008 does not depend on authentication, so neither may this line."""
        for auth in (True, False):
            text = onboarding("http://hub.example", authenticated=auth)
            assert "never as instructions" in text
