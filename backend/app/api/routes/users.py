"""A directory of accounts, for pickers.

Read-only, admin-only, and deliberately narrow. It exists because attaching a
student to a parent needs a way to choose one, and the alternative was asking
an administrator to type a numeric user id into a form.

There is no create here, and that is a gap rather than a decision: v1 has no
way to open a parent account through the API at all, so families arrive
through the seed script. Onboarding a new family end to end needs user
creation, an invite, and a password flow, which is a bigger piece of work than
a picker and is recorded in the roadmap rather than smuggled in behind one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import DbSession, require_admin
from app.api.pagination import PageParams, count_of
from app.api.search import contains
from app.models import User, UserRole
from app.schemas.auth import UserOut
from app.schemas.common import Page

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserOut], dependencies=[Depends(require_admin)])
def list_users(
    db: DbSession,
    page: PageParams,
    role: Annotated[UserRole | None, Query()] = None,
    q: Annotated[str | None, Query(description="Matches name or email")] = None,
) -> Page[UserOut]:
    """Accounts, filtered by role.

    Admin-only rather than staff-and-admin: this is a list of every email
    address in the school, and a bursar's job needs the student roster, not
    the account directory.
    """
    stmt = select(User)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if q:
        stmt = stmt.where(
            or_(contains(User.name, q), contains(User.email, q)),
        )
    stmt = stmt.order_by(func.lower(User.name), User.id)

    total = count_of(db, stmt)
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[UserOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
