"""Password hashing and JSON Web Tokens.

Two decisions here are worth reading before changing anything.

**Passwords are SHA-256 pre-hashed before bcrypt.** bcrypt only considers the
first 72 bytes of its input and, in bcrypt 5.x, raises outright on anything
longer. It also stops at the first NUL byte. Hashing to a fixed-length digest
first removes both problems, so a long passphrase is protected by all of its
entropy rather than its first 72 bytes. The digest is base64-encoded rather
than hex because base64 is 44 bytes where hex would be 64, and both are
comfortably under the limit. This is the same construction passlib shipped as
``bcrypt_sha256``.

**Tokens are decoded with an explicit algorithm allow-list.** Passing
``algorithms=["HS256"]`` is what stops an attacker presenting a token that
claims ``alg: none``, or an RS256 token whose "public key" is our HMAC secret.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


class TokenError(Exception):
    """A token was missing, malformed, expired, or not signed by us."""


def _prepare(password: str) -> bytes:
    """Reduce a password of any length to a fixed 44-byte bcrypt input."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check. Returns False rather than raising on a malformed hash."""
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except ValueError, TypeError:
        return False


def create_access_token(
    subject: int | str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    expires = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {
        # "sub" is required by RFC 7519 to be a string; PyJWT enforces this.
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature and expiry, and return the claims.

    Raises :class:`TokenError` for every failure mode so that callers cannot
    accidentally treat "expired" and "forged" differently.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
