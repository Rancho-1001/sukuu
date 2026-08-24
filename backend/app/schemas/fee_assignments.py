"""Request and response shapes for fee assignments - "this student owes this
much for this fee, this period"."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Money, Name
from app.schemas.fee_types import FeeTypeSummary
from app.schemas.students import StudentSummary


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
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Money
    due_date: date | None = None
    period_label: str
    student: StudentSummary
    fee_type: FeeTypeSummary


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
