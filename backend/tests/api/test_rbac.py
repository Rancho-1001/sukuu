"""The permission boundaries, exercised through HTTP.

These use throwaway routes mounted on the real app rather than the business
endpoints, which do not exist until Phase 3. That is deliberate: it tests the
guards themselves, so a bug in ``require_role`` cannot hide behind a bug in a
route, and the tests stay valid as endpoints come and go.

Every case asserts both directions. A guard that allows the right roles but
forgets to deny the wrong ones passes any allow-only test suite.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    CurrentUser,
    OwnStudent,
    require_admin,
    require_parent,
    require_staff,
)
from app.db.session import get_db
from app.models import Student, UserRole

pytestmark = pytest.mark.db


@pytest.fixture
def guarded_api(db_session):
    """A minimal app exposing one route per guard."""
    app = FastAPI()

    @app.get("/admin-only", dependencies=[Depends(require_admin)])
    def admin_only() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/staff-or-admin", dependencies=[Depends(require_staff)])
    def staff_or_admin() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/parent-only", dependencies=[Depends(require_parent)])
    def parent_only() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/any-authenticated")
    def any_authenticated(user: CurrentUser) -> dict[str, str]:
        return {"role": user.role.value}

    @app.get("/students/{student_id}")
    def read_student(student: OwnStudent) -> dict[str, int]:
        return {"id": student.id}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def token_for(api, make_user):
    """Mint a token for a fresh user of the given role."""

    def _token(role: UserRole):
        user = make_user(role)
        response = api.post(
            "/auth/login", data={"username": user.email, "password": user.raw_password}
        )
        assert response.status_code == 200, response.text
        return user, {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _token


ALL_ROLES = [UserRole.ADMIN, UserRole.STAFF, UserRole.PARENT]


class TestAdminOnly:
    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_only_admin_is_admitted(self, guarded_api, token_for, role):
        _, headers = token_for(role)
        response = guarded_api.get("/admin-only", headers=headers)
        expected = 200 if role is UserRole.ADMIN else 403
        assert response.status_code == expected

    def test_anonymous_is_rejected(self, guarded_api):
        assert guarded_api.get("/admin-only").status_code == 401


class TestStaffOrAdmin:
    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_parents_are_excluded(self, guarded_api, token_for, role):
        """Recording payments and reading reports is staff and admin only."""
        _, headers = token_for(role)
        response = guarded_api.get("/staff-or-admin", headers=headers)
        expected = 403 if role is UserRole.PARENT else 200
        assert response.status_code == expected

    def test_anonymous_is_rejected(self, guarded_api):
        assert guarded_api.get("/staff-or-admin").status_code == 401


class TestParentOnly:
    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_only_parents_are_admitted(self, guarded_api, token_for, role):
        """An admin is not a parent. Elevated privilege is not universal privilege."""
        _, headers = token_for(role)
        response = guarded_api.get("/parent-only", headers=headers)
        expected = 200 if role is UserRole.PARENT else 403
        assert response.status_code == expected


class TestAuthenticationItself:
    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_every_role_can_reach_an_unguarded_route(self, guarded_api, token_for, role):
        _, headers = token_for(role)
        response = guarded_api.get("/any-authenticated", headers=headers)
        assert response.status_code == 200
        assert response.json()["role"] == role.value

    def test_no_token_is_401_not_403(self, guarded_api):
        """401 means "who are you"; 403 means "not you". Anonymous is the former."""
        assert guarded_api.get("/any-authenticated").status_code == 401

    def test_malformed_authorization_header_is_rejected(self, guarded_api):
        response = guarded_api.get(
            "/any-authenticated", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )
        assert response.status_code == 401

    def test_token_without_the_bearer_prefix_is_rejected(self, guarded_api, token_for):
        _, headers = token_for(UserRole.ADMIN)
        raw = headers["Authorization"].removeprefix("Bearer ")
        assert (
            guarded_api.get("/any-authenticated", headers={"Authorization": raw}).status_code == 401
        )


class TestParentScoping:
    """Role is not enough: a parent may see their own children and no others."""

    @pytest.fixture
    def two_families(self, db_session, token_for):
        parent_a, headers_a = token_for(UserRole.PARENT)
        parent_b, headers_b = token_for(UserRole.PARENT)
        from uuid import uuid4

        child_a = Student(
            first_name="Ama", last_name="A", admission_number=uuid4().hex[:10], parent=parent_a
        )
        child_b = Student(
            first_name="Kofi", last_name="B", admission_number=uuid4().hex[:10], parent=parent_b
        )
        db_session.add_all([child_a, child_b])
        db_session.flush()
        return (parent_a, headers_a, child_a), (parent_b, headers_b, child_b)

    def test_a_parent_can_read_their_own_child(self, guarded_api, two_families):
        (_, headers_a, child_a), _ = two_families
        response = guarded_api.get(f"/students/{child_a.id}", headers=headers_a)
        assert response.status_code == 200
        assert response.json()["id"] == child_a.id

    def test_a_parent_cannot_read_another_parents_child(self, guarded_api, two_families):
        (_, headers_a, _), (_, _, child_b) = two_families
        assert guarded_api.get(f"/students/{child_b.id}", headers=headers_a).status_code == 404

    def test_the_refusal_is_404_not_403(self, guarded_api, two_families):
        """403 would confirm the student exists and let a parent walk the roll."""
        (_, headers_a, _), (_, _, child_b) = two_families
        forbidden = guarded_api.get(f"/students/{child_b.id}", headers=headers_a)
        missing = guarded_api.get("/students/99999999", headers=headers_a)
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()

    def test_staff_may_read_any_student(self, guarded_api, two_families, token_for):
        _, (_, _, child_b) = two_families
        _, staff_headers = token_for(UserRole.STAFF)
        assert guarded_api.get(f"/students/{child_b.id}", headers=staff_headers).status_code == 200

    def test_admin_may_read_any_student(self, guarded_api, two_families, token_for):
        _, (_, _, child_b) = two_families
        _, admin_headers = token_for(UserRole.ADMIN)
        assert guarded_api.get(f"/students/{child_b.id}", headers=admin_headers).status_code == 200
