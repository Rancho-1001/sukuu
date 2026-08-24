"""Class CRUD through HTTP.

Every test picks a unique academic year and filters by it. The test database
is migrated, not emptied, and a suite that assumes it is the only thing in
there starts failing the day someone runs the seed script against it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import StudentStatus, UserRole

pytestmark = pytest.mark.db


def a_year() -> str:
    """An academic year no other test is using."""
    return f"YR{uuid4().hex[:8]}"


class TestCreate:
    def test_an_admin_creates_a_class(self, api, admin_headers):
        year = a_year()
        response = api.post(
            "/classes", json={"name": "Grade 5B", "academic_year": year}, headers=admin_headers
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Grade 5B"
        assert body["academic_year"] == year
        assert body["archived_at"] is None
        assert body["active_student_count"] == 0
        assert isinstance(body["id"], int)

    def test_the_class_is_readable_afterwards(self, api, admin_headers):
        created = api.post(
            "/classes", json={"name": "Grade 6A", "academic_year": a_year()}, headers=admin_headers
        ).json()
        response = api.get(f"/classes/{created['id']}", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "Grade 6A"

    def test_the_name_is_trimmed(self, api, admin_headers):
        response = api.post(
            "/classes",
            json={"name": "  Grade 5B  ", "academic_year": a_year()},
            headers=admin_headers,
        )
        assert response.json()["name"] == "Grade 5B"

    def test_a_blank_name_is_refused_by_name(self, api, admin_headers):
        """A name of spaces passes a naive min_length and then trips the CHECK
        constraint as a 500. Trimming before the length check is what makes it
        a 422 that says which field."""
        response = api.post(
            "/classes", json={"name": "   ", "academic_year": a_year()}, headers=admin_headers
        )
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "name"

    def test_a_duplicate_name_and_year_is_a_conflict(self, api, admin_headers):
        year = a_year()
        body = {"name": "Grade 5B", "academic_year": year}
        assert api.post("/classes", json=body, headers=admin_headers).status_code == 201

        response = api.post("/classes", json=body, headers=admin_headers)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_the_same_name_in_another_year_is_fine(self, api, admin_headers):
        """Grade 5B exists every year. The constraint is on the pair."""
        api.post(
            "/classes", json={"name": "Grade 5B", "academic_year": a_year()}, headers=admin_headers
        )
        response = api.post(
            "/classes", json={"name": "Grade 5B", "academic_year": a_year()}, headers=admin_headers
        )
        assert response.status_code == 201

    def test_an_unknown_field_is_refused(self, api, admin_headers):
        """A typo'd field name silently ignored is a bug report six months
        later about a setting that never applied."""
        response = api.post(
            "/classes",
            json={"name": "Grade 5B", "academic_year": a_year(), "capacity": 30},
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_create(self, api, headers_for, role):
        response = api.post(
            "/classes",
            json={"name": "Grade 5B", "academic_year": a_year()},
            headers=headers_for(role),
        )
        assert response.status_code == 403

    def test_anonymous_is_rejected(self, api):
        response = api.post("/classes", json={"name": "Grade 5B", "academic_year": "2026"})
        assert response.status_code == 401


class TestList:
    def test_the_page_reports_its_own_bounds(self, api, admin_headers, make_class):
        year = a_year()
        for index in range(5):
            make_class(name=f"Class {index}", academic_year=year)

        response = api.get(f"/classes?academic_year={year}&limit=2&offset=0", headers=admin_headers)
        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 0

    def test_offset_walks_the_list_without_repeating(self, api, admin_headers, make_class):
        year = a_year()
        for index in range(5):
            make_class(name=f"Class {index}", academic_year=year)

        seen = []
        for offset in (0, 2, 4):
            page = api.get(
                f"/classes?academic_year={year}&limit=2&offset={offset}", headers=admin_headers
            ).json()
            seen.extend(item["id"] for item in page["items"])
        assert len(seen) == len(set(seen)) == 5

    def test_an_oversized_limit_is_refused(self, api, admin_headers):
        """Without a cap, the client decides how much memory the server spends."""
        assert api.get("/classes?limit=100000", headers=admin_headers).status_code == 422

    def test_filtering_by_year(self, api, admin_headers, make_class):
        wanted, other = a_year(), a_year()
        make_class(academic_year=wanted)
        make_class(academic_year=other)

        body = api.get(f"/classes?academic_year={wanted}", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["academic_year"] == wanted

    def test_search_matches_part_of_the_name(self, api, admin_headers, make_class):
        year = a_year()
        make_class(name="Grade 5B", academic_year=year)
        make_class(name="Grade 6A", academic_year=year)

        body = api.get(f"/classes?academic_year={year}&q=5b", headers=admin_headers).json()
        assert [item["name"] for item in body["items"]] == ["Grade 5B"]

    def test_an_underscore_in_the_search_is_not_a_wildcard(self, api, admin_headers, make_class):
        """``_`` matches any single character in a LIKE pattern. Unescaped,
        searching for "5_B" would also return "5xB"."""
        year = a_year()
        make_class(name="5_B", academic_year=year)
        make_class(name="5xB", academic_year=year)

        body = api.get(f"/classes?academic_year={year}&q=5_B", headers=admin_headers).json()
        assert [item["name"] for item in body["items"]] == ["5_B"]

    def test_a_percent_in_the_search_is_not_a_wildcard(self, api, admin_headers, make_class):
        year = a_year()
        make_class(name="Grade 5B", academic_year=year)

        body = api.get(f"/classes?academic_year={year}&q=%25", headers=admin_headers).json()
        assert body["total"] == 0

    def test_archived_classes_are_hidden_by_default(self, api, admin_headers, make_class):
        from datetime import UTC, datetime

        year = a_year()
        make_class(name="Live", academic_year=year)
        make_class(name="Gone", academic_year=year, archived_at=datetime.now(UTC))

        body = api.get(f"/classes?academic_year={year}", headers=admin_headers).json()
        assert [item["name"] for item in body["items"]] == ["Live"]

    def test_archived_classes_can_be_asked_for(self, api, admin_headers, make_class):
        from datetime import UTC, datetime

        year = a_year()
        make_class(name="Live", academic_year=year)
        make_class(name="Gone", academic_year=year, archived_at=datetime.now(UTC))

        body = api.get(
            f"/classes?academic_year={year}&include_archived=true", headers=admin_headers
        ).json()
        assert body["total"] == 2

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_may_read_the_list(self, api, headers_for, role):
        """A bursar recording a payment has to find the student first."""
        assert api.get("/classes", headers=headers_for(role)).status_code == 200

    def test_parents_may_not(self, api, parent_headers):
        assert api.get("/classes", headers=parent_headers).status_code == 403


class TestStudentCounts:
    def test_only_active_students_are_counted(self, api, admin_headers, make_class, make_student):
        year = a_year()
        school_class = make_class(academic_year=year)
        make_student(school_class=school_class)
        make_student(school_class=school_class)
        make_student(school_class=school_class, status=StudentStatus.INACTIVE)

        body = api.get(f"/classes?academic_year={year}", headers=admin_headers).json()
        assert body["items"][0]["active_student_count"] == 2

    def test_an_empty_class_still_appears(self, api, admin_headers, make_class):
        """The status filter has to live in the JOIN condition. In a WHERE
        clause the outer-joined NULL row fails the comparison and the class
        disappears from the list entirely."""
        year = a_year()
        make_class(academic_year=year)

        body = api.get(f"/classes?academic_year={year}", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["active_student_count"] == 0

    def test_a_class_of_only_inactive_students_still_appears(
        self, api, admin_headers, make_class, make_student
    ):
        year = a_year()
        school_class = make_class(academic_year=year)
        make_student(school_class=school_class, status=StudentStatus.INACTIVE)

        body = api.get(f"/classes?academic_year={year}", headers=admin_headers).json()
        assert body["total"] == 1
        assert body["items"][0]["active_student_count"] == 0

    def test_the_query_count_does_not_grow_with_the_page(
        self, api, admin_headers, make_class, make_student, query_counter
    ):
        """The N+1 the roadmap warns about. It is invisible at demo scale -
        four classes, four extra queries - so it has to be asserted rather
        than eyeballed."""
        small_year, large_year = a_year(), a_year()
        make_student(school_class=make_class(academic_year=small_year))
        for _ in range(6):
            make_student(school_class=make_class(academic_year=large_year))

        # One request first: the very first authenticated call also loads the
        # user row, and counting that would compare a cold cache against a warm
        # one rather than one page size against another.
        api.get("/classes?limit=1", headers=admin_headers)

        with query_counter() as small:
            api.get(f"/classes?academic_year={small_year}", headers=admin_headers)
        with query_counter() as large:
            api.get(f"/classes?academic_year={large_year}", headers=admin_headers)

        assert len(small) == len(large)


class TestUpdate:
    def test_an_admin_renames_a_class(self, api, admin_headers, make_class):
        school_class = make_class(name="Grade 5B", academic_year=a_year())
        response = api.patch(
            f"/classes/{school_class.id}", json={"name": "Grade 5C"}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Grade 5C"

    def test_an_omitted_field_is_left_alone(self, api, admin_headers, make_class):
        year = a_year()
        school_class = make_class(name="Grade 5B", academic_year=year)
        body = api.patch(
            f"/classes/{school_class.id}", json={"name": "Grade 5C"}, headers=admin_headers
        ).json()
        assert body["academic_year"] == year

    def test_renaming_onto_an_existing_pair_is_a_conflict(self, api, admin_headers, make_class):
        year = a_year()
        make_class(name="Grade 5B", academic_year=year)
        other = make_class(name="Grade 6A", academic_year=year)

        response = api.patch(
            f"/classes/{other.id}", json={"name": "Grade 5B"}, headers=admin_headers
        )
        assert response.status_code == 409

    def test_an_unknown_class_is_404(self, api, admin_headers):
        response = api.patch("/classes/99999999", json={"name": "x"}, headers=admin_headers)
        assert response.status_code == 404

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_update(self, api, headers_for, make_class, role):
        school_class = make_class(academic_year=a_year())
        response = api.patch(
            f"/classes/{school_class.id}", json={"name": "x"}, headers=headers_for(role)
        )
        assert response.status_code == 403


class TestArchiving:
    def test_archiving_stamps_the_class(self, api, admin_headers, make_class):
        school_class = make_class(academic_year=a_year())
        response = api.post(f"/classes/{school_class.id}/archive", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["archived_at"] is not None

    def test_an_archived_class_leaves_the_default_list(self, api, admin_headers, make_class):
        year = a_year()
        school_class = make_class(academic_year=year)
        api.post(f"/classes/{school_class.id}/archive", headers=admin_headers)

        assert api.get(f"/classes?academic_year={year}", headers=admin_headers).json()["total"] == 0

    def test_archiving_twice_keeps_the_first_timestamp(self, api, admin_headers, make_class):
        """Otherwise the record stops saying when the class actually ended."""
        school_class = make_class(academic_year=a_year())
        first = api.post(f"/classes/{school_class.id}/archive", headers=admin_headers).json()
        second = api.post(f"/classes/{school_class.id}/archive", headers=admin_headers).json()
        assert first["archived_at"] == second["archived_at"]

    def test_restoring_brings_it_back(self, api, admin_headers, make_class):
        year = a_year()
        school_class = make_class(academic_year=year)
        api.post(f"/classes/{school_class.id}/archive", headers=admin_headers)

        response = api.post(f"/classes/{school_class.id}/restore", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["archived_at"] is None
        assert api.get(f"/classes?academic_year={year}", headers=admin_headers).json()["total"] == 1

    def test_archiving_does_not_delete_the_students(
        self, api, admin_headers, make_class, make_student, db_session
    ):
        """The whole reason archive exists rather than delete."""
        school_class = make_class(academic_year=a_year())
        student = make_student(school_class=school_class)
        api.post(f"/classes/{school_class.id}/archive", headers=admin_headers)

        db_session.refresh(student)
        assert student.class_id == school_class.id

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_archive(self, api, headers_for, make_class, role):
        school_class = make_class(academic_year=a_year())
        response = api.post(f"/classes/{school_class.id}/archive", headers=headers_for(role))
        assert response.status_code == 403

    def test_an_unknown_class_is_404(self, api, admin_headers):
        assert api.post("/classes/99999999/archive", headers=admin_headers).status_code == 404
