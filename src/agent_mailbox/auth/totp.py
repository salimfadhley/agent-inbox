"""Time-based one-time passwords and their enrolment QR.

Standard RFC 6238 TOTP via :mod:`pyotp`. Enrolment hands the human an
``otpauth://`` URI, which we also render as an **inline SVG** QR with
:mod:`segno` — no external request, no CDN, no image host, so it is safe under
the console's strict CSP and the charter (nothing deployment-specific, nothing
fetched).

Verification accepts a ±1 step window, which absorbs ordinary clock skew between
the hub and the phone without opening a meaningful replay window.

Recovery codes are minted here (they are the second-factor fallback) but
*hashing* them is the store's job — this module only produces the plaintext.
"""

from __future__ import annotations

import pyotp
import segno

from agent_mailbox.auth import secrets as _secrets

#: How many steps either side of now a code is accepted. 1 step = 30s.
_VALID_WINDOW = 1

#: How many recovery codes to issue at enrolment.
_RECOVERY_COUNT = 10


def new_secret() -> str:
    """A fresh base32 TOTP secret to give one user."""
    return pyotp.random_base32()


def provisioning_uri(
    secret: str, username: str, hub: str = "", issuer: str = "agent-inbox"
) -> str:
    """The ``otpauth://`` URI an authenticator app imports.

    The entry reads ``agent-inbox: <hub>/<username>``. A phone accumulates dozens of
    these, and ``agent-inbox: admin`` is useless the moment someone runs a second hub —
    two entries, same label, and no way to tell which is the staging one. The hub's own
    name is the thing that distinguishes them, so it goes in the account part where the
    app shows it.
    """
    account = f"{hub}/{username}" if hub else username
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def qr_svg(uri: str) -> str:
    """Render an ``otpauth://`` URI as a self-contained inline SVG QR.

    Self-contained on purpose: the SVG carries no external reference, so it
    renders under a strict Content-Security-Policy and leaks nothing to a third
    party. The secret is in the QR, so the page that shows it is already
    sensitive — but it never leaves the response.
    """
    return segno.make(uri, error="m").svg_inline(scale=5)


def verify(secret: str, code: str, valid_window: int = _VALID_WINDOW) -> bool:
    """Whether ``code`` is a valid TOTP for ``secret`` (±``valid_window`` steps)."""
    if not code or not code.strip():
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=valid_window)


def current_code(secret: str) -> str:
    """The code for *now* — used by tests and by nothing in production."""
    return pyotp.TOTP(secret).now()


def new_recovery_codes(n: int = _RECOVERY_COUNT) -> tuple[str, ...]:
    """Fresh single-use recovery codes, in plaintext. Hashing is the store's job."""
    return tuple(_secrets.generate_recovery_code() for _ in range(n))
