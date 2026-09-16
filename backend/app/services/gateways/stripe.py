"""Stripe, behind the gateway interface. The only module that imports its SDK.

Right for the United States and Canada; does not operate in Ghana.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import stripe

from app.models.enums import PaymentMethod, PaymentProvider
from app.services.gateways.base import (
    FEE_ASSIGNMENT_KEY,
    PAID_BY_KEY,
    CheckoutSession,
    GatewayNotConfiguredError,
    WebhookEvent,
    WebhookOutcome,
    WebhookVerificationError,
    from_minor_units,
    int_or_none,
    to_minor_units,
)

PAYMENT_SUCCEEDED = "checkout.session.completed"
CHECKOUT_ABANDONED = "checkout.session.expired"
PAYMENT_FAILED = "payment_intent.payment_failed"

SIGNATURE_HEADER = "stripe-signature"


class StripeGateway:
    provider = PaymentProvider.STRIPE
    display_name = "Stripe"
    # Card only, for now, and said so explicitly: it is what makes recording
    # every Stripe payment as a card payment true rather than approximately
    # true. ACH debit for the US and pre-authorised debit for Canada are the
    # next channels, and adding them means reading the method off the
    # session instead of assuming it.
    methods = (PaymentMethod.CARD,)

    def __init__(self, *, secret_key: str, webhook_secret: str, currency: str) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self.currency = currency.lower()

    @property
    def test_mode(self) -> bool:
        return self._secret_key.startswith("sk_test_")

    def create_checkout(
        self,
        *,
        amount: Decimal,
        fee_assignment_id: int,
        paid_by_user_id: int,
        payer_email: str,
        description: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        metadata = {FEE_ASSIGNMENT_KEY: str(fee_assignment_id), PAID_BY_KEY: str(paid_by_user_id)}
        session = stripe.checkout.Session.create(
            api_key=self._secret_key,
            mode="payment",
            payment_method_types=["card"],
            customer_email=payer_email,
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": self.currency,
                        "unit_amount": to_minor_units(amount),
                        "product_data": {"name": description},
                    },
                }
            ],
            # Metadata on the session *and* on the payment intent it creates:
            # the two are different objects, and which one a given webhook
            # event carries depends on the event type.
            metadata=metadata,
            payment_intent_data={"metadata": metadata},
        )
        return CheckoutSession(id=session.id, url=session.url)

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        if not self._webhook_secret:
            raise GatewayNotConfiguredError("STRIPE_WEBHOOK_SECRET is not set")
        try:
            event = stripe.Webhook.construct_event(
                payload, headers.get(SIGNATURE_HEADER, ""), self._webhook_secret
            )
        except stripe.SignatureVerificationError as exc:
            # Covers a missing header, a wrong secret, a tampered body, and a
            # timestamp outside Stripe's tolerance - which is what stops a
            # captured payload being replayed at leisure.
            raise WebhookVerificationError(str(exc)) from exc

        # A plain dict at the boundary. The SDK's StripeObject is deliberately
        # not a dict in v15 - .get() raises rather than returning None - and
        # every field below is optional in some event shape.
        obj = event.data.object.to_dict()
        metadata = obj.get("metadata") or {}
        common = {
            "id": event.id,
            "type": event.type,
            "fee_assignment_id": int_or_none(metadata.get(FEE_ASSIGNMENT_KEY)),
            "paid_by_user_id": int_or_none(metadata.get(PAID_BY_KEY)),
            "detail": f"session={obj.get('id')}",
        }

        if event.type == PAYMENT_SUCCEEDED:
            if obj.get("payment_status") != "paid":
                common["detail"] += f" payment_status={obj.get('payment_status')}"
                return WebhookEvent(outcome=WebhookOutcome.UNPAID, **common)
            return WebhookEvent(
                outcome=WebhookOutcome.PAID,
                amount=from_minor_units(int(obj.get("amount_total") or 0)),
                currency=(obj.get("currency") or "").lower() or None,
                method=PaymentMethod.CARD,
                reference=_payment_intent_id(obj),
                **common,
            )

        if event.type in (CHECKOUT_ABANDONED, PAYMENT_FAILED):
            return WebhookEvent(outcome=WebhookOutcome.FAILED, **common)

        return WebhookEvent(outcome=WebhookOutcome.IGNORED, **common)


def _payment_intent_id(session: dict) -> str | None:
    """The payment intent, whether Stripe expanded it or sent just the id."""
    intent = session.get("payment_intent")
    if isinstance(intent, str) or intent is None:
        return intent
    return intent.get("id")
