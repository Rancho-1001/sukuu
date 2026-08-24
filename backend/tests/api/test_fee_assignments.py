"""Fee assignments through HTTP: one student at a time, and a class at once."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AuditLog, FeeAssignment, StudentStatus, UserRole

pytestmark = pytest.mark.db


def a_period() -> str:
    return f"Term {uuid4().hex[:8]}"


class TestAssignToOneStudent:
    def test_an_admin_charges_a_student(self, api, admin_headers, make_student, make_fee_type):
        student = make_student()
        fee_type = make_fee_type(default_amount="250.00")

        response = api.post(
            "/fee-assignments",
            json={
                "student_id": student.id,
                "fee_type_id": fee_type.id,
                "period_label": a_period(),
                "amount": "250.00",
                "due_date": "2026-10-01",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["amount"] == "250.00"
        assert body["due_date"] == "2026-10-01"
        assert body["student"]["id"] == student.id
        assert body["fee_type"]["id"] == fee_type.id

    def test_omitting_the_amount_charges_the_fee_types_default(
        self, api, admin_headers, make_student, make_fee_type
    ):
        fee_type = make_fee_type(default_amount="180.00")
        body = api.post(
            "/fee-assignments",
            json={
                "student_id": make_student().id,
                "fee_type_id": fee_type.id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        ).json()
        assert body["amount"] == "180.00"

    def test_the_amount_can_differ_from_the_default(
        self, api, admin_headers, make_student, make_fee_type
    ):
        """A scholarship or a sibling discount, without inventing a fee type
        for every exception."""
        fee_type = make_fee_type(default_amount="250.00")
        body = api.post(
            "/fee-assignments",
            json={
                "student_id": make_student().id,
                "fee_type_id": fee_type.id,
                "period_label": a_period(),
                "amount": "125.00",
            },
            headers=admin_headers,
        ).json()
        assert body["amount"] == "125.00"

    def test_an_inactive_student_can_still_be_billed(
        self, api, admin_headers, make_student, make_fee_type
    ):
        """One at a time is a deliberate act - a withdrawn pupil's arrears are
        still owed. The bulk route deliberately behaves differently."""
        student = make_student(status=StudentStatus.INACTIVE)
        response = api.post(
            "/fee-assignments",
            json={
                "student_id": student.id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )
        assert response.status_code == 201

    def test_charging_the_same_fee_twice_in_a_period_is_a_conflict(
        self, api, admin_headers, make_student, make_fee_type
    ):
        payload = {
            "student_id": make_student().id,
            "fee_type_id": make_fee_type().id,
            "period_label": a_period(),
        }
        assert api.post("/fee-assignments", json=payload, headers=admin_headers).status_code == 201

        response = api.post("/fee-assignments", json=payload, headers=admin_headers)
        assert response.status_code == 409
        assert "already assigned" in response.json()["detail"]

    def test_the_same_fee_in_another_period_is_fine(
        self, api, admin_headers, make_student, make_fee_type
    ):
        base = {"student_id": make_student().id, "fee_type_id": make_fee_type().id}
        api.post(
            "/fee-assignments", json=base | {"period_label": a_period()}, headers=admin_headers
        )
        response = api.post(
            "/fee-assignments", json=base | {"period_label": a_period()}, headers=admin_headers
        )
        assert response.status_code == 201

    def test_an_unknown_student_is_reported_against_the_field(
        self, api, admin_headers, make_fee_type
    ):
        response = api.post(
            "/fee-assignments",
            json={
                "student_id": 99999999,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"].startswith("student_id:")

    def test_an_unknown_fee_type_is_reported_against_the_field(
        self, api, admin_headers, make_student
    ):
        response = api.post(
            "/fee-assignments",
            json={
                "student_id": make_student().id,
                "fee_type_id": 99999999,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"].startswith("fee_type_id:")

    @pytest.mark.parametrize("amount", ["0.00", "-50.00"])
    def test_a_non_positive_amount_is_refused(
        self, api, admin_headers, make_student, make_fee_type, amount
    ):
        response = api.post(
            "/fee-assignments",
            json={
                "student_id": make_student().id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
                "amount": amount,
            },
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_assign(self, api, headers_for, make_student, make_fee_type, role):
        """The spec is explicit: a bursar records payments and does not decide
        who is charged what."""
        response = api.post(
            "/fee-assignments",
            json={
                "student_id": make_student().id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=headers_for(role),
        )
        assert response.status_code == 403


class TestAssignToAClass:
    @pytest.fixture
    def a_class_of_three(self, make_class, make_student):
        school_class = make_class()
        students = [make_student(school_class=school_class) for _ in range(3)]
        return school_class, students

    def test_every_active_student_is_charged(
        self, api, admin_headers, a_class_of_three, make_fee_type
    ):
        school_class, students = a_class_of_three
        fee_type = make_fee_type(default_amount="250.00")

        response = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": fee_type.id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created"] == len(students)
        assert body["skipped_student_ids"] == []
        assert body["amount"] == "250.00"

    def test_the_rows_are_really_there(
        self, api, admin_headers, a_class_of_three, make_fee_type, db_session
    ):
        school_class, students = a_class_of_three
        fee_type = make_fee_type()
        period = a_period()

        api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": fee_type.id,
                "period_label": period,
            },
            headers=admin_headers,
        )

        assigned = set(
            db_session.scalars(
                select(FeeAssignment.student_id).where(FeeAssignment.period_label == period)
            )
        )
        assert assigned == {student.id for student in students}

    def test_inactive_students_are_left_out(
        self, api, admin_headers, make_class, make_student, make_fee_type
    ):
        """A class-wide sweep is routine. Billing a withdrawn pupil in the
        course of one is not something anyone meant to do."""
        school_class = make_class()
        make_student(school_class=school_class)
        make_student(school_class=school_class, status=StudentStatus.INACTIVE)

        body = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        ).json()
        assert body["created"] == 1

    def test_running_it_twice_charges_nobody_a_second_time(
        self, api, admin_headers, a_class_of_three, make_fee_type
    ):
        """The unique constraint would abort the whole statement, so one
        already-billed student would block the other twenty-four."""
        school_class, students = a_class_of_three
        payload = {
            "class_id": school_class.id,
            "fee_type_id": make_fee_type().id,
            "period_label": a_period(),
        }
        api.post("/fee-assignments/bulk", json=payload, headers=admin_headers)

        body = api.post("/fee-assignments/bulk", json=payload, headers=admin_headers).json()
        assert body["created"] == 0
        assert body["skipped_student_ids"] == sorted(student.id for student in students)

    def test_a_student_who_joins_mid_term_is_picked_up(
        self, api, admin_headers, a_class_of_three, make_student, make_fee_type
    ):
        """The reason skipping beats failing: the endpoint stays re-runnable."""
        school_class, students = a_class_of_three
        payload = {
            "class_id": school_class.id,
            "fee_type_id": make_fee_type().id,
            "period_label": a_period(),
        }
        api.post("/fee-assignments/bulk", json=payload, headers=admin_headers)

        latecomer = make_student(school_class=school_class)
        body = api.post("/fee-assignments/bulk", json=payload, headers=admin_headers).json()
        assert body["created"] == 1
        assert latecomer.id not in body["skipped_student_ids"]

    def test_an_empty_class_is_not_an_error(self, api, admin_headers, make_class, make_fee_type):
        body = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": make_class().id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        ).json()
        assert body["created"] == 0

    def test_the_amount_can_be_overridden_for_the_whole_class(
        self, api, admin_headers, a_class_of_three, make_fee_type
    ):
        school_class, _ = a_class_of_three
        body = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": make_fee_type(default_amount="250.00").id,
                "period_label": a_period(),
                "amount": "300.00",
            },
            headers=admin_headers,
        ).json()
        assert body["amount"] == "300.00"

    def test_the_due_date_is_carried_onto_every_row(
        self, api, admin_headers, a_class_of_three, make_fee_type, db_session
    ):
        school_class, _ = a_class_of_three
        period = a_period()
        api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": make_fee_type().id,
                "period_label": period,
                "due_date": "2026-10-01",
            },
            headers=admin_headers,
        )

        rows = db_session.scalars(
            select(FeeAssignment).where(FeeAssignment.period_label == period)
        ).all()
        assert {row.due_date for row in rows} == {date(2026, 10, 1)}

    def test_an_archived_class_cannot_be_billed(
        self, api, admin_headers, make_class, make_fee_type
    ):
        archived = make_class(archived_at=datetime.now(UTC))
        response = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": archived.id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert "archived" in response.json()["detail"]

    def test_an_unknown_class_is_reported_against_the_field(
        self, api, admin_headers, make_fee_type
    ):
        response = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": 99999999,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"].startswith("class_id:")

    def test_the_audit_row_says_how_many_were_billed(
        self, api, admin_headers, a_class_of_three, make_fee_type, db_session
    ):
        """The middleware records "POST /fee-assignments/bulk status=200" for
        free, which does not say that twenty-five families were just charged."""
        school_class, students = a_class_of_three
        api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        )

        entry = db_session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "fee_assignment.bulk")
            .order_by(AuditLog.id.desc())
        ).first()
        assert entry is not None
        assert entry.target == f"class:{school_class.id}"
        assert f"created={len(students)}" in entry.detail
        assert entry.user_id is not None
        # The row an investigation actually reads should not be the one
        # missing where the request came from.
        assert entry.ip_address is not None

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_bill_a_class(
        self, api, headers_for, a_class_of_three, make_fee_type, role
    ):
        school_class, _ = a_class_of_three
        response = api.post(
            "/fee-assignments/bulk",
            json={
                "class_id": school_class.id,
                "fee_type_id": make_fee_type().id,
                "period_label": a_period(),
            },
            headers=headers_for(role),
        )
        assert response.status_code == 403


class TestList:
    def test_filtering_by_student(
        self, api, admin_headers, make_student, make_fee_type, make_fee_assignment
    ):
        student = make_student()
        make_fee_assignment(student, make_fee_type(), period_label=a_period())
        make_fee_assignment(make_student(), make_fee_type(), period_label=a_period())

        body = api.get(f"/fee-assignments?student_id={student.id}", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["student"]["id"] == student.id

    def test_filtering_by_class(
        self, api, admin_headers, make_class, make_student, make_fee_type, make_fee_assignment
    ):
        school_class = make_class()
        make_fee_assignment(make_student(school_class=school_class), make_fee_type())
        make_fee_assignment(make_student(), make_fee_type())

        body = api.get(f"/fee-assignments?class_id={school_class.id}", headers=admin_headers).json()
        assert body["total"] == 1

    def test_filtering_by_period(
        self, api, admin_headers, make_student, make_fee_type, make_fee_assignment
    ):
        period = a_period()
        make_fee_assignment(make_student(), make_fee_type(), period_label=period)
        make_fee_assignment(make_student(), make_fee_type(), period_label=a_period())

        body = api.get(f"/fee-assignments?period_label={period}", headers=admin_headers).json()
        assert body["total"] == 1

    def test_filtering_by_fee_type(
        self, api, admin_headers, make_student, make_fee_type, make_fee_assignment
    ):
        fee_type = make_fee_type()
        make_fee_assignment(make_student(), fee_type)
        make_fee_assignment(make_student(), make_fee_type())

        body = api.get(f"/fee-assignments?fee_type_id={fee_type.id}", headers=admin_headers).json()
        assert body["total"] == 1

    def test_the_soonest_due_comes_first_and_undated_comes_last(
        self, api, admin_headers, make_class, make_student, make_fee_type, make_fee_assignment
    ):
        """The bursar's order, not the database's."""
        school_class = make_class()
        fee_type = make_fee_type()
        undated = make_fee_assignment(make_student(school_class=school_class), fee_type)
        later = make_fee_assignment(
            make_student(school_class=school_class), fee_type, due_date=date(2026, 12, 1)
        )
        sooner = make_fee_assignment(
            make_student(school_class=school_class), fee_type, due_date=date(2026, 9, 1)
        )

        body = api.get(f"/fee-assignments?class_id={school_class.id}", headers=admin_headers).json()
        assert [item["id"] for item in body["items"]] == [sooner.id, later.id, undated.id]

    def test_the_amount_is_a_string(
        self, api, admin_headers, make_student, make_fee_type, make_fee_assignment
    ):
        student = make_student()
        make_fee_assignment(student, make_fee_type(), amount="99.50")
        body = api.get(f"/fee-assignments?student_id={student.id}", headers=admin_headers).json()
        assert body["items"][0]["amount"] == "99.50"

    def test_the_query_count_does_not_grow_with_the_page(
        self,
        api,
        admin_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        query_counter,
    ):
        small_class, large_class = make_class(), make_class()
        fee_type = make_fee_type()
        make_fee_assignment(make_student(school_class=small_class), fee_type)
        for _ in range(6):
            make_fee_assignment(make_student(school_class=large_class), fee_type)

        api.get("/fee-assignments?limit=1", headers=admin_headers)

        with query_counter() as small:
            api.get(f"/fee-assignments?class_id={small_class.id}", headers=admin_headers)
        with query_counter() as large:
            api.get(f"/fee-assignments?class_id={large_class.id}", headers=admin_headers)

        assert len(small) == len(large)

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_may_read_the_list(self, api, headers_for, role):
        assert api.get("/fee-assignments", headers=headers_for(role)).status_code == 200

    def test_parents_may_not(self, api, parent_headers):
        """Parents reach their own children's fees through the balance
        endpoints, not the bursar's list."""
        assert api.get("/fee-assignments", headers=parent_headers).status_code == 403


