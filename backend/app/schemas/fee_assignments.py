"""Request and response shapes for fee assignments - "this student owes this
much for this fee, this period"."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Money, MoneyTotal, Name
from app.schemas.fee_types import FeeTypeSummary
from app.schemas.students import StudentSummary
from app.services.balances import is_settled, outstanding, to_money

if TYPE_CHECKING:
    from app.models import FeeAssignment


class FeeAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: int
    fee_type_id: int
    period_label: Name(40)
    # Omit to charge the fee type's default. Present so a school can bill one
    # student a different amount - a scholarship, a sibling discount - without
    # inventing a fee type per exception.
    amount: Money | None = None
    due_date: date | None = None


class BulkFeeAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_id: int
    fee_type_id: int
    period_label: Name(40)
    amount: Money | None = None
    due_date: date | None = None


class FeeAssignmentOut(BaseModel):
    """One bill, with where it stands.

    ``amount`` is what was charged, ``amount_paid`` what has come in against
    it, and ``outstanding`` the difference - which is the per-assignment
    balance the roadmap asks for, on the record it belongs to rather than at a
    separate endpoint a client has to correlate by hand.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Money
    amount_paid: MoneyTotal
    outstanding: MoneyTotal
    settled: bool
    due_date: date | None = None
    period_label: str
    student: StudentSummary
    fee_type: FeeTypeSummary

    @classmethod
    def from_row(cls, assignment: FeeAssignment, amount_paid: object) -> FeeAssignmentOut:
        """Build from an ``(assignment, amount_paid)`` row.

        The derived figures go through :mod:`app.services.balances` rather than
        being subtracted here, so the rule that a balance never reads negative
        has exactly one definition. Passing the already-summed total as a
        one-element list is what lets that pure function do the work unchanged.
        """
        paid = to_money(amount_paid)
        return cls(
            id=assignment.id,
            amount=assignment.amount,
            amount_paid=paid,
            outstanding=outstanding(assignment.amount, [paid]),
            settled=is_settled(assignment.amount, [paid]),
            due_date=assignment.due_date,
            period_label=assignment.period_label,
            student=StudentSummary.model_validate(assignment.student),
            fee_type=FeeTypeSummary.model_validate(assignment.fee_type),
        )


class BulkFeeAssignmentResult(BaseModel):
    """What a class-wide assignment actually did.

    ``skipped_student_ids`` is the list of students who already had this fee
    for this period. Reporting them rather than failing is what makes the
    endpoint safe to re-run after a student joins the class mid-term.
    """

    class_id: int
    fee_type_id: int
    period_label: str
    amount: Money
    created: int
    skipped_student_ids: list[int]
