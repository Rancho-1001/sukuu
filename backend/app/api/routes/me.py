"""What the signed-in user can see about themselves.

One route, and it exists because of a gap the frontend found: a parent had no
way to discover their own children. Every student endpoint is either staff-only
(`GET /students`) or keyed by an id the parent does not have
(`GET /students/{id}`), so the parent-facing views had nowhere to start.

Answering it from the token rather than from a query parameter is the point.
`GET /students?parent_id=me` would be the same data, but it would mean opening
the staff roster to parents and relying on a filter to keep families apart -
a guard that is one forgotten parameter away from listing the whole school.
Here there is no parameter to forget.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, ParentUser
from app.models import Student
from app.schemas.students import StudentOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/children", response_model=list[StudentOut])
def list_my_children(current_user: ParentUser, db: DbSession) -> list[Student]:
    """Every student attached to the signed-in parent.

    Not paginated: this is one family. A parent with more children than fits on
    a page is not a case worth the complexity, and the caller needs all of them
    to render a picker anyway.
    """
    return list(
        db.scalars(
            select(Student)
            .options(joinedload(Student.school_class))
            .where(Student.parent_id == current_user.id)
            .order_by(Student.first_name, Student.last_name, Student.id)
        )
    )
