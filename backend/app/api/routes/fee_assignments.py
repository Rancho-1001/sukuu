"""Fee assignments: charge one student, or a whole class at once.

Assigning is admin-only, per the spec's permission table. Reading is staff and
admin - the bursar's view of who owes what. Parents reach their own children's
fees through the balance endpoints, which land with the payment service.

There is no update or delete here, and that is a decision rather than an
omission. An assignment's amount is what a student was billed, and payments
already point at it; lowering it below what has been paid, or removing it out
from under a payment, are money rules that belong with the locked payment
service rather than in a CRUD handler.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Select, select
from sqlalchemy.orm import joinedload

from app.api.deps import AdminUser, DbSession, require_admin, require_staff
from app.api.errors import commit_or_conflict, unprocessable
from app.api.pagination import PageParams, count_of
from app.models import FeeAssignment, FeeType, SchoolClass, Student
from app.schemas.common import Page
from app.schemas.fee_assignments import (
    BulkFeeAssignmentCreate,
    BulkFeeAssignmentResult,
    FeeAssignmentCreate,
    FeeAssignmentOut,
)
from app.services import audit
from app.services.fee_assignments import bulk_assign
from app.services.rate_limit import client_ip

router = APIRouter(prefix="/fee-assignments", tags=["fee assignments"])


def _with_relations() -> Select:
    """Assignments with the student and fee type needed to render them."""
    return select(FeeAssignment).options(
        joinedload(FeeAssignment.student), joinedload(FeeAssignment.fee_type)
    )


def _resolve_fee_type(db: DbSession, fee_type_id: int) -> FeeType:
    fee_type = db.get(FeeType, fee_type_id)
    if fee_type is None:
        raise unprocessable("fee_type_id", f"there is no fee type with id {fee_type_id}")
    return fee_type


@router.post(
    "",
    response_model=FeeAssignmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_fee_assignment(payload: FeeAssignmentCreate, db: DbSession) -> FeeAssignment:
    """Charge one student.

    Unlike the bulk route this will bill an inactive student, because doing so
    one at a time is a deliberate act - a withdrawn pupil's arrears are still
    owed.
    """
    student = db.get(Student, payload.student_id)
    if student is None:
        raise unprocessable("student_id", f"there is no student with id {payload.student_id}")
    fee_type = _resolve_fee_type(db, payload.fee_type_id)

    assignment = FeeAssignment(
        student_id=student.id,
        fee_type_id=fee_type.id,
        amount=payload.amount if payload.amount is not None else fee_type.default_amount,
        due_date=payload.due_date,
        period_label=payload.period_label,
    )
    db.add(assignment)
    commit_or_conflict(db)
    return assignment


# Declared before /{fee_assignment_id} so that "bulk" is not read as an id.
@router.post("/bulk", response_model=BulkFeeAssignmentResult)
def create_bulk_fee_assignment(
    request: Request,
    payload: BulkFeeAssignmentCreate,
    db: DbSession,
    current_user: AdminUser,
) -> BulkFeeAssignmentResult:
    """Charge every active student in a class, in one transaction.

    Answers 200 rather than 201: it may create twenty-five rows or none, and a
    201 with nothing behind it would be a lie. The body reports what happened.
    """
    school_class = db.get(SchoolClass, payload.class_id)
    if school_class is None:
        raise unprocessable("class_id", f"there is no class with id {payload.class_id}")
    if school_class.is_archived:
        raise unprocessable("class_id", f"{school_class.name} has been archived")
    fee_type = _resolve_fee_type(db, payload.fee_type_id)

    result = bulk_assign(
        db,
        school_class=school_class,
        fee_type=fee_type,
        period_label=payload.period_label,
        amount=payload.amount,
        due_date=payload.due_date,
    )

    # The audit middleware records "POST /fee-assignments/bulk status=200" for
    # free, which does not say how many students were billed or for how much.
    # One request here charges a whole class; the detail is the point. The
    # address is carried over too - this is the row an investigation would
    # actually read, and it should not be the one missing where it came from.
    audit.record(
        db,
        action="fee_assignment.bulk",
        user_id=current_user.id,
        target=f"class:{school_class.id}",
        detail=(
            f"fee_type={fee_type.id} period={payload.period_label!r} "
            f"amount={result.amount} created={result.created} "
            f"skipped={len(result.skipped_student_ids)}"
        ),
        ip_address=client_ip(request),
    )
    commit_or_conflict(db)

    return BulkFeeAssignmentResult(
        class_id=school_class.id,
        fee_type_id=fee_type.id,
        period_label=payload.period_label,
        amount=result.amount,
        created=result.created,
        skipped_student_ids=result.skipped_student_ids,
    )


@router.get("", response_model=Page[FeeAssignmentOut], dependencies=[Depends(require_staff)])
def list_fee_assignments(
    db: DbSession,
    page: PageParams,
    student_id: Annotated[int | None, Query()] = None,
    class_id: Annotated[int | None, Query()] = None,
    fee_type_id: Annotated[int | None, Query()] = None,
    period_label: Annotated[str | None, Query()] = None,
) -> Page[FeeAssignmentOut]:
    stmt = _with_relations()
    if student_id is not None:
        stmt = stmt.where(FeeAssignment.student_id == student_id)
    if class_id is not None:
        # An explicit join rather than reusing the eager-loaded one: the
        # joinedload above builds its own alias, and filtering through that is
        # the classic way to end up with a WHERE the loader silently ignores.
        stmt = stmt.join(Student, FeeAssignment.student_id == Student.id).where(
            Student.class_id == class_id
        )
    if fee_type_id is not None:
        stmt = stmt.where(FeeAssignment.fee_type_id == fee_type_id)
    if period_label is not None:
        stmt = stmt.where(FeeAssignment.period_label == period_label)

    # Soonest due first, undated last: the bursar's order, not the database's.
    stmt = stmt.order_by(FeeAssignment.due_date.asc().nullslast(), FeeAssignment.id)

    total = count_of(db, stmt)
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[FeeAssignmentOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{fee_assignment_id}",
    response_model=FeeAssignmentOut,
    dependencies=[Depends(require_staff)],
)
def read_fee_assignment(fee_assignment_id: int, db: DbSession) -> FeeAssignment:
    assignment = db.scalar(_with_relations().where(FeeAssignment.id == fee_assignment_id))
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee assignment not found")
    return assignment
