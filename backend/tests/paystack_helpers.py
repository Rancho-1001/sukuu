"""Building signed Paystack webhook deliveries for tests.

The signing is real: HMAC-SHA512 of the raw body against the secret key,
hex-encoded, which is exactly what Paystack puts in ``x-paystack-signature``.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from app.core.config import settings

WEBHOOK_URL = "/webhooks/paystack"


def sign(payload: bytes, *, secret: str | None = None) -> str:
    secret = secret if secret is not None else settings.paystack_secret_key
    return hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()


def event_body(
    *,
    event_type: str = "charge.success",
    reference: str | None = "sukuu-1-abc123",
    transaction_id: int = 4_000_001,
    fee_assignment_id: int | None = 1,
    paid_by_user_id: int | None = None,
    amount: int = 25000,
    currency: str = "GHS",
    status: str = "success",
    channel: str = "mobile_money",
    metadata_as_string: bool = False,
) -> bytes:
    metadata: dict = {}
    if fee_assignment_id is not None:
        metadata["fee_assignment_id"] = str(fee_assignment_id)
    if paid_by_user_id is not None:
        metadata["paid_by_user_id"] = str(paid_by_user_id)

    data = {
        "id": transaction_id,
        "domain": "test",
        "status": status,
        "reference": reference,
        "amount": amount,
        "currency": currency,
        "channel": channel,
        "gateway_response": "Approved",
        "metadata": json.dumps(metadata) if metadata_as_string else metadata,
        "customer": {"email": "parent@example.com"},
    }
    if reference is None:
        del data["reference"]
    return json.dumps({"event": event_type, "data": data}).encode()


def deliver(api, payload: bytes, signature: str | None = None):
    return api.post(
        WEBHOOK_URL,
        content=payload,
        headers={
            "x-paystack-signature": signature if signature is not None else sign(payload),
            "content-type": "application/json",
        },
    )
