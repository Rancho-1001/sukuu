"""Cash payments through HTTP.

The money rules themselves are proved in ``tests/unit/test_balances.py`` and
the lock in ``tests/integration/test_payment_concurrency.py``. What is checked
here is that the route is wired to them, that it refuses the right people, and
that it cannot be talked into recording something that did not happen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, PaymentMethod, UserRole

pytestmark = pytest.mark.db


@pytest.fixture
def bill(make_student, make_fee_type, make_fee_assignment):
    """A student with one 100.00 fee and nothing paid against it."""
    return make_fee_assignment(
        make_student(), make_fee_type(default_amount="100.00"), amount="100.00"
    )


class TestRecordingCash:
    def test_a_bursar_records_a_payment(self, api, staff_headers, bill):
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "40.00"},
            headers=staff_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["payment"]["amount_paid"] == "40.00"
        assert body["payment"]["method"] == "cash"

    def test_the_receipt_says_what_is_left(self, api, staff_headers, bill):
        """The first thing anyone asks after handing over money."""
        body = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "40.00"},
            headers=staff_headers,
        ).json()
        assert body["fee_assignment"]["amount_paid"] == "40.00"
        assert body["fee_assignment"]["outstanding"] == "60.00"
        assert body["fee_assignment"]["settled"] is False

    def test_paying_the_balance_settles_the_bill(self, api, staff_headers, bill):
        body = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "100.00"},
            headers=staff_headers,
        ).json()
        assert body["fee_assignment"]["outstanding"] == "0.00"
        assert body["fee_assignment"]["settled"] is True

    def test_who_took_the_money_is_recorded(self, api, token_for, bill):
        """Accountability data. The roadmap item is "every payment records who
        logged it", and the client does not get to say who that was."""
        bursar, headers = token_for(UserRole.STAFF)
        body = api.post(
            "/payments", json={"fee_assignment_id": bill.id, "amount": "10.00"}, headers=headers
        ).json()
        assert body["payment"]["recorded_by"]["id"] == bursar.id
        assert body["payment"]["recorded_by"]["name"] == bursar.name

    def test_installments_add_up(self, api, staff_headers, bill):
        for part in ("30.00", "30.00", "40.00"):
            response = api.post(
                "/payments",
                json={"fee_assignment_id": bill.id, "amount": part},
                headers=staff_headers,
            )
            assert response.status_code == 201, response.text

        body = api.get(f"/fee-assignments/{bill.id}", headers=staff_headers).json()
        assert body["amount_paid"] == "100.00"
        assert body["settled"] is True

    def test_an_admin_may_also_record_cash(self, api, admin_headers, bill):
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "10.00"},
            headers=admin_headers,
        )
        assert response.status_code == 201

    def test_a_parent_may_not(self, api, parent_headers, bill):
        """Parents pay through Stripe in Phase 5. Being able to file your own
        cash payment is being able to mark your own fees paid."""
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "10.00"},
            headers=parent_headers,
        )
        assert response.status_code == 403

    def test_anonymous_is_rejected(self, api, bill):
        response = api.post("/payments", json={"fee_assignment_id": bill.id, "amount": "10.00"})
        assert response.status_code == 401


class TestTheLedgerCannotBeMadeToLie:
    def test_the_client_cannot_choose_the_method(self, api, staff_headers, bill):
        """The one lie this ledger must not be able to tell about itself.
        A staff member filing a payment as "stripe" with no Stripe transaction
        behind it would reconcile to nothing and look exactly like a real one."""
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "10.00", "method": "stripe"},
            headers=staff_headers,
        )
        assert response.status_code == 422

    def test_the_client_cannot_choose_who_recorded_it(self, api, staff_headers, bill, make_user):
        someone_else = make_user(UserRole.ADMIN)
        response = api.post(
            "/payments",
            json={
                "fee_assignment_id": bill.id,
                "amount": "10.00",
                "recorded_by_id": someone_else.id,
            },
            headers=staff_headers,
        )
        assert response.status_code == 422

    def test_overpaying_is_refused_and_says_what_is_left(self, api, staff_headers, bill):
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "70.00"},
            headers=staff_headers,
        )
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "40.00"},
            headers=staff_headers,
        )
        assert response.status_code == 409
        assert "30.00" in response.json()["detail"]

    def test_a_settled_bill_takes_nothing_more(self, api, staff_headers, bill):
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "100.00"},
            headers=staff_headers,
        )
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "0.01"},
            headers=staff_headers,
        )
        assert response.status_code == 409
        assert "paid in full" in response.json()["detail"]

    def test_a_refused_payment_leaves_no_row(self, api, staff_headers, bill, db_session):
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "100.00"},
            headers=staff_headers,
        )
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "5.00"},
            headers=staff_headers,
        )

        body = api.get(f"/fee-assignments/{bill.id}", headers=staff_headers).json()
        assert body["amount_paid"] == "100.00"

    @pytest.mark.parametrize("amount", ["0.00", "-10.00"])
    def test_a_non_positive_amount_is_refused(self, api, staff_headers, bill, amount):
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": amount},
            headers=staff_headers,
        )
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "amount"

    def test_a_third_decimal_place_is_refused(self, api, staff_headers, bill):
        response = api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "10.005"},
            headers=staff_headers,
        )
        assert response.status_code == 422

    def test_an_unknown_bill_is_reported_against_the_field(self, api, staff_headers):
        response = api.post(
            "/payments",
            json={"fee_assignment_id": 99999999, "amount": "10.00"},
            headers=staff_headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"].startswith("fee_assignment_id:")

    def test_the_audit_row_names_the_amount(self, api, staff_headers, bill, db_session):
        """ "POST /payments status=201" does not say that money changed hands."""
        api.post(
            "/payments",
            json={"fee_assignment_id": bill.id, "amount": "40.00"},
            headers=staff_headers,
        )
        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.action == "payment.cash").order_by(AuditLog.id.desc())
        ).first()
        assert entry is not None
        assert entry.target == f"fee_assignment:{bill.id}"
        assert "amount=40.00" in entry.detail
        assert entry.user_id is not None
        assert entry.ip_address is not None


