"""Stripe webhooks: the only place an online payment becomes a payment row.

**Why not the browser redirect.** Stripe sends the payer back to a success
URL when checkout finishes, and it is tempting to record the payment there -
the user is right in front of you and the page knows the session id. But that
request comes from the browser, which means anyone can issue it, with any
session id, having paid nothing. The redirect is a *hint* that something
happened; the signed webhook is the only evidence. So the success page shows
"we are confirming your payment" and this route is what makes it true.

It is also what makes the flow survive a closed laptop: the webhook arrives
whether or not the browser ever came back.

**Authentication.** No token, because Stripe does not have one. The signature
is the authentication: an HMAC of the raw body against a shared secret, with
a timestamp inside the signed payload so a captured request cannot be replayed
later. Which is why the raw body matters - see ``stripe_gateway``.

**Answering 200.** Stripe retries anything that is not a 2xx, with backoff,
for days. That is right for "the database was down" and wrong for everything
else: an event we do not handle, a duplicate we have already recorded, a
payment we cannot apply. Those are all final answers, and they are all 200
with a body that says what happened. The only 400 here is a signature that
does not verify.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import stripe
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.models import Payment, PaymentMethod, User
from app.services import audit
from app.services.balances import PaymentError
from app.services.payments import UnknownFeeAssignmentError, record_payment
from app.services.stripe_gateway import FEE_ASSIGNMENT_KEY, PAID_BY_KEY, construct_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

PAYMENT_SUCCEEDED = "checkout.session.completed"
CHECKOUT_ABANDONED = "checkout.session.expired"
PAYMENT_FAILED = "payment_intent.payment_failed"

# The unique constraint on payments.stripe_event_id, by the name the database
# knows it. Checked explicitly below rather than treating any IntegrityError as
# a duplicate: a foreign key or CHECK violation answered with "already
# recorded" would tell Stripe the payment was handled, stop the retries, and
# lose the money silently behind a 200.
EVENT_ID_CONSTRAINT = "stripe_event_id"


def _ok(**body: object) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_200_OK, content={"received": True, **body})


@router.post("/stripe")
async def stripe_webhook(request: Request, db: DbSession) -> JSONResponse:
    """Receive one Stripe event.

    ``async def`` for one reason: ``await request.body()`` is how the raw bytes
    are read before anything parses them.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = construct_event(payload, signature)
    except stripe.SignatureVerificationError:
        # Deliberately not audited to the database. An unauthenticated endpoint
        # that writes a row per bad request is a way to fill a disk.
        logger.warning("Rejected a Stripe webhook with an invalid signature")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Signature verification failed"},
        )
    except ValueError:
        logger.warning("Rejected a Stripe webhook with an unparseable body")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "Malformed payload"}
        )

    if event.type == PAYMENT_SUCCEEDED:
        return _handle_completed_checkout(db, event)

    if event.type in (CHECKOUT_ABANDONED, PAYMENT_FAILED):
        # Nothing to undo. No pending row was ever written, so an abandoned or
        # failed checkout leaves nothing behind by construction rather than by
        # cleanup - which is also why there is no reaper job to get wrong.
        audit.record(
            db,
            action="payment.checkout_failed",
            target=_target(event),
            detail=f"event={event.id} type={event.type}",
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason=event.type)

    # Stripe sends whatever the account is subscribed to. Anything else is a
    # final 200: retrying it would not make us understand it.
    return _ok(handled=False, reason=f"{event.type} is not handled")


