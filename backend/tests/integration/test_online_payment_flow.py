"""Phase 5's "done when": killing the browser mid-payment still results in a
correctly recorded payment.

Every other test in this area checks one half. This walks the whole arc a
parent walks - open a checkout session, then vanish - and takes the metadata
for the webhook out of what the gateway was actually asked to send, rather
than hand-writing it. That is the join the two halves could get wrong
independently: the session puts ``fee_assignment_id`` in, the webhook reads it
out, and nothing else connects them.

The browser is never involved after the redirect to Stripe. There is no
success-URL handler in this application on purpose, so "the laptop was closed"
and "the payment page was never returned from" are not special cases here -
they are the only case.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, Payment, PaymentMethod, UserRole
from app.services.stripe_gateway import CheckoutSession, to_minor_units
from tests.stripe_helpers import deliver, event_body

pytestmark = pytest.mark.db


@pytest.fixture
def stripe_calls(monkeypatch):
    from app.api.routes import checkout

    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return CheckoutSession(
            id=f"cs_test_{len(calls)}", url=f"https://checkout.stripe.com/c/pay/cs_{len(calls)}"
        )

    monkeypatch.setattr(checkout.stripe_gateway, "create_checkout_session", fake_create)
    return calls


@pytest.fixture
def parent_with_a_bill(token_for, make_student, make_fee_type, make_fee_assignment):
    parent, headers = token_for(UserRole.PARENT)
    student = make_student(parent=parent, first_name="Ama", last_name="Mensah")
    bill = make_fee_assignment(
        student, make_fee_type(name="Tuition ", default_amount="250.00"), amount="250.00"
    )
    return parent, headers, bill


def webhook_for(call: dict, *, event_id: str, session_id: str = "cs_test_1") -> bytes:
    """Build the delivery Stripe would send for a completed checkout.

    Fields come from what the gateway was asked to create, so a mismatch
    between the two halves shows up here instead of in production.
    """
    return event_body(
        event_id=event_id,
        session_id=session_id,
        fee_assignment_id=call["fee_assignment_id"],
        paid_by_user_id=call["paid_by_user_id"],
        amount_total=to_minor_units(call["amount"]),
    )


def test_the_payment_lands_even_though_the_browser_never_came_back(
    api, parent_with_a_bill, stripe_calls, db_session
):
    parent, headers, bill = parent_with_a_bill

    # 1. The parent chooses to pay half now.
    started = api.post(
        "/payments/checkout-session",
        json={"fee_assignment_id": bill.id, "amount": "125.00"},
        headers=headers,
    )
    assert started.status_code == 201
    assert started.json()["checkout_url"].startswith("https://checkout.stripe.com/")

    # 2. Nothing has been paid yet. The session is an intention, not a payment.
    assert api.get(f"/students/{bill.student_id}/balance", headers=headers).json()["paid"] == "0.00"

    # 3. The laptop closes. No success URL is ever requested - there is nowhere
    #    for it to go. Stripe delivers the event regardless.
    delivered = deliver(api, webhook_for(stripe_calls[0], event_id="evt_flow_1"))
    assert delivered.status_code == 200
    assert delivered.json()["recorded"] is True

    # 4. The parent, logging back in later, sees the payment against the bill.
    balance = api.get(f"/students/{bill.student_id}/balance", headers=headers).json()
    assert balance["paid"] == "125.00"
    assert balance["outstanding"] == "125.00"
    assert balance["lines"][0]["amount_paid"] == "125.00"

    history = api.get(f"/students/{bill.student_id}/payments", headers=headers).json()
    assert history["total"] == 1
    assert history["items"][0]["method"] == "stripe"
    assert history["items"][0]["recorded_by"] is None

    payment = db_session.scalar(select(Payment).where(Payment.fee_assignment_id == bill.id))
    assert payment.method is PaymentMethod.STRIPE
    assert payment.amount_paid == Decimal("125.00")
    assert payment.stripe_event_id == "evt_flow_1"


def test_the_rest_can_be_paid_in_a_second_session(
    api, parent_with_a_bill, stripe_calls, db_session
):
    """Installments across two separate checkouts, which is the feature the
    whole online flow exists for."""
    _, headers, bill = parent_with_a_bill

    api.post(
        "/payments/checkout-session",
        json={"fee_assignment_id": bill.id, "amount": "125.00"},
        headers=headers,
    )
    deliver(api, webhook_for(stripe_calls[0], event_id="evt_part_1", session_id="cs_test_1"))

    api.post(
        "/payments/checkout-session",
        json={"fee_assignment_id": bill.id, "amount": "125.00"},
        headers=headers,
    )
    deliver(api, webhook_for(stripe_calls[1], event_id="evt_part_2", session_id="cs_test_2"))

    balance = api.get(f"/students/{bill.student_id}/balance", headers=headers).json()
    assert balance["paid"] == "250.00"
    assert balance["outstanding"] == "0.00"
    assert balance["lines"][0]["settled"] is True


def test_a_retried_delivery_after_a_timeout_does_not_charge_twice(
    api, parent_with_a_bill, stripe_calls, db_session
):
    """Stripe retries anything it does not see a 2xx for, and a timeout looks
    identical to a failure from its side even when the payment was recorded."""
    _, headers, bill = parent_with_a_bill

    api.post(
        "/payments/checkout-session",
        json={"fee_assignment_id": bill.id, "amount": "250.00"},
        headers=headers,
    )
    delivery = webhook_for(stripe_calls[0], event_id="evt_retried")

    for _ in range(3):
        assert deliver(api, delivery).status_code == 200

    assert (
        len(db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all())
        == 1
    )
    assert (
        api.get(f"/students/{bill.student_id}/balance", headers=headers).json()["paid"] == "250.00"
    )


def test_an_abandoned_checkout_leaves_the_bill_exactly_as_it_was(
    api, parent_with_a_bill, stripe_calls, db_session
):
    """The parent opened the page and closed it. No pending row was written, so
    there is nothing to expire and nothing to clean up."""
    _, headers, bill = parent_with_a_bill

    api.post(
        "/payments/checkout-session",
        json={"fee_assignment_id": bill.id, "amount": "250.00"},
        headers=headers,
    )
    expired = event_body(
        event_id="evt_expired",
        event_type="checkout.session.expired",
        fee_assignment_id=bill.id,
        amount_total=25000,
    )
    assert deliver(api, expired).status_code == 200

    balance = api.get(f"/students/{bill.student_id}/balance", headers=headers).json()
    assert balance["paid"] == "0.00"
    assert balance["outstanding"] == "250.00"
    assert (
        db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all() == []
    )

    # The attempt is still on the record, which is what answers "I tried to pay".
    started = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "payment.checkout_started")
    ).all()
    assert started != []
