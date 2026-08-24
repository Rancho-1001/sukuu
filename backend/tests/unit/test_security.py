"""Password hashing and token handling. No database, no HTTP."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_correct_password_verifies(self):
        assert verify_password("correct-horse", hash_password("correct-horse")) is True

    def test_wrong_password_is_rejected(self):
        assert verify_password("wrong", hash_password("correct-horse")) is False

    def test_hash_is_not_the_password(self):
        assert hash_password("hunter2") != "hunter2"

    def test_same_password_hashes_differently_each_time(self):
        """Distinct salts, so identical passwords are not identifiable in a dump."""
        assert hash_password("same") != hash_password("same")

    def test_password_longer_than_bcrypts_72_byte_limit_works(self):
        """bcrypt 5.x raises above 72 bytes; the SHA-256 pre-hash is what avoids it."""
        long_password = "a" * 200
        assert verify_password(long_password, hash_password(long_password)) is True

    def test_two_long_passwords_sharing_a_72_byte_prefix_are_distinguished(self):
        """Without pre-hashing, bcrypt would treat these as the same password."""
        stored = hash_password("x" * 72 + "AAAA")
        assert verify_password("x" * 72 + "BBBB", stored) is False

    def test_password_containing_a_null_byte_is_handled(self):
        """Raw bcrypt truncates at the first NUL; the digest has no such problem."""
        assert verify_password("abc\x00def", hash_password("abc\x00def")) is True
        assert verify_password("abc\x00xyz", hash_password("abc\x00def")) is False

    def test_unicode_password_round_trips(self):
        assert verify_password("pässwörd-Ω", hash_password("pässwörd-Ω")) is True

    def test_malformed_stored_hash_returns_false_rather_than_raising(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False

    def test_empty_stored_hash_returns_false(self):
        assert verify_password("anything", "") is False


class TestAccessTokens:
    def test_round_trips_subject_and_role(self):
        claims = decode_access_token(create_access_token(42, "admin"))
        assert claims["sub"] == "42"
        assert claims["role"] == "admin"

    def test_subject_is_a_string_as_the_spec_requires(self):
        assert isinstance(decode_access_token(create_access_token(42, "staff"))["sub"], str)

    def test_token_carries_an_expiry(self):
        assert "exp" in decode_access_token(create_access_token(1, "parent"))

    def test_expired_token_is_rejected(self):
        expired = create_access_token(1, "admin", expires_delta=timedelta(seconds=-1))
        with pytest.raises(TokenError):
            decode_access_token(expired)

    def test_token_signed_with_another_secret_is_rejected(self):
        forged = jwt.encode(
            {"sub": "1", "role": "admin"},
            "a-different-secret-of-entirely-sufficient-length-x",
            algorithm="HS256",
        )
        with pytest.raises(TokenError):
            decode_access_token(forged)

    def test_alg_none_token_is_rejected(self):
        """The classic JWT attack: an unsigned token asserting whatever it likes."""
        unsigned = jwt.encode({"sub": "1", "role": "admin"}, key="", algorithm="none")
        with pytest.raises(TokenError):
            decode_access_token(unsigned)

    def test_token_without_an_expiry_is_rejected(self):
        """A token that never expires must not be accepted just because it verifies."""
        no_exp = jwt.encode({"sub": "1", "role": "admin"}, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(TokenError):
            decode_access_token(no_exp)

    def test_garbage_is_rejected(self):
        with pytest.raises(TokenError):
            decode_access_token("not.a.token")

    def test_tampered_payload_is_rejected(self):
        token = create_access_token(1, "parent")
        header, payload, signature = token.split(".")
        other = create_access_token(1, "admin").split(".")[1]
        with pytest.raises(TokenError):
            decode_access_token(f"{header}.{other}.{signature}")