class TestRead:
    def test_reading_one(
        self, api, admin_headers, make_student, make_fee_type, make_fee_assignment
    ):
        assignment = make_fee_assignment(make_student(), make_fee_type(default_amount="250.00"))
        response = api.get(f"/fee-assignments/{assignment.id}", headers=admin_headers)
        assert response.status_code == 200
        assert Decimal(response.json()["amount"]) == assignment.amount

    def test_an_unknown_assignment_is_404(self, api, admin_headers):
        assert api.get("/fee-assignments/99999999", headers=admin_headers).status_code == 404

    def test_bulk_is_not_read_as_an_id(self, api, admin_headers):
        """Route order: with /{fee_assignment_id} declared first, "bulk" would
        be parsed as an id. Both cases answer 422, so the assertion is on which
        fields were complained about - the bulk body's, not a path param's."""
        response = api.post("/fee-assignments/bulk", json={}, headers=admin_headers)
        assert response.status_code == 422
        fields = {error["field"] for error in response.json()["errors"]}
        assert fields == {"class_id", "fee_type_id", "period_label"}


class TestTheBalanceOnAnAssignment:
    """The per-assignment balance, carried on the record it belongs to."""

    @pytest.fixture
    def assignment(self, make_student, make_fee_type, make_fee_assignment):
        return make_fee_assignment(
            make_student(), make_fee_type(default_amount="100.00"), amount="100.00"
        )

    def test_an_untouched_fee_owes_all_of_it(self, api, admin_headers, assignment):
        body = api.get(f"/fee-assignments/{assignment.id}", headers=admin_headers).json()
        assert body["amount"] == "100.00"
        assert body["amount_paid"] == "0.00"
        assert body["outstanding"] == "100.00"
        assert body["settled"] is False

    def test_a_partial_payment_moves_the_balance(
        self, api, admin_headers, assignment, make_payment
    ):
        make_payment(assignment, "40.00")
        body = api.get(f"/fee-assignments/{assignment.id}", headers=admin_headers).json()
        assert body["amount_paid"] == "40.00"
        assert body["outstanding"] == "60.00"
        assert body["settled"] is False

    def test_installments_accumulate_without_inflating_the_amount(
        self, api, admin_headers, assignment, make_payment
    ):
        """Three installments settling one bill exactly.

        This route cannot fan out - it joins payments already collapsed to one
        row per assignment - so this checks the accumulation, not the join.
        The fan-out itself is tested where the risk actually is, against the
        student and class totals in test_balances_api.py."""
        for part in ("30.00", "30.00", "40.00"):
            make_payment(assignment, part)

        body = api.get(f"/fee-assignments/{assignment.id}", headers=admin_headers).json()
        assert body["amount"] == "100.00"
        assert body["amount_paid"] == "100.00"
        assert body["outstanding"] == "0.00"
        assert body["settled"] is True

    def test_the_list_carries_balances_too(self, api, admin_headers, assignment, make_payment):
        make_payment(assignment, "25.00")
        body = api.get(
            f"/fee-assignments?student_id={assignment.student_id}", headers=admin_headers
        ).json()
        assert body["items"][0]["outstanding"] == "75.00"

    def test_filtering_to_what_is_still_owed(
        self,
        api,
        admin_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        make_payment,
    ):
        """The bursar's actual question."""
        school_class = make_class()
        fee_type = make_fee_type(default_amount="100.00")
        settled = make_fee_assignment(
            make_student(school_class=school_class), fee_type, amount="100.00"
        )
        make_payment(settled, "100.00")
        still_owing = make_fee_assignment(
            make_student(school_class=school_class), fee_type, amount="100.00"
        )
        make_payment(still_owing, "99.99")
        untouched = make_fee_assignment(
            make_student(school_class=school_class), fee_type, amount="100.00"
        )

        body = api.get(
            f"/fee-assignments?class_id={school_class.id}&outstanding_only=true",
            headers=admin_headers,
        ).json()
        assert {item["id"] for item in body["items"]} == {still_owing.id, untouched.id}
        assert body["total"] == 2

    def test_a_new_assignment_starts_unpaid(self, api, admin_headers, make_student, make_fee_type):
        body = api.post(
            "/fee-assignments",
            json={
                "student_id": make_student().id,
                "fee_type_id": make_fee_type(default_amount="75.00").id,
                "period_label": a_period(),
            },
            headers=admin_headers,
        ).json()
        assert body["amount_paid"] == "0.00"
        assert body["outstanding"] == "75.00"

    def test_the_query_count_does_not_grow_when_payments_do(
        self,
        api,
        admin_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        make_payment,
        query_counter,
    ):
        """Balances must arrive in the same query as the rows. Asking each
        assignment what it has collected is the N+1 that hurts most: this is
        the bursar's main list."""
        quiet, busy = make_class(), make_class()
        fee_type = make_fee_type(default_amount="100.00")
        make_payment(
            make_fee_assignment(make_student(school_class=quiet), fee_type, amount="100.00"),
            "10.00",
        )
        for _ in range(5):
            assignment = make_fee_assignment(
                make_student(school_class=busy), fee_type, amount="100.00"
            )
            for part in ("10.00", "10.00", "10.00"):
                make_payment(assignment, part)

        api.get("/fee-assignments?limit=1", headers=admin_headers)

        with query_counter() as small:
            api.get(f"/fee-assignments?class_id={quiet.id}", headers=admin_headers)
        with query_counter() as large:
            api.get(f"/fee-assignments?class_id={busy.id}", headers=admin_headers)

        assert len(small) == len(large)
