"""The cryptographic primitives, as pure functions.

Three kinds of secret, three treatments, and the difference is the point:

- **Passwords** are low-entropy, so they get a slow, salted hash (Argon2id).
  Verifying one is deliberately expensive, which only happens at login.
- **Tokens and recovery codes** are high-entropy (generated here from a CSPRNG),
  so a fast hash with a constant-time compare is enough and far cheaper per
  request. Argon2 on a 256-bit random token would buy nothing and cost a lot.
- **TOTP secrets** must be *recovered* to compute codes, so they are reversibly
  **encrypted** at rest (Fernet), never hashed. The key lives in the environment,
  never in the database — so a leaked database reveals no usable 2FA seed
  (NFR-001).

No storage, no I/O, no globals. The key is always an explicit argument.
"""

import hashlib
import hmac
import secrets as _secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

#: One hasher, default parameters — fine for a single-owner hub. Argon2id is the
#: default type. It is stateless and thread-safe, so a module-level instance is safe.
_hasher = PasswordHasher()

#: Bytes of entropy for a generated token. 32 bytes → ~43 url-safe chars, ~256 bits.
_TOKEN_BYTES = 32

# -- passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an Argon2id encoded hash. The parameters travel inside the string."""
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Whether ``password`` matches ``stored_hash``. False, not raise, on mismatch."""
    try:
        return _hasher.verify(stored_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 - a corrupt hash is "does not match", not a crash
        return False


# -- tokens and recovery codes --------------------------------------------


def generate_token() -> str:
    """A fresh high-entropy secret for a device token. Shown once, never stored raw."""
    return _secrets.token_urlsafe(_TOKEN_BYTES)


def generate_recovery_code() -> str:
    """A single-use recovery code. Shorter than a token but still beyond guessing."""
    return _secrets.token_urlsafe(9)


def hash_token(secret: str) -> str:
    """A fast, deterministic hash for a *high-entropy* secret (token or code).

    SHA-256 is right here precisely because the input is already unguessable:
    there is no dictionary to slow down, so Argon2's cost would be waste.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def token_matches(secret: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented secret against a stored hash."""
    return hmac.compare_digest(hash_token(secret), stored_hash)


# -- at-rest encryption (TOTP secrets) ------------------------------------


def generate_key() -> str:
    """A fresh Fernet key, base64 text — for the ``--print-secret-key`` helper."""
    return Fernet.generate_key().decode("ascii")


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "AGENT_INBOX_SECRET_KEY is not a valid Fernet key — generate one with "
            "the app's --print-secret-key helper and keep it stable across restarts"
        ) from exc


def encrypt_secret(plaintext: str, key: str) -> bytes:
    """Encrypt a TOTP secret for storage. The key comes from the environment."""
    return _fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes, key: str) -> str:
    """Recover a TOTP secret. Raises ``ValueError`` on a wrong key or tampering."""
    try:
        return _fernet(key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "could not decrypt the stored TOTP secret — the secret key changed or "
            "the value was tampered with"
        ) from exc
