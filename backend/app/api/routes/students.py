"""Students: create, list, read, update, and reassign.

Writes are admin-only. Reads split three ways, which is why this module has
both a role guard and a per-row one:

* the list is staff and admin - a bursar needs to find who owes what;
* a single student goes through ``get_own_student``, so a parent may read
  their own child and gets a 404, not a 403, for anyone else's. A 403 would
  confirm the student exists and let a parent walk the ids to learn the roll.

Unlike classes, an inactive student is not hidden by default. Archived
classes accumulate one set per year and would swamp a picker; withdrawn
students are rare, and a roll you cannot search for a former pupil in is the
more annoying of the two failures. ``?status=active`` is there when a caller
wants only current students.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, OwnStudent, require_admin, require_staff
from app.api.errors import commit_or_conflict, unprocessable
from app.api.pagination import PageParams, count_of
from app.api.search import contains
from app.models import SchoolClass, Student, StudentStatus, User, UserRole
from app.schemas.common import Page
from app.schemas.students import StudentCreate, StudentOut, StudentUpdate

router = APIRouter(prefix="/students", tags=["students"])


def _with_relations() -> Select:
    """Students with their class and parent already loaded.

    ``joinedload`` rather than ``selectinload``: both are many-to-one, so the
    join cannot multiply rows and LIMIT still means what it says. Without
    either, serialising a page of fifty students touches the database a
    hundred and one times.
    """
    return select(Student).options(joinedload(Student.school_class), joinedload(Student.parent))


def _resolve_class(db: DbSession, class_id: int) -> SchoolClass:
    school_class = db.get(SchoolClass, class_id)
    if school_class is None:
        raise unprocessable("class_id", f"there is no class with id {class_id}")
    if school_class.is_archived:
        # Not a 409: nothing conflicts, the input is simply pointing at a class
        # that has been retired. Letting it through would quietly re-populate a
        # class the school considers closed.
        raise unprocessable("class_id", f"{school_class.name} has been archived")
    return school_class


def _resolve_parent(db: DbSession, parent_id: int) -> User:
    user = db.get(User, parent_id)
    if user is None:
        raise unprocessable("parent_id", f"there is no user with id {parent_id}")
    if user.role is not UserRole.PARENT:
        # An admin account attached to a student is not a harmless mislabel:
        # parent scoping keys off the role, so the link would be invisible to
        # the very check that is supposed to govern it.
        raise unprocessable("parent_id", f"{user.email} is not a parent account")
    return user


def _check_references(db: DbSession, data: dict) -> None:
    """Validate the ids in a create or update body.

    ``data.get(...) is not None`` covers both "absent" and "explicitly null" -
    neither needs a lookup, and null is how a student is detached from a class
    or a parent.
    """
    if data.get("class_id") is not None:
        _resolve_class(db, data["class_id"])
    if data.get("parent_id") is not None:
        _resolve_parent(db, data["parent_id"])


@router.post(
    "",
    response_model=StudentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_student(payload: StudentCreate, db: DbSession) -> Student:
    data = payload.model_dump()
    _check_references(db, data)

    student = Student(**data)
    db.add(student)
    commit_or_conflict(db)
    return student


@router.get("", response_model=Page[StudentOut], dependencies=[Depends(require_staff)])
def list_students(
    db: DbSession,
    page: PageParams,
    class_id: Annotated[int | None, Query()] = None,
    parent_id: Annotated[int | None, Query()] = None,
    student_status: Annotated[StudentStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(description="Matches name or admission number")] = None,
    unassigned: Annotated[
        bool | None, Query(description="True for students with no class yet")
    ] = None,
) -> Page[StudentOut]:
    stmt = _with_relations()
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)
    if parent_id is not None:
        stmt = stmt.where(Student.parent_id == parent_id)
    if student_status is not None:
        stmt = stmt.where(Student.status == student_status)
    if unassigned is not None:
        # The list an admin needs at the start of a year, and the one that is
        # impossible to build from the other filters.
        stmt = stmt.where(
            Student.class_id.is_(None) if unassigned else Student.class_id.is_not(None)
        )
    if q:
        # Concatenating first and last means "Ama Mensah" finds her, which
        # searching the two columns separately does not.
        stmt = stmt.where(
            or_(
                contains(Student.admission_number, q),
                contains(func.concat(Student.first_name, " ", Student.last_name), q),
            )
        )

    stmt = stmt.order_by(Student.last_name, Student.first_name, Student.id)

    total = count_of(db, stmt)
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[StudentOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{student_id}", response_model=StudentOut)
def read_student(student: OwnStudent) -> Student:
    """One student. The guard is per-row, not per-role: see the module docstring."""
    return student


@router.patch("/{student_id}", response_model=StudentOut, dependencies=[Depends(require_admin)])
def update_student(student_id: int, payload: StudentUpdate, db: DbSession) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    data = payload.model_dump(exclude_unset=True)
    _check_references(db, data)
    for field, value in data.items():
        setattr(student, field, value)

    commit_or_conflict(db)
    return student
