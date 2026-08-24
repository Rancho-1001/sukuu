"""The account directory.

Narrow on purpose: it exists so an administrator attaching a student to a
parent can choose one instead of typing a numeric id. The tests that matter
are about who may read it, because it is a list of every email address in the
school.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import UserRole

pytestmark = pytest.mark.db

URL = "/users"


class TestListing:
    def test_filtering_by_role(self, api, admin_headers, make_user):
        parent = make_user(UserRole.PARENT)
        staff = make_user(UserRole.STAFF)

        body = api.get(f"{URL}?role=parent&limit=200", headers=admin_headers).json()
        ids = {user["id"] for user in body["items"]}
        assert parent.id in ids
        assert staff.id not in ids
        assert all(user["role"] == "parent" for user in body["items"])

    def test_searching_by_name(self, api, admin_headers, make_user):
        unique = f"Adjoa{uuid4().hex[:8]}"
        target = make_user(UserRole.PARENT, email=f"{unique.lower()}@example.com")
        target.name = unique

        body = api.get(f"{URL}?q={unique}", headers=admin_headers).json()
        assert [user["id"] for user in body["items"]] == [target.id]

    def test_searching_by_email(self, api, admin_headers, make_user):
        target = make_user(UserRole.PARENT, email=f"findme{uuid4().hex[:8]}@example.com")
        body = api.get(f"{URL}?q={target.email}", headers=admin_headers).json()
        assert [user["id"] for user in body["items"]] == [target.id]

    def test_no_password_hash_is_exposed(self, api, admin_headers, make_user):
        """The reason UserOut exists rather than returning the model."""
        make_user(UserRole.PARENT)
        assert "password" not in api.get(URL, headers=admin_headers).text.lower()

    def test_the_page_reports_its_bounds(self, api, admin_headers, make_user):
        make_user(UserRole.PARENT)
        body = api.get(f"{URL}?limit=1", headers=admin_headers).json()
        assert len(body["items"]) == 1
        assert body["total"] >= 1


class TestWhoMayRead:
    def test_an_admin_may(self, api, admin_headers):
        assert api.get(URL, headers=admin_headers).status_code == 200

    def test_a_bursar_may_not(self, api, staff_headers):
        """Recording a payment needs the student roster, not every email
        address in the school."""
        assert api.get(URL, headers=staff_headers).status_code == 403

    def test_a_parent_may_not(self, api, parent_headers):
        assert api.get(URL, headers=parent_headers).status_code == 403

    def test_anonymous_is_rejected(self, api):
        assert api.get(URL).status_code == 401
