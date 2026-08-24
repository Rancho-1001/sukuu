"""Shared FastAPI dependencies: the current user, and the role guards.

The guards here are the only thing standing between a role and data it may not
see. They run server-side on every request; the frontend hiding a button is a
courtesy, not a control.

Dependencies are declared with ``Annotated`` rather than as argument defaults -
the modern FastAPI style, and it keeps the signatures readable when a route
needs three of them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import Student, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

DbSession = Annotated[Session, Depends(get_db)]
BearerToken = Annotated[str, Depends(oauth2_scheme)]

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(request: Request, token: BearerToken, db: DbSession) -> User:
    try:
        claims = decode_access_token(token)
    except TokenError:
        raise CREDENTIALS_ERROR from None

    try:
        user_id = int(claims["sub"])
    except KeyError, TypeError, ValueError:
        raise CREDENTIALS_ERROR from None

    user = db.get(User, user_id)
    if user is None:
        # The token verified but the account is gone. Same response as a bad
        # token: the client has no business distinguishing the two.
        raise CREDENTIALS_ERROR

    # Picked up by the audit middleware once the response is on its way back.
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*allowed: UserRole) -> Callable[..., User]:
    """Dependency factory admitting only the listed roles.

    Usage::

        @router.post("/students", dependencies=[Depends(require_admin)])
    """
    allowed_set = frozenset(allowed)

    def guard(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this action",
            )
        return current_user

    return guard


# The three boundaries in the permission table.
require_admin = require_role(UserRole.ADMIN)
require_staff = require_role(UserRole.ADMIN, UserRole.STAFF)
require_parent = require_role(UserRole.PARENT)

AdminUser = Annotated[User, Depends(require_admin)]
StaffUser = Annotated[User, Depends(require_staff)]
ParentUser = Annotated[User, Depends(require_parent)]


def get_own_student(student_id: int, current_user: CurrentUser, db: DbSession) -> Student:
    """Fetch a student the current user is allowed to see.

    Role alone is not enough for parents: being a parent does not entitle you
    to *every* child, only your own. That ownership check is per-row and has to
    happen here rather than in a role guard.

    Returns 404 rather than 403 when a parent asks for someone else's child. A
    403 would confirm the student exists, which leaks exactly what the check
    exists to protect - a parent could walk the ids and learn the school roll.
    """
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    if current_user.role is UserRole.PARENT and student.parent_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    return student


OwnStudent = Annotated[Student, Depends(get_own_student)]
