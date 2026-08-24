"""Request and response shapes for payments and balances."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import PaymentMethod
from app.schemas.classes import ClassSummary
from app.schemas.common import Money, MoneyTotal, Page
from app.schemas.fee_assignments import FeeAssignmentOut
from app.schemas.students import ParentSummary, StudentSummary


class CashPaymentCreate(BaseModel):
    """What a bursar submits when someone hands over money.

    Note what is *not* here: ``method``. The route records cash and only cash.
    Accepting a method from the client would let a member of staff file a
    payment as "stripe" with no Stripe transaction behind it, which is the one
    lie this ledger must not be able to tell about itself. Online payments
    arrive from the webhook in Phase 5 and never from a form.
    """

    model_config = ConfigDict(extra="forbid")

    fee_assignment_id: int
    amount: Money


class RecordedBy(BaseModel):
    """Who took the money. Accountability data, so it is on every response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_assignment_id: int
    amount_paid: Money
    method: PaymentMethod
    paid_at: datetime
    recorded_by: RecordedBy | None = None


class CashPaymentReceipt(BaseModel):
    """A recorded payment, with the bill it landed against.

    The assignment comes back so the screen that took the cash can show what
    is left owing without a second request - the first thing anyone asks after
    handing over money.
    """

    payment: PaymentOut
    fee_assignment: FeeAssignmentOut


class StudentBalanceOut(BaseModel):
    """Everything one child owes, itemised.

    This is the parent's view as much as the bursar's, which is why it carries
    the whole picture rather than a number: a total with no lines behind it is
    not something anyone will pay against.
    """

    student: StudentSummary
    school_class: ClassSummary | None = None
    parent: ParentSummary | None = None
    billed: MoneyTotal
    paid: MoneyTotal
    outstanding: MoneyTotal
    lines: list[FeeAssignmentOut]


class StudentBalanceRow(BaseModel):
    """One student's totals, as they appear in a class breakdown."""

    student: StudentSummary
    billed: MoneyTotal
    paid: MoneyTotal
    outstanding: MoneyTotal


class ClassBalanceOut(BaseModel):
    school_class: ClassSummary
    billed: MoneyTotal
    paid: MoneyTotal
    outstanding: MoneyTotal
    # Paginated, while the totals above are not: the totals cover the whole
    # class. A figure that silently reports only the current page is the kind
    # of wrong number a dashboard states with complete confidence.
    students: Page[StudentBalanceRow]


class CheckoutSessionCreate(BaseModel):
    """A parent choosing what to pay online.

    ``amount`` is theirs to choose rather than fixed to the balance: paying a
    term's fees in installments is the v1 feature this whole flow exists for.
    """

    model_config = ConfigDict(extra="forbid")

    fee_assignment_id: int
    amount: Money


class CheckoutSessionOut(BaseModel):
    """Where to send the payer. Nothing here records a payment - only the
    webhook does that."""

    session_id: str
    checkout_url: str
    fee_assignment_id: int
    amount: Money


class ClassCollectionRow(BaseModel):
    """One class's line on the admin dashboard."""

    school_class: ClassSummary
    billed: MoneyTotal
    paid: MoneyTotal
    outstanding: MoneyTotal


class SchoolSummaryOut(BaseModel):
    """Collected and outstanding across the school.

    ``classes`` will not always sum to the totals above it: a student enrolled
    but not yet placed in a class is billed like anyone else and counts toward
    the school figure while having no class row to appear in. That gap is
    information, not drift.
    """

    billed: MoneyTotal
    paid: MoneyTotal
    outstanding: MoneyTotal
    classes: list[ClassCollectionRow]
