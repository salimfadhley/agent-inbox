"""What the mailbox raises, and why each case is its own class.

Two things shape this hierarchy.

**Failures that need different responses must be different types.** Sending to a name
that does not exist *here* is a mistake the sender can fix by correcting it. Sending to
another mailbox entirely is a thing this deployment cannot do *yet*, and will be able to
do later. Collapsing them would tell an agent "that didn't work" and leave it to guess.

**Every error carries a stable ``code``.** Prose is for the agent reading it and may be
reworded freely; the code is for the layer above, which maps it to an HTTP status or an
MCP error without pattern-matching on English.

The one deliberate *fusion* is :class:`NoSuchMessage`, which covers both "no such
message" and "not yours". Distinguishing those would let an outsider probe what is
stored, which is precisely what the visibility rules protect.
"""

from __future__ import annotations


class MailboxError(Exception):
    """Base for everything this package raises.

    ``code`` is the machine-readable half. Subclasses set it; callers switch on it.
    """

    code = "mailbox_error"


# -- identity ---------------------------------------------------------------


class NameUnavailable(MailboxError):
    """A requested name is taken, reserved, or malformed.

    Recoverable by choosing differently, or by asking for one to be issued.
    """

    code = "name_unavailable"


class InvalidHubName(MailboxError):
    """A proposed hub name is not an address component.

    Distinct from :class:`NameUnavailable`, which is about *agent* names and answers
    409 because the usual cause is a collision. A hub name is refused because it is
    malformed, and the caller must fix the value rather than pick another — 422.
    """

    code = "invalid_hub_name"


class HubSettingGoverned(MailboxError):
    """A write named a setting the environment fixes.

    Refused rather than accepted-and-ignored. Accepting a write that the next read
    would override is a change that reports success and does nothing — the same family
    as a send that succeeds and reaches nobody.
    """

    code = "hub_setting_governed"


class NoSuchWebfingerResource(MailboxError):
    """WebFinger cannot resolve what was asked for.

    Deliberately one answer for several causes — the hub does not federate, the host is
    not this one, the account does not exist. Distinguishing them would tell a stranger
    which of those is true, and the first two are exactly what should stay unsaid.
    """

    code = "no_such_webfinger_resource"


class UnknownActor(MailboxError):
    """The **caller** has not joined this mailbox.

    Distinct from :class:`UnknownRecipient`: this is about who is acting, not who is
    being written to, and the fix is to join rather than to correct an address.
    """

    code = "unknown_actor"


# -- addressing -------------------------------------------------------------


class AddressError(MailboxError):
    """Base for anything wrong with an address.

    Catch this to handle every addressing failure alike; catch a subclass when the
    difference matters, which it usually does.
    """

    code = "address_error"


class MalformedAddress(AddressError):
    """The address could not be parsed at all — empty, or not ``name@hub``.

    A syntax error. Nothing was looked up, because there was nothing to look up.
    """

    code = "malformed_address"


class UnknownRecipient(AddressError):
    """No such actor **on this mailbox**.

    The address is well-formed and local; nobody by that name has joined. Almost always
    a typo or a stale name, and always the sender's to fix.

    This is raised rather than delivered-to-nobody on purpose. A message that reports
    success and reaches no one is the worst outcome for an agent, which cannot notice
    the silence and will wait for a reply that is never coming.

    Only a *specific unknown name* raises here. An audience that is well-formed but
    resolves to nobody — an emptied group, or ``everyone`` on a mailbox of one — raises
    :class:`DeliversToNobody` instead, because the remedy is different.
    """

    code = "unknown_recipient"


class DeliversToNobody(AddressError):
    """Every name was real, and not one of them resolves to a recipient.

    A group everyone has left, or ``everyone`` on a mailbox with nobody else on it. The
    names are valid, so this is not the sender's typo — but the outcome is still that
    the message reaches no one, and that is the thing an agent must not be allowed to
    believe went well.

    The hub used to accept these silently, storing an object with an empty ``to`` and
    returning success. That is the same defect shape as a check with nothing to look at:
    the caller receives an object id indistinguishable from a real delivery, and any
    experiment built on it produces a confident false negative.

    Addressing **yourself by name** is not this error: see
    :meth:`~agent_inbox.mailbox.Mailbox.send`. It is a deliberate act with real uses,
    so it delivers.
    """

    code = "delivers_to_nobody"


class RemoteMailbox(AddressError):
    """The address names a **different mailbox**, which this one cannot reach.

    Not a mistake by the sender: the address may be perfectly valid somewhere. This
    deployment does not federate, so there is nowhere to send it *yet*.

    Kept distinct from :class:`UnknownRecipient` because the remedies are opposite —
    one is "fix the name", the other is "this needs federation" — and because when
    federation arrives, this case becomes a delivery while that one still fails.
    """

    code = "remote_mailbox"


# -- storage ----------------------------------------------------------------


class StoreNotOpen(MailboxError):
    """A store was used before it was opened, or after it was closed.

    A misuse rather than a condition — but it gets a named class anyway, because a
    caller that catches this can open the store and retry, and one that catches
    ``RuntimeError`` catches everything else the interpreter raises too.
    """

    code = "store_not_open"


# -- release ---------------------------------------------------------------


class ReleaseGateError(MailboxError):
    """A release would publish a prompt that cannot be followed.

    The onboarding prompt is executable guidance: when it names a package floor, a
    clean resolver must be able to reach that floor before a live hub advertises it.
    """

    code = "release_gate_error"


# -- messages ---------------------------------------------------------------


class NoSuchMessage(MailboxError):
    """No message with that id is available **to you**.

    Deliberately one error for two situations — it does not exist, and it exists but is
    not yours. Distinguishing them would let an outsider probe what is stored, which is
    the same reasoning that makes an unseen thread come back empty rather than
    forbidden.
    """

    code = "no_such_message"
