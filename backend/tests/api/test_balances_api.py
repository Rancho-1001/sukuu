"""The balance roll-ups: one student, and one class.

The fan-out tests here are the point of the file. Totalling what a class has
been billed means joining students to assignments to payments, and the naive
version of that join multiplies each bill by the number of payments made
against it. It agrees perfectly with a hand-check for every student who paid
in one go, and is wrong only for the ones who paid in installments - which is
the feature this product is built around.
"""

from __future__ import annotations

import pytest

from app.models import StudentStatus, UserRole

pytestmark = pytest.mark.db


@pytest.fixture
def family(make_class, make_user, make_student):
    school_class = make_class(name="Grade 5B")
    parent = make_user(UserRole.PARENT)
    return school_class, parent, make_student(school_class=school_class, parent=parent)


class TestOneStudentsBalance:
    def test_a_student_with_no_fees_owes_nothing(self, api, admin_headers, family):
        _, _, student = family
        body = api.get(f"/students/{student.id}/balance", headers=admin_headers).json()
        assert body["billed"] == "0.00"
        assert body["paid"] == "0.00"
        assert body["outstanding"] == "0.00"
        assert body["lines"] == []

    def test_the_fees_are_itemised(
        self, api, admin_headers, family, make_fee_type, make_fee_assignment, make_payment
    ):
        _, _, student = family
        tuition = make_fee_assignment(
            student, make_fee_type(default_amount="250.00"), amount="250.00"
        )
        make_fee_assignment(student, make_fee_type(default_amount="80.00"), amount="80.00")
        make_payment(tuition, "100.00")

        body = api.get(f"/students/{student.id}/balance", headers=admin_headers).json()
        assert body["billed"] == "330.00"
        assert body["paid"] == "100.00"
        assert body["outstanding"] == "230.00"
        assert len(body["lines"]) == 2

        line = next(item for item in body["lines"] if item["id"] == tuition.id)
        assert line["amount"] == "250.00"
        assert line["amount_paid"] == "100.00"
        assert line["outstanding"] == "150.00"

    def test_installments_do_not_inflate_what_was_billed(
        self, api, admin_headers, family, make_fee_type, make_fee_assignment, make_payment
    ):
        """One 250.00 bill paid in three parts is still one 250.00 bill.
        Joined naively it reads as 750.00 billed and 250.00 paid."""
        _, _, student = family
        assignment = make_fee_assignment(
            student, make_fee_type(default_amount="250.00"), amount="250.00"
        )
        for part in ("100.00", "100.00", "50.00"):
            make_payment(assignment, part)

        body = api.get(f"/students/{student.id}/balance", headers=admin_headers).json()
        assert body["billed"] == "250.00"
        assert body["paid"] == "250.00"
        assert body["outstanding"] == "0.00"

    def test_the_totals_always_match_the_lines(
        self, api, admin_headers, family, make_fee_type, make_fee_assignment, make_payment
    ):
        """Derived from the lines rather than fetched separately, so the two
        cannot disagree on screen."""
        from decimal import Decimal

        _, _, student = family
        for amount, paid in (("250.00", "100.00"), ("80.00", "80.00"), ("40.00", None)):
            assignment = make_fee_assignment(
                student, make_fee_type(default_amount=amount), amount=amount
            )
            if paid:
                make_payment(assignment, paid)

        body = api.get(f"/students/{student.id}/balance", headers=admin_headers).json()
        assert Decimal(body["billed"]) == sum(Decimal(line["amount"]) for line in body["lines"])
        assert Decimal(body["paid"]) == sum(Decimal(line["amount_paid"]) for line in body["lines"])

    def test_the_lines_are_ordered_by_due_date(
        self, api, admin_headers, family, make_fee_type, make_fee_assignment
    ):
        from datetime import date

        _, _, student = family
        undated = make_fee_assignment(student, make_fee_type())
        later = make_fee_assignment(student, make_fee_type(), due_date=date(2026, 12, 1))
        sooner = make_fee_assignment(student, make_fee_type(), due_date=date(2026, 9, 1))

        body = api.get(f"/students/{student.id}/balance", headers=admin_headers).json()
        assert [line["id"] for line in body["lines"]] == [sooner.id, later.id, undated.id]

    def test_a_parent_reads_their_own_childs_balance(
        self, api, token_for, make_student, make_fee_type, make_fee_assignment
    ):
        """The parent-scoped fee list. Same route, guarded per row."""
        parent, headers = token_for(UserRole.PARENT)
        child = make_student(parent=parent)
        make_fee_assignment(child, make_fee_type(default_amount="250.00"), amount="250.00")

        body = api.get(f"/students/{child.id}/balance", headers=headers).json()
        assert body["outstanding"] == "250.00"
        assert len(body["lines"]) == 1

    def test_another_familys_balance_is_404(
        self, api, token_for, make_user, make_student, make_fee_type, make_fee_assignment
    ):
        _, headers = token_for(UserRole.PARENT)
        other_child = make_student(parent=make_user(UserRole.PARENT))
        make_fee_assignment(other_child, make_fee_type(default_amount="250.00"))

        assert api.get(f"/students/{other_child.id}/balance", headers=headers).status_code == 404


