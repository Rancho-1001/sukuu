"""Opening a Stripe Checkout session.

Stripe itself is replaced here - the gateway has its own tests for what gets
sent. What matters at this layer is who may start a payment, for which bill,
and for how much.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, Payment, UserRole

pytestmark = pytest.mark.db

URL = "/payments/checkout-session"


@pytest.fixture
def stripe_calls(monkeypatch):
    """Capture what the route asks the gateway for, without leaving the box."""
    from app.api.routes import checkout
    from app.services.stripe_gateway import CheckoutSession

    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return CheckoutSession(
            id="cs_test_fake", url="https://checkout.stripe.com/c/pay/cs_test_fake"
        )

    monkeypatch.setattr(checkout.stripe_gateway, "create_checkout_session", fake_create)
    return calls


@pytest.fixture
def family(api, token_for, make_student, make_fee_type, make_fee_assignment):
    """A parent, their child, and a 250.00 bill with nothing paid."""
    parent, headers = token_for(UserRole.PARENT)
    student = make_student(parent=parent)
    bill = make_fee_assignment(student, make_fee_type(default_amount="250.00"), amount="250.00")
    return parent, headers, bill


class TestStartingAPayment:
    def test_a_parent_gets_somewhere_to_pay(self, api, family, stripe_calls):
        _, headers, bill = family
        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": "250.00"}, headers=headers
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["checkout_url"].startswith("https://checkout.stripe.com/")
        assert body["session_id"] == "cs_test_fake"
        assert body["amount"] == "250.00"

    def test_a_partial_amount_is_allowed(self, api, family, stripe_calls):
        """Paying a term in installments is the v1 feature this exists for."""
        _, headers, bill = family
        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": "50.00"}, headers=headers
        )
        assert response.status_code == 201
        assert stripe_calls[0]["amount"] == Decimal("50.00")

    def test_the_bill_travels_with_the_session(self, api, family, stripe_calls):
        parent, headers, bill = family
        api.post(URL, json={"fee_assignment_id": bill.id, "amount": "50.00"}, headers=headers)
        assert stripe_calls[0]["fee_assignment_id"] == bill.id
        assert stripe_calls[0]["paid_by_user_id"] == parent.id

    def test_the_payer_sees_what_they_are_paying_for(self, api, family, stripe_calls):
        _, headers, bill = family
        api.post(URL, json={"fee_assignment_id": bill.id, "amount": "50.00"}, headers=headers)
        assert bill.fee_type.name in stripe_calls[0]["description"]
        assert bill.period_label in stripe_calls[0]["description"]

    def test_starting_checkout_records_no_payment(self, api, family, stripe_calls, db_session):
        """Nothing is owed to the ledger until the webhook says so."""
        _, headers, bill = family
        api.post(URL, json={"fee_assignment_id": bill.id, "amount": "250.00"}, headers=headers)
        assert (
            db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all()
            == []
        )

    def test_the_attempt_is_audited(self, api, family, stripe_calls, db_session):
        """The trail that explains "I paid and it never showed up"."""
        parent, headers, bill = family
        api.post(URL, json={"fee_assignment_id": bill.id, "amount": "50.00"}, headers=headers)

        entry = db_session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "payment.checkout_started")
            .order_by(AuditLog.id.desc())
        ).first()
        assert entry is not None
        assert entry.user_id == parent.id
        assert "cs_test_fake" in entry.detail
        assert entry.target == f"fee_assignment:{bill.id}"


class TestWhoMayPay:
    def test_another_familys_bill_is_404(
        self,
        api,
        family,
        stripe_calls,
        make_user,
        make_student,
        make_fee_type,
        make_fee_assignment,
    ):
        """404 rather than 403: 403 would confirm the bill exists and let a
        parent walk the ids to learn what other families are charged."""
        _, headers, _ = family
        other_bill = make_fee_assignment(
            make_student(parent=make_user(UserRole.PARENT)),
            make_fee_type(default_amount="250.00"),
        )
        response = api.post(
            URL, json={"fee_assignment_id": other_bill.id, "amount": "10.00"}, headers=headers
        )
        assert response.status_code == 404

    def test_a_bill_with_no_parent_attached_is_404(
        self, api, family, stripe_calls, make_student, make_fee_type, make_fee_assignment
    ):
        _, headers, _ = family
        orphan = make_fee_assignment(make_student(), make_fee_type(default_amount="250.00"))
        response = api.post(
            URL, json={"fee_assignment_id": orphan.id, "amount": "10.00"}, headers=headers
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_and_admins_do_not_use_this_route(
        self, api, family, stripe_calls, headers_for, role
    ):
        """They take cash through POST /payments. Nothing here is a permission
        they lack elsewhere - it is that a staff-initiated card payment has no
        payer, and the flow would have nobody to send to the payment page."""
        _, _, bill = family
        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": "10.00"}, headers=headers_for(role)
        )
        assert response.status_code == 403

    def test_anonymous_is_rejected(self, api, family, stripe_calls):
        _, _, bill = family
        response = api.post(URL, json={"fee_assignment_id": bill.id, "amount": "10.00"})
        assert response.status_code == 401


class TestTheAmountIsCheckedFirst:
    def test_more_than_is_owed_is_refused(self, api, family, stripe_calls):
        """Better to refuse here than to send a parent to a payment page for
        money they do not owe and refund it afterwards."""
        _, headers, bill = family
        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": "250.01"}, headers=headers
        )
        assert response.status_code == 409
        assert "250.00" in response.json()["detail"]
        assert stripe_calls == []

    def test_the_balance_already_paid_is_taken_into_account(
        self, api, family, stripe_calls, make_payment
    ):
        _, headers, bill = family
        make_payment(bill, "200.00")

        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": "100.00"}, headers=headers
        )
        assert response.status_code == 409
        assert "50.00" in response.json()["detail"]

    def test_a_settled_bill_cannot_be_paid_again(self, api, family, stripe_calls, make_payment):
        _, headers, bill = family
        make_payment(bill, "250.00")

        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": "10.00"}, headers=headers
        )
        assert response.status_code == 409
        assert "paid in full" in response.json()["detail"]

    @pytest.mark.parametrize("amount", ["0.00", "-10.00"])
    def test_a_non_positive_amount_is_refused(self, api, family, stripe_calls, amount):
        _, headers, bill = family
        response = api.post(
            URL, json={"fee_assignment_id": bill.id, "amount": amount}, headers=headers
        )
        assert response.status_code == 422
        assert stripe_calls == []

    def test_an_unknown_bill_is_reported_against_the_field(self, api, family, stripe_calls):
        _, headers, _ = family
        response = api.post(
            URL, json={"fee_assignment_id": 99999999, "amount": "10.00"}, headers=headers
        )
        assert response.status_code == 422
        assert response.json()["detail"].startswith("fee_assignment_id:")

    def test_nothing_reaches_stripe_when_the_request_is_refused(self, api, family, stripe_calls):
        _, headers, bill = family
        api.post(URL, json={"fee_assignment_id": bill.id, "amount": "999.00"}, headers=headers)
        assert stripe_calls == []
