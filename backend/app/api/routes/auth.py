"""Login and identity."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import Token, UserOut
from app.services import audit
from app.services.rate_limit import client_ip, enforce_login_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

# Verifying against this when the email is unknown keeps the response time for
# "no such user" close to that of "wrong password", so the endpoint does not
# quietly answer "does this email have an account?" by how fast it replies.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder")


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    """Exchange email and password for a bearer token.

    Takes form encoding rather than JSON so the interactive docs' Authorize
    button works, which makes the API demonstrable without a frontend. The
    OAuth2 form calls the field ``username``; ours holds an email address.
    """
    email = form.username.strip().lower()
    ip = client_ip(request)

    # Checked before the password is verified, so a throttled caller costs us a
    # single indexed count rather than a bcrypt comparison.
    enforce_login_rate_limit(db, email=email, ip=ip)

    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        verify_password(form.password, _DUMMY_HASH)
        _fail(db, email, ip=ip)

    if not verify_password(form.password, user.password_hash):
        _fail(db, email, ip=ip, user_id=user.id)

    audit.record(db, action="auth.login", user_id=user.id, target=user.email, ip_address=ip)
    db.commit()

    return Token(
        access_token=create_access_token(user.id, user.role.value),
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _fail(
    db: DbSession, attempted: str, *, ip: str | None = None, user_id: int | None = None
) -> None:
    """Record the attempt, then reject without saying which half was wrong.

    The row written here is what the rate limiter counts, so this must run on
    every failure - including one for an email that does not exist.
    """
    audit.record(
        db,
        action="auth.login_failed",
        user_id=user_id,
        target=attempted[:120],
        detail="bad credentials",
        ip_address=ip,
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.get("/me", response_model=UserOut)
def read_me(current_user: CurrentUser) -> User:
    return current_user
