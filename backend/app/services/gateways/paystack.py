"""Paystack, behind the gateway interface. No SDK: two HTTP calls and an HMAC.

Right for Ghana, and the reason this interface exists. The channel that
matters there is mobile money - MTN MoMo, Telecel Cash, AT Money - which is
how most school fees are actually paid, and which Paystack offers as a
checkout option alongside cards.

Differences from Stripe that shaped the code:

* One secret. The API key is also the webhook signing key. There is no
  separate ``whsec_``.
* The signature is HMAC-SHA512 of the raw body, hex-encoded, in
  ``x-paystack-signature`` - and there is no timestamp in it. A captured
  delivery could be replayed later; what makes that harmless is the
  idempotency key, not the signature. Paystack's other defence is a fixed set
  of source addresses, which belongs at the edge rather than here.
* No event id. A successful charge is identified by its transaction
  reference, which is unique and which Paystack only ever reports as
  successful once - so ``charge.success:<reference>`` is the idempotency key.
* No failure webhooks for a one-off checkout. An abandoned payment is silence,
  which is fine: nothing was written, so there is nothing to undo.
* The payer's email is required to open a checkout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from decimal import Decimal

import httpx2 as httpx

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

API_BASE = "https://api.paystack.co"
CHARGE_SUCCEEDED = "charge.success"
SIGNATURE_HEADER = "x-paystack-signature"

# Paystack's channel names, to what the bursar means by "method". Cards and
# the wallets that front them are cards; everything that moves money between
# bank accounts - USSD, transfer, EFT - is a bank payment.
CHANNELS = {
    "card": PaymentMethod.CARD,
    "apple_pay": PaymentMethod.CARD,
    "mobile_money": PaymentMethod.MOBILE_MONEY,
}


class PaystackError(Exception):
    """Paystack answered, and the answer was no."""


class PaystackGateway:
    provider = PaymentProvider.PAYSTACK
    display_name = "Paystack"
    methods = (PaymentMethod.MOBILE_MONEY, PaymentMethod.CARD, PaymentMethod.BANK)

    def __init__(self, *, secret_key: str, currency: str) -> None:
        self._secret_key = secret_key
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
        if not self._secret_key:
            raise GatewayNotConfiguredError("PAYSTACK_SECRET_KEY is not set")
        # Our own reference rather than Paystack's, so the audit row written
        # when checkout starts already names what the webhook will carry back.
        reference = f"sukuu-{fee_assignment_id}-{secrets.token_hex(8)}"
        response = httpx.post(
            f"{API_BASE}/transaction/initialize",
            headers={"Authorization": f"Bearer {self._secret_key}"},
            json={
                "email": payer_email,
                "amount": to_minor_units(amount),
                "currency": self.currency.upper(),
                "reference": reference,
                "callback_url": success_url,
                "metadata": {
                    FEE_ASSIGNMENT_KEY: str(fee_assignment_id),
                    PAID_BY_KEY: str(paid_by_user_id),
                    # Where the hosted page sends a payer who backs out.
                    "cancel_action": cancel_url,
                    # Shown on the hosted page and in the dashboard.
                    "custom_fields": [
                        {
                            "display_name": "Payment for",
                            "variable_name": "payment_for",
                            "value": description,
                        }
                    ],
                },
            },
            timeout=20,
        )
        body = _json_or_error(response)
        if response.status_code >= 400 or not body.get("status"):
            raise PaystackError(body.get("message") or f"HTTP {response.status_code}")
        data = body["data"]
        return CheckoutSession(id=data["reference"], url=data["authorization_url"])

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        if not self._secret_key:
            raise GatewayNotConfiguredError("PAYSTACK_SECRET_KEY is not set")
        expected = hmac.new(self._secret_key.encode(), payload, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, headers.get(SIGNATURE_HEADER, "")):
            raise WebhookVerificationError("x-paystack-signature does not match the body")

        try:
            body = json.loads(payload)
            event_type = body["event"]
            data = body["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Paystack delivery is not a readable event") from exc
        if not isinstance(data, dict):
            raise ValueError("Paystack delivery has no data object")

        reference = data.get("reference")
        metadata = _metadata(data)
        common = {
            "type": event_type,
            "fee_assignment_id": int_or_none(metadata.get(FEE_ASSIGNMENT_KEY)),
            "paid_by_user_id": int_or_none(metadata.get(PAID_BY_KEY)),
            "reference": reference,
            "detail": f"reference={reference} transaction={data.get('id')}",
        }

        if event_type != CHARGE_SUCCEEDED:
            return WebhookEvent(
                id=f"{event_type}:{data.get('id') or reference}",
                outcome=WebhookOutcome.IGNORED,
                **common,
            )
        if not reference:
            raise ValueError("charge.success without a reference cannot be recorded")

        event_id = f"{CHARGE_SUCCEEDED}:{reference}"
        if data.get("status") != "success":
            common["detail"] += f" status={data.get('status')}"
            return WebhookEvent(id=event_id, outcome=WebhookOutcome.UNPAID, **common)

        channel = data.get("channel") or ""
        return WebhookEvent(
            id=event_id,
            outcome=WebhookOutcome.PAID,
            amount=from_minor_units(int(data.get("amount") or 0)),
            currency=(data.get("currency") or "").lower() or None,
            method=CHANNELS.get(channel, PaymentMethod.BANK),
            **common,
        )


def _metadata(data: dict) -> dict:
    """Paystack echoes metadata back as sent - usually. Some paths return it as
    a JSON string, and a checkout opened outside this app has none."""
    metadata = data.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return {}
    return metadata if isinstance(metadata, dict) else {}


def _json_or_error(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise PaystackError(f"HTTP {response.status_code}: not JSON") from exc
    return body if isinstance(body, dict) else {}
