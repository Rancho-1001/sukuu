"""Building signed Stripe webhook deliveries for tests.

Shared by the webhook tests and the end-to-end flow test. The signing is real:
the same HMAC scheme Stripe uses, against the configured test secret, so
``construct_event`` does in tests exactly what it will do in production.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from app.core.config import settings

WEBHOOK_URL = "/webhooks/stripe"


def sign(payload: bytes, *, timestamp: int | None = None, secret: str | None = None) -> str:
    """Build a Stripe-Signature header exactly as Stripe would.

    The timestamp is inside the signed payload, which is what stops a captured
    request being replayed a week later: change it and the HMAC no longer
    matches, leave it and it falls outside the tolerance window.
    """
    timestamp = timestamp if timestamp is not None else int(time.time())
    secret = secret if secret is not None else settings.stripe_webhook_secret
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def event_body(
    *,
    event_id: str = "evt_test_1",
    event_type: str = "checkout.session.completed",
    fee_assignment_id: int | None = 1,
    paid_by_user_id: int | None = None,
    amount_total: int = 25000,
    payment_status: str = "paid",
    session_id: str = "cs_test_1",
    payment_intent: str | None = "pi_test_1",
) -> bytes:
    metadata = {}
    if fee_assignment_id is not None:
        metadata["fee_assignment_id"] = str(fee_assignment_id)
    if paid_by_user_id is not None:
        metadata["paid_by_user_id"] = str(paid_by_user_id)

    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "api_version": "2024-06-20",
            "created": int(time.time()),
            "type": event_type,
            "data": {
                "object": {
                    "id": session_id,
                    "object": "checkout.session",
                    "payment_status": payment_status,
                    "amount_total": amount_total,
                    "currency": "usd",
                    "payment_intent": payment_intent,
                    "metadata": metadata,
                }
            },
        }
    ).encode()


def deliver(api, payload: bytes, signature: str | None = None):
    return api.post(
        WEBHOOK_URL,
        content=payload,
        headers={
            "stripe-signature": signature if signature is not None else sign(payload),
            "content-type": "application/json",
        },
    )
