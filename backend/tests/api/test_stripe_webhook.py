"""The Stripe webhook: the only route that turns money into a payment row.

Signatures here are *real*. Each payload is signed with the same HMAC scheme
Stripe uses, against the test webhook secret, so ``construct_event`` does the
work it will do in production. Patching the verification out would leave the
one security control on an unauthenticated endpoint untested.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, Payment, PaymentMethod, UserRole
from tests.stripe_helpers import WEBHOOK_URL, deliver, event_body, sign

pytestmark = pytest.mark.db


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
        response = deliver(api, payload, signature=sign(payload, secret="whsec_not_the_secret"))
        assert response.status_code == 400

    def test_a_tampered_body_is_rejected(self, api, bill):
        """Sign a 1.00 payment, deliver a 5000.00 one. This is the attack the
        signature exists to stop, and it is why the raw bytes are what get
        verified rather than a re-serialised parse of them."""
        honest = event_body(fee_assignment_id=bill.id, amount_total=100)
        signature = sign(honest)
        tampered = honest.replace(b'"amount_total": 100', b'"amount_total": 500000')
        assert tampered != honest

        response = deliver(api, tampered, signature=signature)
        assert response.status_code == 400

    def test_an_old_timestamp_is_rejected(self, api, bill):
        """A captured delivery replayed later. The timestamp is inside the
        signed payload, so it cannot be refreshed without the secret."""
        payload = event_body(fee_assignment_id=bill.id)
        stale = sign(payload, timestamp=int(time.time()) - 3600)
        assert deliver(api, payload, signature=stale).status_code == 400

    def test_a_rejected_signature_records_no_payment(self, api, bill, db_session):
        api.post(WEBHOOK_URL, content=event_body(fee_assignment_id=bill.id))
        assert (
            db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all()
            == []
        )

    def test_garbage_that_is_signed_is_still_refused(self, api):
        payload = b"this is not json"
        assert deliver(api, payload, signature=sign(payload)).status_code == 400


class TestRecordingThePayment:
    def test_the_payment_lands_against_the_right_bill(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, amount_total=25000))

        payments = db_session.scalars(
            select(Payment).where(Payment.fee_assignment_id == bill.id)
        ).all()
        assert len(payments) == 1
        assert payments[0].amount_paid == Decimal("250.00")
        assert payments[0].method is PaymentMethod.STRIPE

    def test_minor_units_come_back_to_decimal(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, amount_total=8250))
        payment = db_session.scalar(select(Payment).where(Payment.fee_assignment_id == bill.id))
        assert payment.amount_paid == Decimal("82.50")

    def test_the_stripe_identifiers_are_kept(self, api, bill, db_session):
        """Reconciliation with Stripe's own dashboard depends on these, and the
        event id is what makes a replay a no-op."""
        deliver(api, event_body(fee_assignment_id=bill.id, event_id="evt_abc"))
        payment = db_session.scalar(select(Payment).where(Payment.fee_assignment_id == bill.id))
        assert payment.stripe_event_id == "evt_abc"
        assert payment.stripe_payment_intent_id == "pi_test_1"

    def test_nobody_is_credited_with_recording_it(self, api, bill, db_session):
        """recorded_by is for a person who took cash. A webhook is not one."""
        deliver(api, event_body(fee_assignment_id=bill.id))
        payment = db_session.scalar(select(Payment).where(Payment.fee_assignment_id == bill.id))
        assert payment.recorded_by_id is None

    def test_the_balance_moves(self, api, bill, staff_headers):
        deliver(api, event_body(fee_assignment_id=bill.id, amount_total=10000))
        body = api.get(f"/fee-assignments/{bill.id}", headers=staff_headers).json()
        assert body["amount_paid"] == "100.00"
        assert body["outstanding"] == "150.00"

    def test_a_partial_online_payment_leaves_the_rest_owing(self, api, bill, staff_headers):
        """Installments, which is the point of the whole flow."""
        deliver(api, event_body(event_id="evt_1", fee_assignment_id=bill.id, amount_total=10000))
        deliver(api, event_body(event_id="evt_2", fee_assignment_id=bill.id, amount_total=15000))

        body = api.get(f"/fee-assignments/{bill.id}", headers=staff_headers).json()
        assert body["amount_paid"] == "250.00"
        assert body["settled"] is True

    def test_the_audit_row_names_the_event(self, api, bill, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, event_id="evt_audit"))
        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.action == "payment.stripe").order_by(AuditLog.id.desc())
        ).first()
        assert entry is not None
        assert "evt_audit" in entry.detail
        assert entry.target == f"fee_assignment:{bill.id}"

    def test_the_paying_parent_is_credited_on_the_audit_row(self, api, bill, parent, db_session):
        deliver(api, event_body(fee_assignment_id=bill.id, paid_by_user_id=parent.id))
        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.action == "payment.stripe").order_by(AuditLog.id.desc())
        ).first()
        assert entry.user_id == parent.id

    def test_a_stale_payer_id_does_not_lose_the_payment(self, api, bill, db_session):
        """The id is ours, but it round-trips through Stripe and can come back
        after the account is gone. An audit row that will not write because of
        a stale foreign key must not take the payment down with it."""
        response = deliver(api, event_body(fee_assignment_id=bill.id, paid_by_user_id=99999999))
        assert response.status_code == 200
        assert response.json()["recorded"] is True
        assert (
            db_session.scalar(select(Payment).where(Payment.fee_assignment_id == bill.id))
            is not None
        )


class TestIdempotency:
    def test_a_replayed_event_does_not_pay_twice(self, api, bill, db_session):
        """Stripe delivers at least once and retries after any timeout. The
        same event arriving again is routine, not an attack."""
        payload = event_body(fee_assignment_id=bill.id, event_id="evt_replay")
        first = deliver(api, payload)
        second = deliver(api, payload)

        assert first.json()["recorded"] is True
        assert second.status_code == 200
        assert second.json()["recorded"] is False
        assert "already recorded" in second.json()["reason"]

        payments = db_session.scalars(
            select(Payment).where(Payment.fee_assignment_id == bill.id)
        ).all()
        assert len(payments) == 1

    def test_a_replay_answers_200_so_stripe_stops_retrying(self, api, bill):
        payload = event_body(fee_assignment_id=bill.id, event_id="evt_replay_2")
        deliver(api, payload)
        assert deliver(api, payload).status_code == 200

    def test_two_different_events_both_land(self, api, bill, db_session):
        """The guard is the event id, not the amount or the bill."""
        deliver(api, event_body(event_id="evt_a", fee_assignment_id=bill.id, amount_total=10000))
        deliver(api, event_body(event_id="evt_b", fee_assignment_id=bill.id, amount_total=10000))

        payments = db_session.scalars(
            select(Payment).where(Payment.fee_assignment_id == bill.id)
        ).all()
        assert len(payments) == 2

    def test_the_database_enforces_it_too(
        self, api, bill, db_session, make_fee_assignment, make_student, make_fee_type
    ):
        """Belt and braces: the pre-check catches the ordinary replay, the
        unique index catches two deliveries racing."""
        from sqlalchemy.exc import IntegrityError

        deliver(api, event_body(fee_assignment_id=bill.id, event_id="evt_unique"))
        other = make_fee_assignment(make_student(), make_fee_type(default_amount="10.00"))
        db_session.add(
            Payment(
                fee_assignment_id=other.id,
                amount_paid=Decimal("1.00"),
                method=PaymentMethod.STRIPE,
                stripe_payment_intent_id="pi_x",
                stripe_event_id="evt_unique",
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


class TestEventsThatRecordNothing:
    def test_an_abandoned_checkout_leaves_no_row(self, api, bill, db_session):
        """No pending row is ever written, so there is nothing to clean up -
        by construction rather than by a reaper job that can get it wrong."""
        response = deliver(
            api, event_body(fee_assignment_id=bill.id, event_type="checkout.session.expired")
        )
        assert response.status_code == 200
        assert response.json()["recorded"] is False
        assert (
            db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all()
            == []
        )

    def test_a_failed_payment_leaves_no_row(self, api, bill, db_session):
        response = deliver(
            api,
            event_body(fee_assignment_id=bill.id, event_type="payment_intent.payment_failed"),
        )
        assert response.status_code == 200
        assert (
            db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all()
            == []
        )

    def test_a_completed_but_unpaid_session_records_nothing(self, api, bill, db_session):
        """Delayed payment methods complete the session and settle later.
        Recording on completion alone credits money that has not arrived."""
        response = deliver(api, event_body(fee_assignment_id=bill.id, payment_status="unpaid"))
        assert response.status_code == 200
        assert response.json()["recorded"] is False
        assert (
            db_session.scalars(select(Payment).where(Payment.fee_assignment_id == bill.id)).all()
            == []
        )

    def test_an_event_type_we_do_not_handle_is_a_final_200(self, api, bill):
        """Not a 500 and not a 400: Stripe would retry both for days, and
        retrying will not make us understand it."""
        response = deliver(
            api, event_body(fee_assignment_id=bill.id, event_type="customer.created")
        )
        assert response.status_code == 200
        assert response.json()["handled"] is False

    def test_a_session_with_no_metadata_is_not_our_payment(self, api, db_session):
        response = deliver(api, event_body(fee_assignment_id=None))
        assert response.status_code == 200
        assert response.json()["recorded"] is False

    def test_an_event_naming_a_deleted_bill_does_not_retry_forever(self, api):
        response = deliver(api, event_body(fee_assignment_id=99999999))
        assert response.status_code == 200
        assert response.json()["recorded"] is False


class TestMoneyThatCannotBeApplied:
    def test_an_overpaying_event_is_flagged_rather_than_recorded(
        self, api, bill, staff_headers, db_session
    ):
        """A bursar recorded cash while the parent was on the payment page.
        The card has already been charged, so a 409 would be a lie - there is
        no smaller amount to retry. It is held for a human to refund."""
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "250.00"},
            headers=staff_headers,
        )

        response = deliver(api, event_body(fee_assignment_id=bill.id, amount_total=25000))
        assert response.status_code == 200
        assert response.json()["recorded"] is False
        assert "reconciliation" in response.json()["reason"]

    def test_the_invariant_still_holds(self, api, bill, staff_headers):
        """The whole point of not recording it: payments never exceed the bill."""
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "250.00"},
            headers=staff_headers,
        )
        deliver(api, event_body(fee_assignment_id=bill.id, amount_total=25000))

        body = api.get(f"/fee-assignments/{bill.id}", headers=staff_headers).json()
        assert body["amount_paid"] == "250.00"
        assert body["outstanding"] == "0.00"

    def test_it_is_audited_loudly_enough_to_act_on(self, api, bill, staff_headers, db_session):
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "250.00"},
            headers=staff_headers,
        )
        deliver(
            api, event_body(fee_assignment_id=bill.id, event_id="evt_refund", amount_total=25000)
        )

        entry = db_session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "payment.stripe_needs_refund")
            .order_by(AuditLog.id.desc())
        ).first()
        assert entry is not None
        assert "evt_refund" in entry.detail
        assert "250.00" in entry.detail
        assert "cs_test_1" in entry.detail


class TestAFailureIsNotReportedAsSuccess:
    """Stripe stops retrying once it sees a 2xx. Anything that answers 200
    without recording the payment has to be a genuinely final answer, or the
    money is lost with no further deliveries coming.

    This is the guard on that: an integrity failure that is *not* a duplicate
    event must not be reported as one.
    """

    def test_an_unexpected_integrity_error_is_not_swallowed(
        self, api, bill, db_session, monkeypatch
    ):
        from app.api.routes import webhooks

        real_record = webhooks.audit.record

        def record_with_a_broken_foreign_key(db, **kwargs):
            # An audit row pointing at a user who does not exist. Stands in for
            # any constraint violation that is not the event-id unique index.
            return real_record(db, **{**kwargs, "user_id": 99999999})

        monkeypatch.setattr(webhooks.audit, "record", record_with_a_broken_foreign_key)

        with pytest.raises(IntegrityError):
            deliver(api, event_body(fee_assignment_id=bill.id, event_id="evt_boom"))

    def test_a_real_duplicate_is_still_reported_as_one(self, api, bill):
        """The other half: narrowing the handler must not break idempotency."""
        payload = event_body(fee_assignment_id=bill.id, event_id="evt_still_idempotent")
        assert deliver(api, payload).json()["recorded"] is True
        second = deliver(api, payload)
        assert second.status_code == 200
        assert second.json()["reason"] == "event already recorded"