class TestAClassesBalance:
    @pytest.fixture
    def billed_class(self, make_class, make_student, make_fee_type, make_fee_assignment):
        """Three students, each billed 100.00."""
        school_class = make_class()
        fee_type = make_fee_type(default_amount="100.00")
        assignments = [
            make_fee_assignment(
                make_student(school_class=school_class, last_name=f"Family{index}"),
                fee_type,
                amount="100.00",
            )
            for index in range(3)
        ]
        return school_class, assignments

    def test_the_class_totals(self, api, admin_headers, billed_class, make_payment):
        school_class, assignments = billed_class
        make_payment(assignments[0], "100.00")
        make_payment(assignments[1], "25.00")

        body = api.get(f"/classes/{school_class.id}/balance", headers=admin_headers).json()
        assert body["billed"] == "300.00"
        assert body["paid"] == "125.00"
        assert body["outstanding"] == "175.00"
        assert body["school_class"]["id"] == school_class.id

    def test_installments_do_not_inflate_the_class_total(
        self, api, admin_headers, billed_class, make_payment
    ):
        """The fan-out, where it actually bites. One student settling 100.00 in
        four payments makes their bill count four times, so the class reads as
        billed 600.00 instead of 300.00 - while the other two students' figures
        stay perfectly correct, which is what makes it hard to spot."""
        school_class, assignments = billed_class
        for part in ("25.00", "25.00", "25.00", "25.00"):
            make_payment(assignments[0], part)

        body = api.get(f"/classes/{school_class.id}/balance", headers=admin_headers).json()
        assert body["billed"] == "300.00"
        assert body["paid"] == "100.00"
        assert body["outstanding"] == "200.00"

    def test_the_per_student_breakdown(self, api, admin_headers, billed_class, make_payment):
        school_class, assignments = billed_class
        make_payment(assignments[0], "40.00")

        body = api.get(f"/classes/{school_class.id}/balance", headers=admin_headers).json()
        rows = {row["student"]["id"]: row for row in body["students"]["items"]}
        assert rows[assignments[0].student_id]["paid"] == "40.00"
        assert rows[assignments[0].student_id]["outstanding"] == "60.00"
        assert rows[assignments[1].student_id]["outstanding"] == "100.00"

    def test_a_students_own_row_is_not_inflated_by_installments(
        self, api, admin_headers, billed_class, make_payment
    ):
        """The class total and the rows that make it up are two different
        queries, and each can fan out on its own. This is the row.

        Without the collapse, the student who paid in four installments reads
        as billed 400.00 and fully paid, owing nothing - while actually still
        owing nothing, which is the one case where the bug hides. Add a fifth
        unpaid fee and the same row starts under-reporting a real debt.
        """
        school_class, assignments = billed_class
        payer = assignments[0]
        for part in ("25.00", "25.00", "25.00", "25.00"):
            make_payment(payer, part)

        body = api.get(f"/classes/{school_class.id}/balance", headers=admin_headers).json()
        row = next(
            item for item in body["students"]["items"] if item["student"]["id"] == payer.student_id
        )
        assert row["billed"] == "100.00"
        assert row["paid"] == "100.00"
        assert row["outstanding"] == "0.00"

    def test_a_student_with_no_fees_still_appears(
        self, api, admin_headers, billed_class, make_student
    ):
        """A zero row is information: it usually means somebody was missed."""
        school_class, _ = billed_class
        unbilled = make_student(school_class=school_class, last_name="Zzz")

        body = api.get(f"/classes/{school_class.id}/balance", headers=admin_headers).json()
        rows = {row["student"]["id"]: row for row in body["students"]["items"]}
        assert rows[unbilled.id]["billed"] == "0.00"

    def test_the_totals_cover_the_class_not_the_page(
        self, api, admin_headers, billed_class, make_payment
    ):
        """Totalling the page gives a number that shrinks when someone clicks
        "next", and a dashboard states it with complete confidence."""
        school_class, assignments = billed_class
        make_payment(assignments[0], "100.00")

        body = api.get(f"/classes/{school_class.id}/balance?limit=1", headers=admin_headers).json()
        assert len(body["students"]["items"]) == 1
        assert body["students"]["total"] == 3
        assert body["billed"] == "300.00"
        assert body["paid"] == "100.00"

    def test_inactive_students_still_count_toward_what_is_owed(
        self, api, admin_headers, make_class, make_student, make_fee_type, make_fee_assignment
    ):
        """A withdrawn pupil's arrears do not stop being owed."""
        school_class = make_class()
        withdrawn = make_student(school_class=school_class, status=StudentStatus.INACTIVE)
        make_fee_assignment(withdrawn, make_fee_type(default_amount="100.00"), amount="100.00")

        body = api.get(f"/classes/{school_class.id}/balance", headers=admin_headers).json()
        assert body["outstanding"] == "100.00"

    def test_an_unknown_class_is_404(self, api, admin_headers):
        assert api.get("/classes/99999999/balance", headers=admin_headers).status_code == 404

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_may_read_it(self, api, headers_for, billed_class, role):
        school_class, _ = billed_class
        response = api.get(f"/classes/{school_class.id}/balance", headers=headers_for(role))
        assert response.status_code == 200

    def test_a_parent_may_not(self, api, parent_headers, billed_class):
        """A class balance names every other family's child and what they owe."""
        school_class, _ = billed_class
        response = api.get(f"/classes/{school_class.id}/balance", headers=parent_headers)
        assert response.status_code == 403

    def test_the_query_count_does_not_grow_with_the_class(
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
        fee_type = make_fee_type(default_amount="100.00")
        small, large = make_class(), make_class()
        make_payment(
            make_fee_assignment(make_student(school_class=small), fee_type, amount="100.00"),
            "10.00",
        )
        for _ in range(6):
            assignment = make_fee_assignment(
                make_student(school_class=large), fee_type, amount="100.00"
            )
            make_payment(assignment, "10.00")
            make_payment(assignment, "10.00")

        api.get(f"/classes/{small.id}/balance", headers=admin_headers)

        with query_counter() as few:
            api.get(f"/classes/{small.id}/balance", headers=admin_headers)
        with query_counter() as many:
            api.get(f"/classes/{large.id}/balance", headers=admin_headers)

        assert len(few) == len(many)