class TestListingPayments:
    def test_filtering_by_assignment(self, api, staff_headers, bill, make_payment):
        make_payment(bill, "10.00")
        body = api.get(f"/payments?fee_assignment_id={bill.id}", headers=staff_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["amount_paid"] == "10.00"

    def test_filtering_by_student(self, api, staff_headers, bill, make_payment):
        make_payment(bill, "10.00")
        body = api.get(f"/payments?student_id={bill.student_id}", headers=staff_headers).json()
        assert body["total"] == 1

    def test_filtering_by_class(
        self,
        api,
        staff_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        make_payment,
    ):
        school_class = make_class()
        fee_type = make_fee_type(default_amount="100.00")
        mine = make_fee_assignment(make_student(school_class=school_class), fee_type)
        make_payment(mine, "10.00")
        make_payment(make_fee_assignment(make_student(), fee_type), "10.00")

        body = api.get(f"/payments?class_id={school_class.id}", headers=staff_headers).json()
        assert body["total"] == 1

    def test_filtering_by_who_recorded_it(self, api, staff_headers, bill, make_user, make_payment):
        bursar = make_user(UserRole.STAFF)
        make_payment(bill, "10.00", recorded_by=bursar)
        make_payment(bill, "10.00")

        body = api.get(f"/payments?recorded_by_id={bursar.id}", headers=staff_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["recorded_by"]["id"] == bursar.id

    def test_filtering_by_method(self, api, staff_headers, bill, make_payment):
        make_payment(bill, "10.00")
        body = api.get(
            f"/payments?fee_assignment_id={bill.id}&method=stripe", headers=staff_headers
        ).json()
        assert body["total"] == 0

    def test_a_parent_may_not_read_the_school_wide_list(self, api, parent_headers):
        assert api.get("/payments", headers=parent_headers).status_code == 403


class TestAParentsPaymentHistory:
    def test_a_parent_sees_their_own_childs_payments(
        self, api, token_for, make_student, make_fee_type, make_fee_assignment, make_payment
    ):
        parent, headers = token_for(UserRole.PARENT)
        child = make_student(parent=parent)
        assignment = make_fee_assignment(child, make_fee_type(default_amount="100.00"))
        make_payment(assignment, "25.00")

        body = api.get(f"/students/{child.id}/payments", headers=headers).json()
        assert body["total"] == 1
        assert body["items"][0]["amount_paid"] == "25.00"

    def test_another_familys_history_is_404(
        self,
        api,
        token_for,
        make_user,
        make_student,
        make_fee_type,
        make_fee_assignment,
        make_payment,
    ):
        _, headers = token_for(UserRole.PARENT)
        other_child = make_student(parent=make_user(UserRole.PARENT))
        make_payment(
            make_fee_assignment(other_child, make_fee_type(default_amount="100.00")), "25.00"
        )

        assert api.get(f"/students/{other_child.id}/payments", headers=headers).status_code == 404

    def test_staff_may_read_any_childs_history(self, api, staff_headers, bill, make_payment):
        make_payment(bill, "10.00")
        response = api.get(f"/students/{bill.student_id}/payments", headers=staff_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_the_payment_amount_is_a_string(self, api, staff_headers, bill, make_payment):
        make_payment(bill, "10.50")
        body = api.get(f"/students/{bill.student_id}/payments", headers=staff_headers).json()
        assert body["items"][0]["amount_paid"] == "10.50"
        assert Decimal(body["items"][0]["amount_paid"]) == Decimal("10.50")


def test_a_cash_payment_is_recorded_as_cash(api, staff_headers, bill, db_session):
    """Belt and braces on the method: not just refused from the body, but
    actually stored as cash."""
    api.post(
        "/payments", json={"fee_assignment_id": bill.id, "amount": "10.00"}, headers=staff_headers
    )
    db_session.refresh(bill)
    assert [p.method for p in bill.payments] == [PaymentMethod.CASH]
    assert all(p.stripe_payment_intent_id is None for p in bill.payments)
