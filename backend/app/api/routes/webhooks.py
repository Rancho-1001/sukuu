"""Processor webhooks: the only place an online payment becomes a payment row.

**Why not the browser redirect.** Every processor sends the payer back to a
success URL when checkout finishes, and it is tempting to record the payment
there - the user is right in front of you and the page knows the session id.
But that request comes from the browser, which means anyone can issue it,
with any session id, having paid nothing. The redirect is a *hint* that
something happened; the signed webhook is the only evidence. So the success
page shows "we are confirming your payment" and this module is what makes it
true.

It is also what makes the flow survive a closed laptop: the webhook arrives
whether or not the browser ever came back.

**One handler, one route per processor.** Verifying and reading a delivery is
processor-specific and lives in ``services/gateways``. Everything after that
- the idempotency check, the lock, the needs-refund path, the audit trail - is
the ledger's business and is the same code for both. A route per processor
because each has its own URL registered in its own dashboard, and because a
payment started through Stripe before a deployment switched to Paystack can
still complete afterwards.

**Authentication.** No token, because processors do not have one. The
signature is the authentication: an HMAC of the raw body against a shared
secret. A gateway with no secret configured refuses every delivery outright -
an HMAC against an empty key is a signature anyone can produce.

**Answering 200.** Processors retry anything that is not a 2xx, with backoff,
for days. That is right for "the database was down" and wrong for everything
else: an event we do not handle, a duplicate we have already recorded, a
payment we cannot apply. Those are all final answers, and they are all 200
with a body that says what happened. The only 400 here is a delivery that
does not verify.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.models import Payment, PaymentProvider, User
from app.services import audit
from app.services.balances import PaymentError
from app.services.gateways import (
    GatewayNotConfiguredError,
    PaymentGateway,
    WebhookEvent,
    WebhookOutcome,
    WebhookVerificationError,
    gateway_for,
)
from app.services.payments import UnknownFeeAssignmentError, record_payment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# The unique constraint on (provider, provider_event_id), by the name the
# database knows it. Checked explicitly below rather than treating any
# IntegrityError as a duplicate: a foreign key or CHECK violation answered with
# "already recorded" would tell the processor the payment was handled, stop the
# retries, and lose the money silently behind a 200.
EVENT_ID_CONSTRAINT = "provider_event_id"


def _ok(**body: object) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_200_OK, content={"received": True, **body})


def _refused(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.post("/stripe")
async def stripe_webhook(request: Request, db: DbSession) -> JSONResponse:
    return await _receive(request, db, gateway_for(PaymentProvider.STRIPE))


@router.post("/paystack")
async def paystack_webhook(request: Request, db: DbSession) -> JSONResponse:
    return await _receive(request, db, gateway_for(PaymentProvider.PAYSTACK))


async def _receive(request: Request, db: DbSession, gateway: PaymentGateway) -> JSONResponse:
    """Verify one delivery and hand it to the ledger.

    ``async`` for one reason: ``await request.body()`` is how the raw bytes
    are read before anything parses them.
    """
    payload = await request.body()
    name = gateway.display_name
    try:
        event = gateway.parse_webhook(payload, request.headers)
    except GatewayNotConfiguredError as exc:
        # Deliberately loud and deliberately not a 200: the processor will
        # retry, which is right, because the fix is a deploy away.
        logger.error("Refused a %s webhook: %s", name, exc)
        return _refused(status.HTTP_503_SERVICE_UNAVAILABLE, f"{name} webhooks are not configured")
    except WebhookVerificationError:
        # Deliberately not audited to the database. An unauthenticated endpoint
        # that writes a row per bad request is a way to fill a disk.
        logger.warning("Rejected a %s webhook with an invalid signature", name)
        return _refused(status.HTTP_400_BAD_REQUEST, "Signature verification failed")
    except ValueError:
        logger.warning("Rejected a %s webhook with an unreadable body", name)
        return _refused(status.HTTP_400_BAD_REQUEST, "Malformed payload")

    return _apply(db, gateway, event)


def _apply(db: DbSession, gateway: PaymentGateway, event: WebhookEvent) -> JSONResponse:
    provider = gateway.provider.value
    target = f"fee_assignment:{event.fee_assignment_id}" if event.fee_assignment_id else None
    stamp = f"provider={provider} event={event.id} {event.detail}".strip()

    if event.outcome is WebhookOutcome.IGNORED:
        # The processor sends whatever the account is subscribed to. Anything
        # else is a final 200: retrying it would not make us understand it.
        return _ok(handled=False, reason=f"{event.type} is not handled")

    if event.outcome is WebhookOutcome.FAILED:
        # Nothing to undo. No pending row was ever written, so an abandoned or
        # failed checkout leaves nothing behind by construction rather than by
        # cleanup - which is also why there is no reaper job to get wrong.
        audit.record(
            db, action="payment.checkout_failed", target=target, detail=f"{stamp} type={event.type}"
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason=event.type)

    if event.outcome is WebhookOutcome.UNPAID:
        audit.record(db, action="payment.checkout_unpaid", target=target, detail=stamp)
        db.commit()
        return _ok(handled=True, recorded=False, reason="payment has not settled")

    if event.fee_assignment_id is None:
        # A checkout opened outside this application, or one whose metadata
        # was lost. Not our payment to record, and not a retry that would help.
        logger.warning("%s event %s carried no fee assignment", gateway.display_name, event.id)
        audit.record(db, action="payment.online_unattributable", detail=stamp)
        db.commit()
        return _ok(handled=True, recorded=False, reason="no fee assignment in metadata")

    # Idempotency, first pass. Processors deliver at least once and retry after
    # any timeout, so the same event arrives again routinely - not only under
    # attack. The unique index is what settles the race this check cannot;
    # both paths answer 200, because a duplicate is a success.
    already = db.scalar(
        select(Payment.id).where(
            Payment.provider == gateway.provider, Payment.provider_event_id == event.id
        )
    )
    if already is not None:
        return _ok(handled=True, recorded=False, reason="event already recorded")

    if event.currency != gateway.currency:
        # Money in the wrong currency cannot be applied at face value, and it
        # has already moved. Same answer as an overpayment: flag it for a human.
        logger.error(
            "%s event %s is in %s, not %s", provider, event.id, event.currency, gateway.currency
        )
        audit.record(
            db,
            action="payment.online_needs_refund",
            target=target,
            detail=f"{stamp} amount={event.amount} reason=currency is {event.currency}",
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason="needs manual reconciliation")

    try:
        payment = record_payment(
            db,
            fee_assignment_id=event.fee_assignment_id,
            amount=event.amount,  # type: ignore[arg-type]
            method=event.method,  # type: ignore[arg-type]
            provider=gateway.provider,
            provider_reference=event.reference,
            provider_event_id=event.id,
        )
    except UnknownFeeAssignmentError:
        logger.error("%s event %s names a fee assignment that does not exist", provider, event.id)
        audit.record(
            db,
            action="payment.online_unattributable",
            target=target,
            detail=f"{stamp} assignment no longer exists",
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
        # and left for a human to refund. A production system would call the
        # processor's refund API here; doing that automatically is not
        # something to write without someone to answer for it.
        logger.error("%s event %s could not be applied: %s", provider, event.id, exc)
        audit.record(
            db,
            action="payment.online_needs_refund",
            target=target,
            detail=f"{stamp} amount={event.amount} reason={exc}",
        )
        db.commit()
        return _ok(handled=True, recorded=False, reason="needs manual reconciliation")

    audit.record(
        db,
        action="payment.online",
        user_id=_paying_user_id(db, event.paid_by_user_id),
        target=target,
        detail=(
            f"{stamp} payment={payment.id} amount={payment.amount_paid}"
            f" method={payment.method.value}"
        ),
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint != EVENT_ID_CONSTRAINT:
            # Not a duplicate. Let it 500 so the processor retries and the
            # failure reaches the logs, rather than being reported as handled.
            raise
        # Idempotency, second pass: two deliveries of the same event racing.
        # The unique index means exactly one commits, and the loser is a
        # duplicate rather than a failure.
        logger.info("%s event %s was recorded concurrently", provider, event.id)
        return _ok(handled=True, recorded=False, reason="event already recorded")

    return _ok(handled=True, recorded=True, payment_id=payment.id)


def _paying_user_id(db: DbSession, user_id: int | None) -> int | None:
    """The parent whose checkout this was, if that account still exists.

    The id is ours - it was put on the checkout when it started - but it
    round-trips through the processor and can come back days later, by which
    time the account may be gone. An audit row that cannot be written because
    of a stale foreign key would take the payment down with it, and the
    payment is the part that matters.
    """
    if user_id is None or db.get(User, user_id) is None:
        return None
    return user_id
