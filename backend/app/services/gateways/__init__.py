"""Payment processors, one interface, chosen by configuration.

``get_gateway()`` is the one the deployment sells through - what a parent's
pay button opens. ``gateway_for(provider)`` is for the webhook routes, which
exist per processor: a Stripe delivery is verified with Stripe's secret
whether or not Stripe is the active gateway, because a payment that was
started before a switch can still complete after it.
"""

from __future__ import annotations

from app.core.config import settings
from app.models.enums import PaymentProvider
from app.services.gateways.base import (
    FEE_ASSIGNMENT_KEY,
    PAID_BY_KEY,
    CheckoutSession,
    GatewayNotConfiguredError,
    PaymentGateway,
    WebhookEvent,
    WebhookOutcome,
    WebhookVerificationError,
    from_minor_units,
    to_minor_units,
)

__all__ = [
    "FEE_ASSIGNMENT_KEY",
    "PAID_BY_KEY",
    "CheckoutSession",
    "GatewayNotConfiguredError",
    "PaymentGateway",
    "WebhookEvent",
    "WebhookOutcome",
    "WebhookVerificationError",
    "from_minor_units",
    "gateway_for",
    "get_gateway",
    "to_minor_units",
]


def gateway_for(provider: PaymentProvider) -> PaymentGateway:
    """The implementation for one processor, built from settings.

    Built per call rather than cached: it is two strings and an object, and
    reading settings at the moment of use is what lets a test switch the
    deployment's gateway by changing settings.
    """
    if provider is PaymentProvider.STRIPE:
        from app.services.gateways.stripe import StripeGateway

        return StripeGateway(
            secret_key=settings.stripe_secret_key,
            webhook_secret=settings.stripe_webhook_secret,
            currency=settings.currency,
        )
    if provider is PaymentProvider.PAYSTACK:
        from app.services.gateways.paystack import PaystackGateway

        return PaystackGateway(secret_key=settings.paystack_secret_key, currency=settings.currency)
    raise ValueError(f"No gateway for {provider!r}")  # pragma: no cover - enum is closed


def get_gateway() -> PaymentGateway:
    """The processor this deployment takes payments through."""
    return gateway_for(settings.payment_gateway)
