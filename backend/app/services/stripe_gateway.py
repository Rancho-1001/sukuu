"""The only module that touches the Stripe SDK.

Everything Stripe-shaped is behind these three functions so that the routes
stay about fees and permissions, the tests have one seam to patch, and the
day this school actually needs Paystack - Stripe does not operate in Ghana -
the replacement is a file rather than a search.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import stripe

from app.core.config import settings
from app.services.balances import to_money

# Metadata keys travelling with the session and coming back on the event. This
# is how a webhook - which arrives with no session, no cookie and no user -
# learns which bill was being paid.
FEE_ASSIGNMENT_KEY = "fee_assignment_id"
PAID_BY_KEY = "paid_by_user_id"


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


def to_minor_units(amount: Decimal) -> int:
    """250.00 -> 25000. Stripe counts in the currency's smallest unit.

    ``scaleb`` shifts the decimal point on the Decimal itself rather than
    multiplying by 100.0, which would put the amount through a float on its way
    to the payment processor - the one journey it must not make.
    """
    return int(to_money(amount).scaleb(2))


def create_checkout_session(
    *,
    amount: Decimal,
    fee_assignment_id: int,
    paid_by_user_id: int,
    description: str,
) -> CheckoutSession:
    """Hand Stripe a bill and get back somewhere to send the payer."""
    session = stripe.checkout.Session.create(
        api_key=settings.stripe_secret_key,
        mode="payment",
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": settings.stripe_currency,
                    "unit_amount": to_minor_units(amount),
                    "product_data": {"name": description},
                },
            }
        ],
        # Metadata on the session *and* on the payment intent it creates: the
        # two are different objects, and which one a given webhook event
        # carries depends on the event type.
        metadata={
            FEE_ASSIGNMENT_KEY: str(fee_assignment_id),
            PAID_BY_KEY: str(paid_by_user_id),
        },
        payment_intent_data={
            "metadata": {
                FEE_ASSIGNMENT_KEY: str(fee_assignment_id),
                PAID_BY_KEY: str(paid_by_user_id),
            }
        },
    )
    return CheckoutSession(id=session.id, url=session.url)


def construct_event(payload: bytes, signature: str) -> stripe.Event:
    """Verify a webhook's signature and parse it.

    ``payload`` must be the raw request body, byte for byte. FastAPI will
    happily hand a route the parsed JSON, but re-serialising it changes
    whitespace and key order, the HMAC no longer matches, and every delivery
    fails for a reason that looks nothing like the cause.

    Raises :class:`stripe.SignatureVerificationError` for a bad signature, a
    missing header, or a timestamp outside Stripe's tolerance - which is what
    stops a captured payload being replayed at leisure.
    """
    return stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
