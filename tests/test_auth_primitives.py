"""WP01 — the cryptographic primitives, with a negative case for each.

These are the leaf everything else trusts, so every property is checked against its
failure: a wrong password, a foreign token, a tampered ciphertext, a stale TOTP code.
A test that only shows the happy path would let a broken constant-time compare or a
no-op encryptor pass.
"""

from __future__ import annotations

import pytest

from agent_mailbox.auth import secrets, totp


class TestPasswords:
    def test_round_trip(self) -> None:
        h = secrets.hash_password("correct horse battery staple")
        assert secrets.verify_password(h, "correct horse battery staple")

    def test_wrong_password_is_rejected(self) -> None:
        h = secrets.hash_password("s3cret")
        assert not secrets.verify_password(h, "s3cret ")
        assert not secrets.verify_password(h, "wrong")

    def test_a_corrupt_hash_does_not_raise(self) -> None:
        assert not secrets.verify_password("not-a-hash", "anything")

    def test_two_hashes_of_the_same_password_differ(self) -> None:
        # argon2 salts, so identical passwords must not produce identical hashes.
        assert secrets.hash_password("x") != secrets.hash_password("x")


class TestTokens:
    def test_generated_tokens_are_unguessable_and_unique(self) -> None:
        a, b = secrets.generate_token(), secrets.generate_token()
        assert a != b
        assert len(a) > 30

    def test_hash_is_stable_and_matches_only_the_right_secret(self) -> None:
        tok = secrets.generate_token()
        stored = secrets.hash_token(tok)
        assert secrets.hash_token(tok) == stored  # deterministic
        assert secrets.token_matches(tok, stored)
        assert not secrets.token_matches(secrets.generate_token(), stored)

    def test_recovery_codes_are_distinct(self) -> None:
        codes = [secrets.generate_recovery_code() for _ in range(20)]
        assert len(set(codes)) == 20


class TestAtRestEncryption:
    def test_round_trip(self) -> None:
        key = secrets.generate_key()
        blob = secrets.encrypt_secret("JBSWY3DPEHPK3PXP", key)
        assert blob != b"JBSWY3DPEHPK3PXP"  # actually encrypted, not stored raw
        assert secrets.decrypt_secret(blob, key) == "JBSWY3DPEHPK3PXP"

    def test_a_wrong_key_cannot_decrypt(self) -> None:
        blob = secrets.encrypt_secret("seed", secrets.generate_key())
        with pytest.raises(ValueError):
            secrets.decrypt_secret(blob, secrets.generate_key())

    def test_a_tampered_ciphertext_is_refused(self) -> None:
        key = secrets.generate_key()
        blob = bytearray(secrets.encrypt_secret("seed", key))
        blob[-1] ^= 0x01
        with pytest.raises(ValueError):
            secrets.decrypt_secret(bytes(blob), key)

    def test_a_malformed_key_is_a_clear_error(self) -> None:
        with pytest.raises(ValueError):
            secrets.encrypt_secret("seed", "not-a-real-fernet-key")


class TestTotp:
    def test_a_fresh_secret_verifies_its_own_current_code(self) -> None:
        s = totp.new_secret()
        assert totp.verify(s, totp.current_code(s))

    def test_a_foreign_code_is_rejected(self) -> None:
        s, other = totp.new_secret(), totp.new_secret()
        assert not totp.verify(s, totp.current_code(other))

    def test_empty_code_is_rejected(self) -> None:
        assert not totp.verify(totp.new_secret(), "")

    def test_window_absorbs_one_step_of_skew(self) -> None:
        import datetime as dt

        import pyotp

        s = totp.new_secret()
        now = dt.datetime.now(dt.UTC)
        # a code from the previous 30s step must still be accepted at window=1
        previous = pyotp.TOTP(s).at(now, counter_offset=-1)
        assert totp.verify(s, previous, valid_window=1)
        # ...but not one from three steps ago
        stale = pyotp.TOTP(s).at(now, counter_offset=-3)
        assert not totp.verify(s, stale, valid_window=1)

    def test_provisioning_uri_is_otpauth(self) -> None:
        uri = totp.provisioning_uri(totp.new_secret(), "rosemary_nasrin")
        assert uri.startswith("otpauth://totp/")
        # The project is agent-inbox; the issuer a phone shows should say so.
        assert "issuer=agent-inbox" in uri

    def test_qr_is_self_contained_svg(self) -> None:
        svg = totp.qr_svg(totp.provisioning_uri(totp.new_secret(), "trevor_mahmood"))
        assert "<svg" in svg
        # no external fetch of any kind — CSP/charter safe
        assert "http://" not in svg and "https://" not in svg

    def test_recovery_codes_are_plaintext_and_many(self) -> None:
        codes = totp.new_recovery_codes()
        assert len(codes) == 10
        assert len(set(codes)) == 10
