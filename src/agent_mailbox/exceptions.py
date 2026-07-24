"""What the mailbox raises.

One base class, so a caller can catch everything from this package without catching
the world. Messages are written to be read by an agent that must act on them alone.
"""

from __future__ import annotations


class MailboxError(Exception):
    """Base for everything this package raises."""


class NameUnavailable(MailboxError):
    """A requested name is taken, reserved, or malformed."""


class NoSuchMessage(MailboxError):
    """No message with that id is available **to you**.

    Deliberately one error for two situations — it does not exist, and it exists but
    is not yours. Distinguishing them would let an outsider probe what is stored, which
    is the same reasoning that makes an unseen thread come back empty rather than
    forbidden.
    """


class UnknownActor(MailboxError):
    """No actor by that name has joined."""
