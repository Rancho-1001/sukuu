"""Class groups: create, list, update, archive.

Writes are admin-only, per the spec's permission table. Reads are open to
staff as well: a bursar recording a cash payment has to find the student
first, and filtering by class is how you narrow a roll of several hundred
down to a screenful. Nothing here is visible to parents, who see their own
children through the student routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.api.deps import DbSession, require_admin, require_staff
from app.api.errors import commit_or_conflict
from app.api.pagination import PageParams, count_of
from app.api.search import contains
from app.models import SchoolClass, Student, StudentStatus
from app.schemas.classes import ClassCreate, ClassOut, ClassUpdate
from app.schemas.common import Page

router = APIRouter(prefix="/classes", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")


def _with_counts() -> Select:
    """Classes, each with its number of active students.

    One query for the whole page. The obvious alternative - fetch the classes,
    then ask each one how many students it has - is the N+1 the roadmap warns
    about, and it is invisible at demo scale: four classes, four extra queries,
    nobody notices until a real school has sixty.

    The ``status`` test sits in the JOIN condition rather than a WHERE clause.
    In a WHERE it would drop any class with no active students - their
    outer-joined row is all NULLs and fails the comparison - so a newly created
    class would vanish from the list instead of showing a count of zero.
    """
    return (
        select(SchoolClass, func.count(Student.id).label("active_student_count"))
        .outerjoin(
            Student,
            (Student.class_id == SchoolClass.id) & (Student.status == StudentStatus.ACTIVE),
        )
        .group_by(SchoolClass.id)
    )


def _to_out(school_class: SchoolClass, active_student_count: int) -> ClassOut:
    return ClassOut(
        id=school_class.id,
        name=school_class.name,
        academic_year=school_class.academic_year,
        archived_at=school_class.archived_at,
        active_student_count=active_student_count,
    )


def _load(db: DbSession, class_id: int) -> tuple[SchoolClass, int]:
    row = db.execute(_with_counts().where(SchoolClass.id == class_id)).first()
    if row is None:
        raise NOT_FOUND
    return row[0], row[1]


@router.post(
    "",
    response_model=ClassOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_class(payload: ClassCreate, db: DbSession) -> ClassOut:
    school_class = SchoolClass(**payload.model_dump())
    db.add(school_class)
    commit_or_conflict(db)
    return _to_out(school_class, active_student_count=0)


@router.get("", response_model=Page[ClassOut], dependencies=[Depends(require_staff)])
def list_classes(
    db: DbSession,
    page: PageParams,
    academic_year: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(description="Case-insensitive match on the name")] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> Page[ClassOut]:
    stmt = _with_counts()
    if academic_year:
        stmt = stmt.where(SchoolClass.academic_year == academic_year)
    if q:
        stmt = stmt.where(contains(SchoolClass.name, q))
    if not include_archived:
        stmt = stmt.where(SchoolClass.archived_at.is_(None))

    # Newest year first: last year's classes are history, this year's are work.
    stmt = stmt.order_by(SchoolClass.academic_year.desc(), SchoolClass.name)

    total = count_of(db, stmt)
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[_to_out(school_class, count) for school_class, count in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{class_id}", response_model=ClassOut, dependencies=[Depends(require_staff)])
def read_class(class_id: int, db: DbSession) -> ClassOut:
    return _to_out(*_load(db, class_id))


@router.patch("/{class_id}", response_model=ClassOut, dependencies=[Depends(require_admin)])
def update_class(class_id: int, payload: ClassUpdate, db: DbSession) -> ClassOut:
    school_class, count = _load(db, class_id)

    # exclude_unset, not exclude_none: the two differ the moment a nullable
    # field exists, and "field omitted" must never mean the same thing as
    # "field explicitly set to null".
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(school_class, field, value)

    commit_or_conflict(db)
    return _to_out(school_class, count)


@router.post("/{class_id}/archive", response_model=ClassOut, dependencies=[Depends(require_admin)])
def archive_class(class_id: int, db: DbSession) -> ClassOut:
    """Take a class out of circulation without deleting it.

    Idempotent: archiving an already-archived class keeps the original
    timestamp rather than resetting it, so the record still says when the class
    actually ended.
    """
    school_class, count = _load(db, class_id)
    if school_class.archived_at is None:
        school_class.archived_at = datetime.now(UTC)
        db.commit()
    return _to_out(school_class, count)


@router.post("/{class_id}/restore", response_model=ClassOut, dependencies=[Depends(require_admin)])
def restore_class(class_id: int, db: DbSession) -> ClassOut:
    """Undo an archive. An archive with no way back is a delete with extra steps."""
    school_class, count = _load(db, class_id)
    if school_class.archived_at is not None:
        school_class.archived_at = None
        db.commit()
    return _to_out(school_class, count)
