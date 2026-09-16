"""The Paystack webhook: the same ledger, a different signature.

Everything after parsing - idempotency, the lock, the needs-refund path, the
audit trail - is shared with the Stripe route and tested there. What is
tested here is the Paystack-shaped half: the signature scheme, the channel
becoming the method, the reference as the idempotency key, and the shared
handler being reached at all.

Signatures are real: HMAC-SHA512 of the raw body against the configured key.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AuditLog, Payment, PaymentMethod, PaymentProvider, UserRole
from tests.paystack_helpers import WEBHOOK_URL, deliver, event_body, sign

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def a_ghanaian_deployment(monkeypatch):
    """These tests run as a deployment that sells through Paystack, in cedis."""
    monkeypatch.setattr(settings, "payment_gateway", PaymentProvider.PAYSTACK)
    monkeypatch.setattr(settings, "payment_currency", "")


@pytest.fixture
def parent(make_user):
    return make_user(UserRole.PARENT)


@pytest.fixture
def bill(make_student, make_fee_type, make_fee_assignment, parent):
    """A 250.00 tuition bill belonging to a real parent."""
    student = make_student(parent=parent)
    return make_fee_assignment(student, make_fee_type(default_amount="250.00"), amount="250.00")


class TestSignatureVerification:
    def test_a_correctly_signed_event_is_accepted(self, api, bill):
        response = deliver(api, event_body(fee_assignment_id=bill.id))
        assert response.status_code == 200, response.text
        assert response.json()["recorded"] is True

    def test_an_unsigned_request_is_rejected(self, api, bill):
        response = api.post(WEBHOOK_URL, content=event_body(fee_assignment_id=bill.id))
        assert response.status_code == 400

    def test_a_forged_signature_is_rejected(self, api, bill):
        payload = event_body(fee_assignment_id=bill.id)
        response = deliver(api, payload, signature=sign(payload, secret="sk_test_not_ours"))
        assert response.status_code == 400

    def test_a_tampered_body_is_rejected(self, api, bill):
        """Sign a 1.00 payment, deliver a 5000.00 one."""
        honest = event_body(fee_assignment_id=bill.id, amount=100)
        tampered = honest.replace(b'"amount": 100', b'"amount": 500000')
        assert tampered != honest
        response = deliver(api, tampered, signature=sign(honest))
        assert response.status_code == 400

    def test_a_rejected_signature_records_no_payment(self, api, bill, db_session):
        api.post(WEBHOOK_URL, content=event_body(fee_assignment_id=bill.id))
        assert db_session.scalars(select(Payment)).all() == []

    def test_garbage_that_is_signed_is_still_refused(self, api):
        payload = b"this is not json"
        assert deliver(api, payload, signature=sign(payload)).status_code == 400

    def test_a_stripe_signature_on_the_paystack_route_is_nothing(self, api, bill):
        """Each route verifies with its own processor's scheme and secret."""
        from tests.stripe_helpers import sign as stripe_sign

        payload = event_body(fee_assignment_id=bill.id)
        response = api.post(
            WEBHOOK_URL,
            content=payload,
            headers={"stripe-signature": stripe_sign(payload)},
        )
        assert response.status_code == 400


class TestRecordingThePayment:
    def test_a_mobile_money_payment_is_recorded_as_one(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, channel="mobile_money"))
        payment = db_session.scalars(select(Payment)).one()
        assert payment.fee_assignment_id == bill.id
        assert payment.amount_paid == Decimal("250.00")
        assert payment.method is PaymentMethod.MOBILE_MONEY
        assert payment.provider is PaymentProvider.PAYSTACK
        assert payment.recorded_by_id is None

    def test_a_card_payment_is_recorded_as_one(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, channel="card"))
        assert db_session.scalars(select(Payment)).one().method is PaymentMethod.CARD

    def test_the_reference_is_kept_where_a_human_can_find_it(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, reference="sukuu-1-feedface"))
        payment = db_session.scalars(select(Payment)).one()
        assert payment.provider_reference == "sukuu-1-feedface"
        assert payment.provider_event_id == "charge.success:sukuu-1-feedface"

    def test_the_balance_moves(self, api, bill, staff_headers):
        deliver(api, event_body(fee_assignment_id=bill.id, amount=10000))
        body = api.get(f"/fee-assignments/{bill.id}", headers=staff_headers).json()
        assert body["amount_paid"] == "100.00"
        assert body["outstanding"] == "150.00"

    def test_the_audit_row_names_the_processor_and_the_method(self, api, bill, parent, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, paid_by_user_id=parent.id))
        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.action == "payment.online")
        ).one()
        assert entry.user_id == parent.id
        assert "provider=paystack" in entry.detail
        assert "method=mobile_money" in entry.detail
        assert "reference=sukuu-1-abc123" in entry.detail