def _handle_completed_checkout(db: DbSession, event: stripe.Event) -> JSONResponse:
    # Converted to a plain dict at the boundary. The SDK's StripeObject is
    # deliberately not a dict in v15 - .get() raises rather than returning None
    # - and treating a verified payload as data rather than as an object is
    # what this function wants anyway: every field below is optional in some
    # event shape, and a missing one must be a branch, not an AttributeError.
    session = event.data.object.to_dict()

    # A completed session is not always a paid one: with delayed payment
    # methods Stripe completes the session and settles later. Recording on
    # completion alone would credit money that has not arrived.
    if session.get("payment_status") != "paid":
        audit.record(
            db,
            action="payment.checkout_unpaid",
            target=_target(event),
            detail=f"event={event.id} payment_status={session.get('payment_status')}",
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason="session is not paid")

    metadata = session.get("metadata") or {}
    fee_assignment_id = _int_or_none(metadata.get(FEE_ASSIGNMENT_KEY))
    if fee_assignment_id is None:
        # A session created outside this application, or one whose metadata was
        # lost. Not our payment to record, and not a retry that would help.
        logger.warning("Stripe event %s carried no %s", event.id, FEE_ASSIGNMENT_KEY)
        audit.record(
            db,
            action="payment.stripe_unattributable",
            detail=f"event={event.id} session={session.get('id')}",
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason="no fee assignment in metadata")

    # Idempotency, first pass. Stripe delivers at least once and retries after
    # any timeout, so the same event arrives again routinely - not only under
    # attack. The unique index on stripe_event_id is what settles the race this
    # check cannot; both paths answer 200, because a duplicate is a success.
    already = db.scalar(select(Payment).where(Payment.stripe_event_id == event.id))
    if already is not None:
        return _ok(handled=True, recorded=False, reason="event already recorded")

    amount = Decimal(session.get("amount_total", 0)).scaleb(-2)

    try:
        payment = record_payment(
            db,
            fee_assignment_id=fee_assignment_id,
            amount=amount,
            method=PaymentMethod.STRIPE,
            stripe_payment_intent_id=_payment_intent_id(session),
            stripe_event_id=event.id,
        )
    except UnknownFeeAssignmentError:
        logger.error(
            "Stripe event %s names fee assignment %s, which does not exist",
            event.id,
            fee_assignment_id,
        )
        audit.record(
            db,
            action="payment.stripe_unattributable",
            target=f"fee_assignment:{fee_assignment_id}",
            detail=f"event={event.id} assignment no longer exists",
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason="fee assignment not found")
    except PaymentError as exc:
        # The money has already moved. Refusing to record it does not send it
        # back, so this cannot behave like the cash route's 409 - there is no
        # "try a smaller amount" available to a card that has been charged.
        #
        # The usual cause is honest: a bursar recorded cash while the parent was
        # on the payment page. Recording it anyway would break the invariant
        # that payments never exceed the bill, so instead it is flagged loudly
        # and left for a human to refund. A production system would call
        # Stripe's refund API here; doing that automatically is not something to
        # write without someone to answer for it.
        logger.error(
            "Stripe event %s could not be applied to fee assignment %s: %s",
            event.id,
            fee_assignment_id,
            exc,
        )
        audit.record(
            db,
            action="payment.stripe_needs_refund",
            target=f"fee_assignment:{fee_assignment_id}",
            detail=(f"event={event.id} amount={amount} session={session.get('id')} reason={exc}"),
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason="needs manual reconciliation")

    audit.record(
        db,
        action="payment.stripe",
        user_id=_paying_user_id(db, metadata),
        target=f"fee_assignment:{fee_assignment_id}",
        detail=f"event={event.id} payment={payment.id} amount={payment.amount_paid}",
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint != EVENT_ID_CONSTRAINT:
            # Not a duplicate. Let it 500 so Stripe retries and the failure
            # reaches the logs, rather than being reported as handled.
            raise
        # Idempotency, second pass: two deliveries of the same event racing.
        # The unique index means exactly one commits, and the loser is a
        # duplicate rather than a failure.
        logger.info("Stripe event %s was recorded concurrently", event.id)
        return _ok(handled=True, recorded=False, reason="event already recorded")

    return _ok(handled=True, recorded=True, payment_id=payment.id)


def _paying_user_id(db: DbSession, metadata: dict) -> int | None:
    """The parent whose checkout this was, if that account still exists.

    The id is ours - it was put on the session when checkout started - but it
    round-trips through Stripe and can come back days later, by which time the
    account may be gone. An audit row that cannot be written because of a stale
    foreign key would take the payment down with it, and the payment is the
    part that matters.
    """
    user_id = _int_or_none(metadata.get(PAID_BY_KEY))
    if user_id is None or db.get(User, user_id) is None:
        return None
    return user_id


def _payment_intent_id(session: dict) -> str | None:
    """The payment intent, whether Stripe expanded it or sent just the id."""
    intent = session.get("payment_intent")
    if isinstance(intent, str) or intent is None:
        return intent
    return intent.get("id")


def _target(event: stripe.Event) -> str | None:
    metadata = event.data.object.to_dict().get("metadata") or {}
    assignment_id = metadata.get(FEE_ASSIGNMENT_KEY)
    return f"fee_assignment:{assignment_id}" if assignment_id else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
