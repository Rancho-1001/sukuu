"""Starting an online payment.

A parent picks a bill and an amount, and gets back somewhere to be sent. That
is all this route does: no payment row is written here, and none is written
when the browser comes back from Stripe either. The only thing that records
money is the signed webhook, because it is the only one of the three that
cannot be fabricated by whoever is holding the browser.

Parents only. Staff take cash through ``POST /payments``; a parent being able
to file their own cash payment would be a parent being able to mark their own
fees paid.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession
from app.api.errors import unprocessable
from app.models import FeeAssignment, UserRole
from app.schemas.payments import CheckoutSessionCreate, CheckoutSessionOut
from app.services import audit, ledger, stripe_gateway
from app.services.balances import PaymentError, to_money, validate_payment
from app.services.rate_limit import client_ip

router = APIRouter(tags=["payments"])


@router.post(
    "/payments/checkout-session",
    response_model=CheckoutSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_checkout_session(
    request: Request,
    payload: CheckoutSessionCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> CheckoutSessionOut:
    """Open a Stripe Checkout session for part or all of one fee.

    The amount is validated against the balance here so a parent is not sent
    to a payment page for money they do not owe. That check can still go stale
    - a bursar may record cash while the parent is typing a card number - which
    is why it is repeated at the webhook, where the answer has to be different
    because by then the money has actually moved.
    """
    row = db.execute(
        ledger.assignments_with_paid().where(FeeAssignment.id == payload.fee_assignment_id)
    ).first()
    if row is None:
        raise unprocessable(
            "fee_assignment_id", f"there is no fee assignment with id {payload.fee_assignment_id}"
        )
    assignment, paid = row

    # The same rule as get_own_student, applied to the bill's owner: 404 rather
    # than 403, because 403 would confirm the assignment exists and let a
    # parent walk the ids to learn what other families are charged.
    if current_user.role is not UserRole.PARENT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a parent can pay online; staff record cash payments"
        )
    if assignment.student.parent_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee assignment not found")

    try:
        amount = validate_payment(assignment.amount, [to_money(paid)], payload.amount)
    except PaymentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    session = stripe_gateway.create_checkout_session(
        amount=amount,
        fee_assignment_id=assignment.id,
        paid_by_user_id=current_user.id,
        description=f"{assignment.fee_type.name} - {assignment.period_label}",
    )

    # Recorded even though nothing was paid: a session that is opened and never
    # completed is the trail that explains a parent's "I paid and it did not
    # show up", and it is the only record that the attempt happened at all.
    audit.record(
        db,
        action="payment.checkout_started",
        user_id=current_user.id,
        target=f"fee_assignment:{assignment.id}",
        detail=f"session={session.id} amount={amount}",
        ip_address=client_ip(request),
    )
    db.commit()

    return CheckoutSessionOut(
        session_id=session.id,
        checkout_url=session.url,
        fee_assignment_id=assignment.id,
        amount=amount,
    )
