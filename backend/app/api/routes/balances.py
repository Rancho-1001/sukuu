"""What is owed: per student, and per class.

The per-assignment balance lives on the assignment itself - see
``FeeAssignmentOut`` - because that is the record it describes. These two are
the roll-ups, and they are the numbers a dashboard and a parent both read, so
the arithmetic behind them goes through :mod:`app.services.balances` and the
aggregation through :mod:`app.services.ledger` rather than being summed
wherever it was convenient.

The student endpoint is guarded per row, not per role: it is the parent's view
of their own child as much as the bursar's view of anybody's.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, OwnStudent, require_staff
from app.api.pagination import PageParams, count_of
from app.models import FeeAssignment, SchoolClass, Student
from app.schemas.classes import ClassSummary
from app.schemas.common import Page
from app.schemas.fee_assignments import FeeAssignmentOut
from app.schemas.payments import (
    ClassBalanceOut,
    StudentBalanceOut,
    StudentBalanceRow,
)
from app.schemas.students import ParentSummary, StudentSummary
from app.services import ledger
from app.services.balances import ZERO, outstanding, to_money

router = APIRouter(tags=["balances"])


@router.get("/students/{student_id}/balance", response_model=StudentBalanceOut)
def read_student_balance(student: OwnStudent, db: DbSession) -> StudentBalanceOut:
    """Everything one child owes, itemised - the parent-scoped fee list.

    The lines are not paginated. One child carries a handful of fees a term,
    and the totals have to cover all of them anyway; splitting the lines across
    pages would mean either a second query for the totals or a total that
    disagrees with what is on screen.

    Which is also why the totals are summed from the lines rather than fetched
    separately: with every line in hand, deriving the totals from them is one
    query and makes a mismatch between the two impossible.
    """
    rows = db.execute(
        ledger.assignments_with_paid()
        .options(joinedload(FeeAssignment.student), joinedload(FeeAssignment.fee_type))
        .where(FeeAssignment.student_id == student.id)
        .order_by(FeeAssignment.due_date.asc().nullslast(), FeeAssignment.id)
    ).all()

    lines = [FeeAssignmentOut.from_row(assignment, paid) for assignment, paid in rows]
    billed = sum((line.amount for line in lines), ZERO)
    paid = sum((line.amount_paid for line in lines), ZERO)

    return StudentBalanceOut(
        student=StudentSummary.model_validate(student),
        school_class=(
            ClassSummary.model_validate(student.school_class) if student.school_class else None
        ),
        parent=ParentSummary.model_validate(student.parent) if student.parent else None,
        billed=billed,
        paid=paid,
        outstanding=outstanding(billed, [paid]),
        lines=lines,
    )


@router.get(
    "/classes/{class_id}/balance",
    response_model=ClassBalanceOut,
    dependencies=[Depends(require_staff)],
)
def read_class_balance(class_id: int, db: DbSession, page: PageParams) -> ClassBalanceOut:
    """A class's collection position, with the per-student breakdown.

    Unlike the student view the rows are paginated, so the totals come from
    their own query over the whole class. Totalling the page would give a
    number that shrinks when someone clicks "next".
    """
    school_class = db.get(SchoolClass, class_id)
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    billed, paid = ledger.totals_where(db, Student.class_id == class_id)

    stmt = (
        ledger.student_balances()
        .where(Student.class_id == class_id)
        .order_by(Student.last_name, Student.first_name, Student.id)
    )
    total = count_of(db, stmt)
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).all()

    return ClassBalanceOut(
        school_class=ClassSummary.model_validate(school_class),
        billed=to_money(billed),
        paid=to_money(paid),
        outstanding=outstanding(billed, [paid]),
        students=Page(
            items=[
                StudentBalanceRow(
                    student=StudentSummary.model_validate(student),
                    billed=to_money(student_billed),
                    paid=to_money(student_paid),
                    outstanding=outstanding(student_billed, [student_paid]),
                )
                for student, student_billed, student_paid in rows
            ],
            total=total,
            limit=page.limit,
            offset=page.offset,
        ),
    )
