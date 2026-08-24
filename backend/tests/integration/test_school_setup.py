"""Phase 3's "done when", as a test: an admin sets up a whole school through
the API alone.

The unit and route tests each check one endpoint in isolation. This walks the
sequence a real administrator walks in August - classes, fee types, students,
then billing the classes - using nothing but HTTP, and reading back what the
next step needs from the previous response rather than from fixtures. It is
the test that catches the endpoints being individually correct and jointly
unusable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import UserRole

pytestmark = pytest.mark.db

CLASSES = ["Grade 4", "Grade 5", "Grade 6"]
STUDENTS_PER_CLASS = 3


@pytest.fixture
def year() -> str:
    return f"YR{uuid4().hex[:8]}"


def test_an_admin_sets_up_a_school(api, admin_headers, make_user, year):
    def post(path: str, body: dict) -> dict:
        response = api.post(path, json=body, headers=admin_headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    # 1. The classes for the coming year.
    classes = [post("/classes", {"name": name, "academic_year": year}) for name in CLASSES]
    assert all(school_class["active_student_count"] == 0 for school_class in classes)

    # 2. What the school charges for.
    tuition = post(
        "/fee-types",
        {
            "name": f"Tuition {uuid4().hex[:6]}",
            "description": "Termly tuition",
            "default_amount": "250.00",
            "billing_period": "term",
        },
    )
    uniform = post(
        "/fee-types",
        {
            "name": f"Uniform {uuid4().hex[:6]}",
            "default_amount": "80.00",
            "billing_period": "one_time",
        },
    )

    # 3. The roll, each child attached to a class and a paying parent.
    parents = [make_user(UserRole.PARENT) for _ in range(len(CLASSES) * STUDENTS_PER_CLASS)]
    for index, school_class in enumerate(classes):
        for offset in range(STUDENTS_PER_CLASS):
            parent = parents[index * STUDENTS_PER_CLASS + offset]
            post(
                "/students",
                {
                    "first_name": f"Child{offset}",
                    "last_name": f"Family{index}",
                    "admission_number": f"ADM{uuid4().hex[:10]}",
                    "class_id": school_class["id"],
                    "parent_id": parent.id,
                },
            )

    # The counts the admin sees on the classes page are now non-zero.
    listed = api.get(f"/classes?academic_year={year}", headers=admin_headers).json()
    assert listed["total"] == len(CLASSES)
    assert all(item["active_student_count"] == STUDENTS_PER_CLASS for item in listed["items"])

    # 4. Bill every class for the term, plus a one-off uniform charge.
    period = f"Term 1 {year}"
    for school_class in classes:
        result = post(
            "/fee-assignments/bulk",
            {
                "class_id": school_class["id"],
                "fee_type_id": tuition["id"],
                "period_label": period,
                "due_date": "2026-10-01",
            },
        )
        assert result["created"] == STUDENTS_PER_CLASS
        assert result["amount"] == "250.00"

    intake = post(
        "/fee-assignments/bulk",
        {
            "class_id": classes[0]["id"],
            "fee_type_id": uniform["id"],
            "period_label": f"Intake {year}",
            "amount": "80.00",
        },
    )
    assert intake["created"] == STUDENTS_PER_CLASS

    # 5. The school is set up: every student is billed, and the bursar's list
    #    reflects it without a single direct database write.
    billed = api.get(
        f"/fee-assignments?period_label={period}&limit=200", headers=admin_headers
    ).json()
    assert billed["total"] == len(CLASSES) * STUDENTS_PER_CLASS
    assert {item["amount"] for item in billed["items"]} == {"250.00"}
    assert len({item["student"]["id"] for item in billed["items"]}) == billed["total"]

    first_class = api.get(
        f"/fee-assignments?class_id={classes[0]['id']}&limit=200", headers=admin_headers
    ).json()
    # Tuition and uniform for each child in the first class.
    assert first_class["total"] == STUDENTS_PER_CLASS * 2


def test_a_parent_created_along_the_way_sees_only_their_own_child(
    api, admin_headers, token_for, make_user, year
):
    """The setup above hands parents real children. The scoping that matters
    once they log in is asserted here rather than assumed."""
    school_class = api.post(
        "/classes", json={"name": "Grade 4", "academic_year": year}, headers=admin_headers
    ).json()

    mine, headers = token_for(UserRole.PARENT)
    theirs = make_user(UserRole.PARENT)

    students = [
        api.post(
            "/students",
            json={
                "first_name": "Child",
                "last_name": "Family",
                "admission_number": f"ADM{uuid4().hex[:10]}",
                "class_id": school_class["id"],
                "parent_id": parent.id,
            },
            headers=admin_headers,
        ).json()
        for parent in (mine, theirs)
    ]

    assert api.get(f"/students/{students[0]['id']}", headers=headers).status_code == 200
    assert api.get(f"/students/{students[1]['id']}", headers=headers).status_code == 404