class TestIdempotency:
    def test_a_replayed_delivery_does_not_pay_twice(self, api, bill, db_session):
        payload = event_body(fee_assignment_id=bill.id, amount=10000)
        first = deliver(api, payload)
        second = deliver(api, payload)
        assert first.json()["recorded"] is True
        assert second.status_code == 200
        assert second.json()["recorded"] is False
        assert "already recorded" in second.json()["reason"]
        assert len(db_session.scalars(select(Payment)).all()) == 1

    def test_two_different_references_both_land(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, amount=10000, reference="sukuu-a"))
        deliver(api, event_body(fee_assignment_id=bill.id, amount=10000, reference="sukuu-b"))
        assert len(db_session.scalars(select(Payment)).all()) == 2

    def test_a_stripe_event_with_the_same_id_is_a_different_event(self, api, bill, db_session):
        """The unique index is scoped by provider. Deliberately contrived - the
        namespaces do not overlap in practice - but the index must be right
        for the day something else shares an id format."""
        from tests.stripe_helpers import deliver as stripe_deliver
        from tests.stripe_helpers import event_body as stripe_event

        deliver(api, event_body(fee_assignment_id=bill.id, amount=10000, reference="shared"))
        stripe_deliver(
            api,
            stripe_event(
                fee_assignment_id=bill.id,
                amount_total=10000,
                event_id="charge.success:shared",
                currency="ghs",
            ),
        )
        assert len(db_session.scalars(select(Payment)).all()) == 2


class TestEventsThatRecordNothing:
    def test_a_charge_that_did_not_succeed_records_nothing(self, api, bill, db_session):
        response = deliver(api, event_body(fee_assignment_id=bill.id, status="failed"))
        assert response.status_code == 200
        assert response.json()["recorded"] is False
        assert db_session.scalars(select(Payment)).all() == []
        assert (
            db_session.scalar(select(AuditLog).where(AuditLog.action == "payment.checkout_unpaid"))
            is not None
        )

    def test_an_event_type_we_do_not_handle_is_a_final_200(self, api, bill):
        response = deliver(
            api, event_body(fee_assignment_id=bill.id, event_type="transfer.success")
        )
        assert response.status_code == 200
        assert response.json()["handled"] is False

    def test_a_charge_with_no_metadata_is_not_our_payment(self, api, db_session):
        response = deliver(api, event_body(fee_assignment_id=None))
        assert response.status_code == 200
        assert response.json()["recorded"] is False
        assert (
            db_session.scalar(
                select(AuditLog).where(AuditLog.action == "payment.online_unattributable")
            )
            is not None
        )

    def test_a_success_without_a_reference_is_malformed(self, api, bill):
        """Nothing to key idempotency on, so nothing safe to record."""
        response = deliver(api, event_body(fee_assignment_id=bill.id, reference=None))
        assert response.status_code == 400


class TestMoneyThatCannotBeApplied:
    def test_an_overpayment_is_flagged_for_a_human(self, api, bill, staff_headers, db_session):
        """The shared path, reached through this route."""
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "250.00"},
            headers=staff_headers,
        )
        response = deliver(api, event_body(fee_assignment_id=bill.id, amount=25000))
        assert response.json()["recorded"] is False
        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.action == "payment.online_needs_refund")
        ).one()
        assert "provider=paystack" in entry.detail

    def test_the_wrong_currency_is_flagged_for_a_human(self, api, bill, db_session):
        response = deliver(api, event_body(fee_assignment_id=bill.id, currency="NGN"))
        assert response.json()["recorded"] is False
        assert db_session.scalars(select(Payment)).all() == []


class TestWithoutASecret:
    def test_every_delivery_is_refused(self, api, bill, monkeypatch, db_session):
        monkeypatch.setattr(settings, "paystack_secret_key", "")
        payload = event_body(fee_assignment_id=bill.id)
        response = deliver(api, payload, signature=sign(payload, secret=""))
        assert response.status_code == 503
        assert db_session.scalars(select(Payment)).all() == []
