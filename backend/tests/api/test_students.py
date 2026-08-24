"""Student CRUD through HTTP.

The permission cases here overlap the ones in ``test_rbac.py`` on purpose.
Those exercise the guards on throwaway routes so a bug in ``require_role``
cannot hide behind a bug in a route; these check the guards were actually
wired onto the real endpoints, which is a different mistake.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models import StudentStatus, UserRole

pytestmark = pytest.mark.db


def an_admission_number() -> str:
    return f"ADM{uuid4().hex[:10]}"


def a_student(**overrides) -> dict:
    return {
        "first_name": "Ama",
        "last_name": "Mensah",
        "admission_number": an_admission_number(),
    } | overrides


class TestCreate:
    def test_an_admin_enrols_a_student(self, api, admin_headers):
        response = api.post("/students", json=a_student(), headers=admin_headers)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["full_name"] == "Ama Mensah"
        assert body["status"] == "active"
        assert body["school_class"] is None
        assert body["parent"] is None

    def test_a_student_can_be_placed_and_linked_at_once(
        self, api, admin_headers, make_class, make_user
    ):
        school_class = make_class(name="Grade 5B")
        parent = make_user(UserRole.PARENT)

        body = api.post(
            "/students",
            json=a_student(class_id=school_class.id, parent_id=parent.id),
            headers=admin_headers,
        ).json()
        assert body["school_class"]["name"] == "Grade 5B"
        assert body["parent"]["email"] == parent.email

    def test_the_parent_summary_carries_no_credentials(self, api, admin_headers, make_user):
        """The reason the response schemas are not the ORM models."""
        parent = make_user(UserRole.PARENT)
        response = api.post("/students", json=a_student(parent_id=parent.id), headers=admin_headers)
        assert "password" not in response.text.lower()

    def test_a_duplicate_admission_number_is_a_conflict(self, api, admin_headers):
        number = an_admission_number()
        api.post("/students", json=a_student(admission_number=number), headers=admin_headers)

        response = api.post(
            "/students", json=a_student(admission_number=number), headers=admin_headers
        )
        assert response.status_code == 409
        assert "admission number" in response.json()["detail"]

    def test_an_unknown_class_is_reported_against_the_field(self, api, admin_headers):
        response = api.post("/students", json=a_student(class_id=99999999), headers=admin_headers)
        assert response.status_code == 422
        assert response.json()["detail"].startswith("class_id:")

    def test_an_archived_class_will_not_take_new_students(self, api, admin_headers, make_class):
        """Letting it through would quietly re-populate a class the school
        considers closed."""
        archived = make_class(archived_at=datetime.now(UTC))
        response = api.post(
            "/students", json=a_student(class_id=archived.id), headers=admin_headers
        )
        assert response.status_code == 422
        assert "archived" in response.json()["detail"]

    def test_an_unknown_parent_is_reported_against_the_field(self, api, admin_headers):
        response = api.post("/students", json=a_student(parent_id=99999999), headers=admin_headers)
        assert response.status_code == 422
        assert response.json()["detail"].startswith("parent_id:")

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_only_a_parent_account_may_be_a_parent(self, api, admin_headers, make_user, role):
        """Parent scoping keys off the role. A student hung off an admin
        account is a link the check that governs it cannot see."""
        not_a_parent = make_user(role)
        response = api.post(
            "/students", json=a_student(parent_id=not_a_parent.id), headers=admin_headers
        )
        assert response.status_code == 422
        assert "not a parent account" in response.json()["detail"]

    def test_a_blank_name_is_refused(self, api, admin_headers):
        response = api.post("/students", json=a_student(first_name="  "), headers=admin_headers)
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "first_name"

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_enrol(self, api, headers_for, role):
        response = api.post("/students", json=a_student(), headers=headers_for(role))
        assert response.status_code == 403


class TestRead:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_and_admins_read_any_student(self, api, headers_for, make_student, role):
        student = make_student()
        response = api.get(f"/students/{student.id}", headers=headers_for(role))
        assert response.status_code == 200
        assert response.json()["id"] == student.id

    def test_a_parent_reads_their_own_child(self, api, token_for, make_student):
        parent, headers = token_for(UserRole.PARENT)
        child = make_student(parent=parent)
        response = api.get(f"/students/{child.id}", headers=headers)
        assert response.status_code == 200

    def test_another_parents_child_is_404_not_403(self, api, token_for, make_student, make_user):
        """403 confirms the record exists, which is the thing the guard is
        protecting: a parent could walk the ids and learn the school roll."""
        _, headers = token_for(UserRole.PARENT)
        other_child = make_student(parent=make_user(UserRole.PARENT))

        forbidden = api.get(f"/students/{other_child.id}", headers=headers)
        missing = api.get("/students/99999999", headers=headers)
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()


class TestList:
    def test_filtering_by_class(self, api, admin_headers, make_class, make_student):
        school_class = make_class()
        make_student(school_class=school_class)
        make_student()

        body = api.get(f"/students?class_id={school_class.id}", headers=admin_headers).json()
        assert body["total"] == 1

    def test_filtering_by_parent(self, api, admin_headers, make_user, make_student):
        parent = make_user(UserRole.PARENT)
        make_student(parent=parent)
        make_student(parent=parent)
        make_student()

        body = api.get(f"/students?parent_id={parent.id}", headers=admin_headers).json()
        assert body["total"] == 2

    def test_filtering_by_status(self, api, admin_headers, make_class, make_student):
        school_class = make_class()
        make_student(school_class=school_class)
        make_student(school_class=school_class, status=StudentStatus.INACTIVE)

        body = api.get(
            f"/students?class_id={school_class.id}&status=inactive", headers=admin_headers
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "inactive"

    def test_inactive_students_are_listed_unless_excluded(
        self, api, admin_headers, make_class, make_student
    ):
        """Unlike archived classes: a roll you cannot search for a former
        pupil in is the more annoying failure."""
        school_class = make_class()
        make_student(school_class=school_class)
        make_student(school_class=school_class, status=StudentStatus.INACTIVE)

        body = api.get(f"/students?class_id={school_class.id}", headers=admin_headers).json()
        assert body["total"] == 2

    def test_finding_the_students_with_no_class(self, api, admin_headers, make_student, make_class):
        """The list an admin needs at the start of a year."""
        placed = make_student(school_class=make_class())
        unplaced = make_student()

        body = api.get("/students?unassigned=true&limit=200", headers=admin_headers).json()
        ids = [item["id"] for item in body["items"]]
        assert unplaced.id in ids
        assert placed.id not in ids

    def test_searching_by_admission_number(self, api, admin_headers, make_student):
        student = make_student(admission_number=an_admission_number())
        body = api.get(f"/students?q={student.admission_number}", headers=admin_headers).json()
        assert [item["id"] for item in body["items"]] == [student.id]

    def test_searching_by_full_name(self, api, admin_headers, make_class, make_student):
        """Searching the two name columns separately never matches "Ama Mensah"."""
        school_class = make_class()
        wanted = make_student(first_name="Ama", last_name="Mensah", school_class=school_class)
        make_student(first_name="Kofi", last_name="Boateng", school_class=school_class)

        body = api.get(
            f"/students?class_id={school_class.id}&q=ama mensah", headers=admin_headers
        ).json()
        assert [item["id"] for item in body["items"]] == [wanted.id]

    def test_the_list_is_ordered_by_surname(self, api, admin_headers, make_class, make_student):
        school_class = make_class()
        make_student(last_name="Zebrahene", school_class=school_class)
        make_student(last_name="Ankrah", school_class=school_class)

        body = api.get(f"/students?class_id={school_class.id}", headers=admin_headers).json()
        assert [item["last_name"] for item in body["items"]] == ["Ankrah", "Zebrahene"]

    def test_the_page_reports_its_bounds(self, api, admin_headers, make_class, make_student):
        school_class = make_class()
        for _ in range(3):
            make_student(school_class=school_class)

        body = api.get(
            f"/students?class_id={school_class.id}&limit=2", headers=admin_headers
        ).json()
        assert len(body["items"]) == 2
        assert body["total"] == 3

    def test_the_query_count_does_not_grow_with_the_page(
        self, api, admin_headers, make_class, make_user, make_student, query_counter
    ):
        """Every student carries a class and a parent. Lazy-loaded, a page of
        fifty is a hundred and one queries."""
        small_class, large_class = make_class(), make_class()
        make_student(school_class=small_class, parent=make_user(UserRole.PARENT))
        for _ in range(6):
            make_student(school_class=large_class, parent=make_user(UserRole.PARENT))

        api.get("/students?limit=1", headers=admin_headers)

        with query_counter() as small:
            api.get(f"/students?class_id={small_class.id}", headers=admin_headers)
        with query_counter() as large:
            api.get(f"/students?class_id={large_class.id}", headers=admin_headers)

        assert len(small) == len(large)

    def test_parents_may_not_list_students(self, api, parent_headers):
        assert api.get("/students", headers=parent_headers).status_code == 403


class TestUpdate:
    def test_moving_a_student_to_another_class(self, api, admin_headers, make_class, make_student):
        student = make_student(school_class=make_class())
        destination = make_class(name="Grade 6A")

        response = api.patch(
            f"/students/{student.id}", json={"class_id": destination.id}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["school_class"]["id"] == destination.id

    def test_an_explicit_null_detaches_the_student(
        self, api, admin_headers, make_class, make_student
    ):
        """Distinct from omitting the field, which is why the route reads
        exclude_unset rather than exclude_none."""
        student = make_student(school_class=make_class())
        body = api.patch(
            f"/students/{student.id}", json={"class_id": None}, headers=admin_headers
        ).json()
        assert body["school_class"] is None

    def test_an_omitted_field_is_left_alone(self, api, admin_headers, make_class, make_student):
        school_class = make_class()
        student = make_student(school_class=school_class)
        body = api.patch(
            f"/students/{student.id}", json={"first_name": "Akosua"}, headers=admin_headers
        ).json()
        assert body["school_class"]["id"] == school_class.id
        assert body["first_name"] == "Akosua"

    def test_linking_a_parent_afterwards(self, api, admin_headers, make_student, make_user):
        student = make_student()
        parent = make_user(UserRole.PARENT)
        body = api.patch(
            f"/students/{student.id}", json={"parent_id": parent.id}, headers=admin_headers
        ).json()
        assert body["parent"]["id"] == parent.id

    def test_withdrawing_a_student(self, api, admin_headers, make_student):
        student = make_student()
        body = api.patch(
            f"/students/{student.id}", json={"status": "inactive"}, headers=admin_headers
        ).json()
        assert body["status"] == "inactive"

    def test_a_student_cannot_be_moved_into_an_archived_class(
        self, api, admin_headers, make_class, make_student
    ):
        student = make_student()
        archived = make_class(archived_at=datetime.now(UTC))
        response = api.patch(
            f"/students/{student.id}", json={"class_id": archived.id}, headers=admin_headers
        )
        assert response.status_code == 422

    def test_a_non_parent_cannot_be_linked(self, api, admin_headers, make_student, make_user):
        student = make_student()
        staff = make_user(UserRole.STAFF)
        response = api.patch(
            f"/students/{student.id}", json={"parent_id": staff.id}, headers=admin_headers
        )
        assert response.status_code == 422

    def test_a_duplicate_admission_number_is_a_conflict(self, api, admin_headers, make_student):
        first = make_student()
        second = make_student()
        response = api.patch(
            f"/students/{second.id}",
            json={"admission_number": first.admission_number},
            headers=admin_headers,
        )
        assert response.status_code == 409

    def test_an_unknown_student_is_404(self, api, admin_headers):
        response = api.patch("/students/99999999", json={"first_name": "x"}, headers=admin_headers)
        assert response.status_code == 404

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_update(self, api, headers_for, make_student, role):
        student = make_student()
        response = api.patch(
            f"/students/{student.id}", json={"first_name": "x"}, headers=headers_for(role)
        )
        assert response.status_code == 403

    def test_a_parent_cannot_edit_their_own_child(self, api, token_for, make_student):
        """Reading is scoped by ownership; writing is not opened by it."""
        parent, headers = token_for(UserRole.PARENT)
        child = make_student(parent=parent)
        response = api.patch(f"/students/{child.id}", json={"first_name": "x"}, headers=headers)
        assert response.status_code == 403
