"""Login and identity, over HTTP."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, UserRole

pytestmark = pytest.mark.db


class TestLogin:
    def test_valid_credentials_return_a_token(self, api, make_user):
        user = make_user(UserRole.ADMIN)
        response = api.post(
            "/auth/login", data={"username": user.email, "password": "correct-horse"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["expires_in"] > 0

    def test_wrong_password_is_rejected(self, api, make_user):
        user = make_user(UserRole.ADMIN)
        response = api.post("/auth/login", data={"username": user.email, "password": "nope"})
        assert response.status_code == 401

    def test_unknown_email_is_rejected(self, api):
        response = api.post(
            "/auth/login", data={"username": "nobody@example.com", "password": "nope"}
        )
        assert response.status_code == 401

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, api, make_user):
        """The error must not reveal whether an account exists."""
        user = make_user(UserRole.PARENT)
        wrong_password = api.post("/auth/login", data={"username": user.email, "password": "nope"})
        no_such_user = api.post(
            "/auth/login", data={"username": "ghost@example.com", "password": "nope"}
        )
        assert wrong_password.status_code == no_such_user.status_code
        assert wrong_password.json() == no_such_user.json()

    def test_email_is_matched_case_insensitively(self, api, make_user):
        make_user(UserRole.STAFF, email="mixed.case@example.com")
        response = api.post(
            "/auth/login",
            data={"username": "MIXED.CASE@EXAMPLE.COM", "password": "correct-horse"},
        )
        assert response.status_code == 200

    def test_response_never_contains_the_password_hash(self, api, make_user):
        user = make_user(UserRole.ADMIN)
        response = api.post(
            "/auth/login", data={"username": user.email, "password": "correct-horse"}
        )
        assert "password" not in response.text.lower()


class TestMe:
    def test_returns_the_authenticated_user(self, api, make_user, auth_headers):
        user = make_user(UserRole.STAFF)
        response = api.get("/auth/me", headers=auth_headers(user))
        assert response.status_code == 200
        assert response.json() == {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": "staff",
        }

    def test_never_exposes_the_password_hash(self, api, make_user, auth_headers):
        user = make_user(UserRole.ADMIN)
        assert "password_hash" not in api.get("/auth/me", headers=auth_headers(user)).text

    def test_requires_a_token(self, api):
        assert api.get("/auth/me").status_code == 401

    def test_rejects_a_garbage_token(self, api):
        response = api.get("/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401

    def test_rejects_a_token_for_a_deleted_user(self, api, make_user, auth_headers, db_session):
        user = make_user(UserRole.PARENT)
        headers = auth_headers(user)
        db_session.delete(user)
        db_session.flush()
        assert api.get("/auth/me", headers=headers).status_code == 401


class TestAuditTrail:
    def test_successful_login_is_recorded(self, api, make_user, db_session):
        user = make_user(UserRole.ADMIN)
        api.post("/auth/login", data={"username": user.email, "password": "correct-horse"})
        actions = db_session.scalars(
            select(AuditLog.action).where(AuditLog.user_id == user.id)
        ).all()
        assert "auth.login" in actions

    def test_failed_login_is_recorded(self, api, make_user, db_session):
        """A burst of these is what a brute-force attempt looks like in the log."""
        user = make_user(UserRole.ADMIN)
        api.post("/auth/login", data={"username": user.email, "password": "wrong"})
        actions = db_session.scalars(
            select(AuditLog.action).where(AuditLog.user_id == user.id)
        ).all()
        assert "auth.login_failed" in actions

    def test_failed_login_for_an_unknown_email_is_still_recorded(self, api, db_session):
        api.post("/auth/login", data={"username": "ghost@example.com", "password": "x"})
        entry = db_session.scalar(
            select(AuditLog)
            .where(AuditLog.action == "auth.login_failed")
            .order_by(AuditLog.id.desc())
        )
        assert entry is not None
        assert entry.target == "ghost@example.com"
        assert entry.user_id is None
