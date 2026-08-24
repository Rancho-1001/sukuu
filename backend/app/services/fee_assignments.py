"""Assigning a fee to a whole class.

Split out from the route because it is the one piece of Phase 3 with a rule
in it rather than a mapping: which students get charged, and what happens to
the ones who already have been.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeeAssignment, FeeType, SchoolClass, Student, StudentStatus


@dataclass(frozen=True)
class BulkAssignment:
    amount: Decimal
    created: int
    skipped_student_ids: list[int]


def bulk_assign(
    db: Session,
    *,
    school_class: SchoolClass,
    fee_type: FeeType,
    period_label: str,
    amount: Decimal | None = None,
    due_date: date | None = None,
) -> BulkAssignment:
    """Charge every active student in ``school_class``.

    Inactive students are left out. A class-wide sweep is a routine act -
    "tuition, Term 1" - and billing a withdrawn pupil in the course of it is
    not something anyone meant to do. Charging one deliberately is still
    possible one student at a time, which is where arrears belong.

    Students who already hold this fee for this period are skipped rather than
    rejected. The alternative is worse than it looks: the unique constraint
    would abort the whole statement, so one already-billed student would block
    the other twenty-four, and the endpoint could never be safely re-run after
    somebody joined the class mid-term.

    The caller owns the commit, which is what makes this all-or-nothing. If a
    second admin assigns the same fee to one of these students between the
    SELECT below and that commit, the unique constraint turns the whole batch
    into a 409 and nothing lands - a retry then finds the row and skips it.
    """
    charge = amount if amount is not None else fee_type.default_amount

    student_ids = set(
        db.scalars(
            select(Student.id).where(
                Student.class_id == school_class.id,
                Student.status == StudentStatus.ACTIVE,
            )
        )
    )
    if not student_ids:
        return BulkAssignment(amount=charge, created=0, skipped_student_ids=[])

    already_assigned = set(
        db.scalars(
            select(FeeAssignment.student_id).where(
                FeeAssignment.fee_type_id == fee_type.id,
                FeeAssignment.period_label == period_label,
                FeeAssignment.student_id.in_(student_ids),
            )
        )
    )

    db.add_all(
        [
            FeeAssignment(
                student_id=student_id,
                fee_type_id=fee_type.id,
                amount=charge,
                due_date=due_date,
                period_label=period_label,
            )
            for student_id in sorted(student_ids - already_assigned)
        ]
    )

    return BulkAssignment(
        amount=charge,
        created=len(student_ids - already_assigned),
        skipped_student_ids=sorted(already_assigned),
    )
