"""What a payment processor has to be able to do for this ledger.

Two things, and only two: hand a parent somewhere to pay, and tell us -
verifiably - that they did. Everything else about a processor (its SDK, its
header names, its event vocabulary, whether it counts in cents or pesewas) is
that processor's business and stays inside its own module.

The interface is small on purpose. A wider one would be a description of
Stripe with the name filed off, and the second processor would fit it badly.
This one was shaped by writing both implementations and keeping what they
shared.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.models.enums import PaymentMethod, PaymentProvider
from app.services.balances import to_money

# Metadata keys travelling out with a checkout and coming back on the webhook.
# This is how a webhook - which arrives with no session, no cookie and no user
# - learns which bill was being paid. Both processors round-trip arbitrary
# metadata, and both get the same keys.
FEE_ASSIGNMENT_KEY = "fee_assignment_id"
PAID_BY_KEY = "paid_by_user_id"


class WebhookVerificationError(Exception):
    """The delivery is not from the processor: bad or missing signature."""


class GatewayNotConfiguredError(Exception):
    """The processor has no secret. Nothing can be verified, so nothing is."""


@dataclass(frozen=True)
class CheckoutSession:
    """Somewhere to send the payer, and the processor's name for the attempt."""

    id: str
    url: str


class WebhookOutcome(enum.StrEnum):
    # Money arrived. The only outcome that writes a payment row.
    PAID = "paid"
    # The checkout completed but the money has not settled - Stripe's delayed
    # methods do this. Recording on completion alone would credit money that
    # has not arrived, so it is audited and nothing else.
    UNPAID = "unpaid"
    # Abandoned or declined. Nothing to undo, since nothing was written.
    FAILED = "failed"
    # An event type this ledger does not act on. A final 200, not a retry.
    IGNORED = "ignored"


@dataclass(frozen=True)
class WebhookEvent:
    """One verified delivery, reduced to what the ledger needs.

    ``id`` is the idempotency key - whatever the processor guarantees is the
    same on a redelivery and different for a different payment. It lands in
    ``payments.provider_event_id`` under a unique index, which is what turns a
    replay into a no-op.
    """

    id: str
    type: str
    outcome: WebhookOutcome
    fee_assignment_id: int | None = None
    paid_by_user_id: int | None = None
    amount: Decimal | None = None
    currency: str | None = None
    method: PaymentMethod | None = None
    # The processor's own id for the money; what a human types into its
    # dashboard to find this payment.
    reference: str | None = None
    # Free text for the audit line: the session id, the transaction id.
    detail: str = ""


class PaymentGateway(Protocol):
    provider: PaymentProvider
    display_name: str
    # Lower-case ISO code. Each implementation formats it the way its API wants.
    currency: str
    # What a parent can pay with through this processor, for the UI to say so.
    methods: tuple[PaymentMethod, ...]

    @property
    def test_mode(self) -> bool: ...

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
    ) -> CheckoutSession: ...

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Verify a delivery and reduce it to a :class:`WebhookEvent`.

        ``payload`` must be the raw request body, byte for byte. FastAPI will
        happily hand a route the parsed JSON, but re-serialising it changes
        whitespace and key order, the HMAC no longer matches, and every
        delivery fails for a reason that looks nothing like the cause.

        Raises :class:`WebhookVerificationError` for a bad or missing
        signature, :class:`GatewayNotConfiguredError` when there is no secret
        to verify against, and :class:`ValueError` for a body that verifies but
        cannot be read.
        """
        ...


def to_minor_units(amount: Decimal) -> int:
    """250.00 -> 25000. Both processors count in the currency's smallest unit.

    ``scaleb`` shifts the decimal point on the Decimal itself rather than
    multiplying by 100.0, which would put the amount through a float on its way
    to the payment processor - the one journey it must not make.
    """
    return int(to_money(amount).scaleb(2))


def from_minor_units(amount: int) -> Decimal:
    """25000 -> 250.00, the same way back."""
    return to_money(Decimal(amount).scaleb(-2))


def int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
