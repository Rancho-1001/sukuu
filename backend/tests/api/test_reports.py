"""The admin dashboard's numbers.

Everything here is derivable from endpoints that already exist, so the tests
that matter are the ones about the joins: three levels deep - class to student
to assignment to payments - is where a fan-out inflates a figure that still
looks plausible.
"""

from __future__ import annotations

import pytest

from app.models import UserRole

pytestmark = pytest.mark.db

URL = "/reports/summary"


def row_for(body: dict, class_id: int) -> dict | None:
    return next((row for row in body["classes"] if row["school_class"]["id"] == class_id), None)


class TestTheTotals:
    def test_a_class_with_nothing_billed_reads_zero(self, api, admin_headers, make_class):
        school_class = make_class()
        row = row_for(api.get(URL, headers=admin_headers).json(), school_class.id)
        assert row is not None
        assert row["billed"] == "0.00"
        assert row["outstanding"] == "0.00"

    def test_a_class_row_adds_up(
        self,
        api,
        admin_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        make_payment,
    ):
        school_class = make_class()
        fee_type = make_fee_type(default_amount="100.00")
        first = make_fee_assignment(
            make_student(school_class=school_class), fee_type, amount="100.00"
        )
        make_fee_assignment(make_student(school_class=school_class), fee_type, amount="100.00")
        make_payment(first, "40.00")

        row = row_for(api.get(URL, headers=admin_headers).json(), school_class.id)
        assert row["billed"] == "200.00"
        assert row["paid"] == "40.00"
        assert row["outstanding"] == "160.00"

    def test_installments_do_not_inflate_a_class_row(
        self,
        api,
        admin_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        make_payment,
    ):
        """Three joins deep. One 100.00 bill settled in four payments would
        read as 400.00 billed, and the class beside it would still be right."""
        school_class = make_class()
        assignment = make_fee_assignment(
            make_student(school_class=school_class),
            make_fee_type(default_amount="100.00"),
            amount="100.00",
        )
        for part in ("25.00", "25.00", "25.00", "25.00"):
            make_payment(assignment, part)

        row = row_for(api.get(URL, headers=admin_headers).json(), school_class.id)
        assert row["billed"] == "100.00"
        assert row["paid"] == "100.00"
        assert row["outstanding"] == "0.00"

    def test_a_student_with_no_class_counts_toward_the_school_not_a_class(
        self, api, admin_headers, make_student, make_fee_type, make_fee_assignment
    ):
        """The gap between the totals and the class rows is the admin's cue
        that somebody still needs placing."""
        before = api.get(URL, headers=admin_headers).json()
        make_fee_assignment(make_student(), make_fee_type(default_amount="100.00"), amount="100.00")
        after = api.get(URL, headers=admin_headers).json()

        from decimal import Decimal

        assert Decimal(after["billed"]) - Decimal(before["billed"]) == Decimal("100.00")
        class_billed_before = sum(Decimal(row["billed"]) for row in before["classes"])
        class_billed_after = sum(Decimal(row["billed"]) for row in after["classes"])
        assert class_billed_after == class_billed_before

    def test_the_query_count_does_not_grow_with_the_number_of_classes(
        self,
        api,
        admin_headers,
        make_class,
        make_student,
        make_fee_type,
        make_fee_assignment,
        query_counter,
    ):
        """The whole reason this endpoint exists rather than the client looping
        over `/classes/{id}/balance`."""
        api.get(URL, headers=admin_headers)
        with query_counter() as before:
            api.get(URL, headers=admin_headers)

        fee_type = make_fee_type(default_amount="100.00")
        for _ in range(5):
            school_class = make_class()
            make_fee_assignment(make_student(school_class=school_class), fee_type, amount="100.00")

        with query_counter() as after:
            api.get(URL, headers=admin_headers)

        assert len(before) == len(after)


class TestWhoMayRead:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_and_admins_may(self, api, headers_for, role):
        assert api.get(URL, headers=headers_for(role)).status_code == 200

    def test_a_parent_may_not(self, api, parent_headers):
        """It names every class and what each is owed."""
        assert api.get(URL, headers=parent_headers).status_code == 403

    def test_anonymous_is_rejected(self, api):
        assert api.get(URL).status_code == 401
