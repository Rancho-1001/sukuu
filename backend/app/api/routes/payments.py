"""Recording and reading payments.

Cash only, and staff-or-admin only. A parent pays online in Phase 5; a bursar
takes notes across a desk and records it here.

The route is deliberately thin. Every rule that matters - the row lock, the
overpayment check, who may be credited - lives in
:mod:`app.services.payments`, so the same rules apply to the Stripe webhook
when it arrives, rather than being re-implemented next to it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Select, select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, OwnStudent, StaffUser, require_staff
from app.api.errors import unprocessable
from app.api.pagination import PageParams, count_of
from app.models import FeeAssignment, Payment, PaymentMethod, Student
from app.schemas.common import Page
from app.schemas.fee_assignments import FeeAssignmentOut
from app.schemas.payments import CashPaymentCreate, CashPaymentReceipt, PaymentOut
from app.services import audit, ledger
from app.services.balances import PaymentError
from app.services.payments import UnknownFeeAssignmentError, record_payment
from app.services.rate_limit import client_ip

router = APIRouter(tags=["payments"])


def _with_relations() -> Select:
    return select(Payment).options(joinedload(Payment.recorded_by))


@router.post(
    "/payments",
    response_model=CashPaymentReceipt,
    status_code=status.HTTP_201_CREATED,
)
def record_cash_payment(
    request: Request,
    payload: CashPaymentCreate,
    db: DbSession,
    current_user: StaffUser,
) -> CashPaymentReceipt:
    """Take a cash payment against one fee.

    A refused payment answers 409 rather than 422. The request is well-formed
    and the amount is a real amount; what it conflicts with is the current
    state of the bill - somebody paid in the meantime, or it was already
    settled. That is a retry with a different number, not a malformed field,
    and the message says what is actually left.
    """
    try:
        payment = record_payment(
            db,
            fee_assignment_id=payload.fee_assignment_id,
            amount=payload.amount,
            method=PaymentMethod.CASH,
            recorded_by_id=current_user.id,
        )
    except UnknownFeeAssignmentError:
        raise unprocessable(
            "fee_assignment_id", f"there is no fee assignment with id {payload.fee_assignment_id}"
        ) from None
    except PaymentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Money changing hands deserves better than "POST /payments status=201".
    audit.record(
        db,
        action="payment.cash",
        user_id=current_user.id,
        target=f"fee_assignment:{payload.fee_assignment_id}",
        detail=f"payment={payment.id} amount={payment.amount_paid}",
        ip_address=client_ip(request),
    )
    # Commits the payment, the audit row, and releases the row lock together.
    db.commit()

    row = db.execute(
        ledger.assignments_with_paid()
        .options(joinedload(FeeAssignment.student), joinedload(FeeAssignment.fee_type))
        .where(FeeAssignment.id == payload.fee_assignment_id)
    ).one()
    return CashPaymentReceipt(
        payment=PaymentOut.model_validate(payment),
        fee_assignment=FeeAssignmentOut.from_row(*row),
    )


@router.get("/payments", response_model=Page[PaymentOut], dependencies=[Depends(require_staff)])
def list_payments(
    db: DbSession,
    page: PageParams,
    fee_assignment_id: Annotated[int | None, Query()] = None,
    student_id: Annotated[int | None, Query()] = None,
    class_id: Annotated[int | None, Query()] = None,
    method: Annotated[PaymentMethod | None, Query()] = None,
    recorded_by_id: Annotated[int | None, Query()] = None,
) -> Page[PaymentOut]:
    """Every payment the school has taken. The reports half of the spec's
    "view all payments & reports", and where "who recorded it" is visible."""
    stmt = _with_relations()
    if fee_assignment_id is not None:
        stmt = stmt.where(Payment.fee_assignment_id == fee_assignment_id)
    if student_id is not None or class_id is not None:
        stmt = stmt.join(FeeAssignment, Payment.fee_assignment_id == FeeAssignment.id)
        if student_id is not None:
            stmt = stmt.where(FeeAssignment.student_id == student_id)
        if class_id is not None:
            stmt = stmt.join(Student, FeeAssignment.student_id == Student.id).where(
                Student.class_id == class_id
            )
    if method is not None:
        stmt = stmt.where(Payment.method == method)
    if recorded_by_id is not None:
        stmt = stmt.where(Payment.recorded_by_id == recorded_by_id)

    # Most recent first: a payments list is read to find what just happened.
    stmt = stmt.order_by(Payment.paid_at.desc(), Payment.id.desc())

    total = count_of(db, stmt)
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[PaymentOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/students/{student_id}/payments", response_model=Page[PaymentOut])
def list_student_payments(student: OwnStudent, db: DbSession, page: PageParams) -> Page[PaymentOut]:
    """One child's payment history, for the parent who made them.

    Scoped by ``get_own_student`` rather than by a role, which is what lets the
    same route serve a parent, the bursar, and an admin without any of them
    seeing another family's payments.
    """
    stmt = (
        _with_relations()
        .join(FeeAssignment, Payment.fee_assignment_id == FeeAssignment.id)
        .where(FeeAssignment.student_id == student.id)
        .order_by(Payment.paid_at.desc(), Payment.id.desc())
    )
    total = count_of(db, stmt)
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[PaymentOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
