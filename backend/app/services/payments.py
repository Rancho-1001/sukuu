"""Recording a payment against a fee assignment.

This is the only sanctioned way a row enters ``payments``, and the reason it
exists as a service rather than a few lines in a route is the lock.

**Why a row lock, and why on the parent row.** The rule being defended is that
payments against one assignment may not sum past the amount owed. Checking it
means reading every existing payment, deciding, and inserting - and between the
read and the insert, a second request can do exactly the same thing. Under
Postgres's default READ COMMITTED, neither transaction sees the other's
uncommitted insert, so both read the same pre-payment state, both conclude
there is room, and a fee for 100.00 collects 120.00.

Locking the existing payment rows would not help: the dangerous write is a
*new* row, and a row that does not exist yet cannot be locked. So the lock goes
on the fee assignment - the parent every payment hangs off - which gives the
two transactions one thing to queue on. ``SELECT ... FOR UPDATE`` makes the
second caller wait until the first commits, and it then re-reads the payments
and sees the truth.

**The caller owns the commit.** A lock is held until the transaction ends, so
committing here would release it before the caller had finished its own work -
and the concurrency test needs to hold one open deliberately. Routes commit
immediately after; nothing else should sit between.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeeAssignment, Payment, PaymentMethod
from app.services.balances import validate_payment


class UnknownFeeAssignmentError(LookupError):
    """No fee assignment with that id. Raised before any lock is taken."""


def record_payment(
    db: Session,
    *,
    fee_assignment_id: int,
    amount: Decimal | int | str,
    method: PaymentMethod,
    recorded_by_id: int | None = None,
    stripe_payment_intent_id: str | None = None,
    stripe_event_id: str | None = None,
) -> Payment:
    """Validate and insert one payment, holding the assignment's row lock.

    Raises :class:`UnknownFeeAssignmentError` if there is no such assignment,
    and the :class:`~app.services.balances.PaymentError` family - non-positive,
    already settled, overpayment - if the money rules refuse it.

    ``recorded_by_id`` is nullable only because a Stripe payment is recorded by
    the webhook rather than a person. Every cash payment has one, and the route
    is what guarantees it.
    """
    if method is PaymentMethod.CASH and (stripe_payment_intent_id or stripe_event_id):
        # The database has a CHECK constraint saying the same thing. Catching it
        # here turns an IntegrityError raised at commit - by which point the
        # caller has done other work - into an error at the call that caused it.
        raise ValueError("A cash payment cannot carry Stripe identifiers.")
    if method is PaymentMethod.STRIPE and not stripe_payment_intent_id:
        raise ValueError("A Stripe payment must carry a payment intent id.")

    # FOR UPDATE. Everything below happens while this row is held.
    assignment = db.scalar(
        select(FeeAssignment).where(FeeAssignment.id == fee_assignment_id).with_for_update()
    )
    if assignment is None:
        raise UnknownFeeAssignmentError(f"No fee assignment with id {fee_assignment_id}.")

    # Read *after* the lock, never before. A total gathered before the wait is
    # a total from before the other transaction committed, and acting on it is
    # the whole bug the lock exists to prevent.
    already_paid = db.scalars(
        select(Payment.amount_paid).where(Payment.fee_assignment_id == assignment.id)
    ).all()

    accepted = validate_payment(assignment.amount, already_paid, amount)

    payment = Payment(
        fee_assignment_id=assignment.id,
        amount_paid=accepted,
        method=method,
        recorded_by_id=recorded_by_id,
        stripe_payment_intent_id=stripe_payment_intent_id,
        stripe_event_id=stripe_event_id,
    )
    db.add(payment)
    # Flush rather than commit: the caller may still have work to do inside
    # this transaction, and this is what gives the payment an id for a response.
    db.flush()
    return payment
