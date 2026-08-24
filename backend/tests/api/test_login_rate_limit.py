"""Throttling repeated failed logins."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.models import AuditLog, UserRole

pytestmark = pytest.mark.db


def attempt(api, email: str, password: str = "wrong-password"):
    return api.post("/auth/login", data={"username": email, "password": password})


def exhaust(api, email: str, times: int | None = None):
    """Burn the per-account allowance."""
    for _ in range(times if times is not None else settings.login_max_attempts_per_email):
        attempt(api, email)


class TestPerAccountLimit:
    def test_attempts_within_the_allowance_are_only_rejected_as_unauthorised(self, api, make_user):
        user = make_user(UserRole.ADMIN)
        for _ in range(settings.login_max_attempts_per_email):
            assert attempt(api, user.email).status_code == 401

    def test_the_next_attempt_is_throttled(self, api, make_user):
        user = make_user(UserRole.ADMIN)
        exhaust(api, user.email)
        assert attempt(api, user.email).status_code == 429

    def test_the_throttled_response_says_when_to_come_back(self, api, make_user):
        user = make_user(UserRole.ADMIN)
        exhaust(api, user.email)
        response = attempt(api, user.email)
        assert response.headers["retry-after"] == str(settings.login_rate_limit_window_minutes * 60)

    def test_the_correct_password_is_refused_too(self, api, make_user):
        """The point of the limit. Letting a correct guess through defeats it."""
        user = make_user(UserRole.ADMIN)
        exhaust(api, user.email)
        assert attempt(api, user.email, user.raw_password).status_code == 429

    def test_another_account_is_unaffected(self, api, make_user):
        victim = make_user(UserRole.ADMIN)
        bystander = make_user(UserRole.STAFF)
        exhaust(api, victim.email)
        assert attempt(api, bystander.email, bystander.raw_password).status_code == 200

    def test_an_unknown_email_is_throttled_the_same_way(self, api):
        """Otherwise the throttle itself would reveal which accounts exist."""
        exhaust(api, "ghost@example.com")
        assert attempt(api, "ghost@example.com").status_code == 429

    def test_a_successful_login_is_still_possible_before_the_allowance_runs_out(
        self, api, make_user
    ):
        user = make_user(UserRole.PARENT)
        exhaust(api, user.email, times=settings.login_max_attempts_per_email - 1)
        assert attempt(api, user.email, user.raw_password).status_code == 200


class TestWindowExpiry:
    def test_failures_older_than_the_window_do_not_count(self, api, make_user, db_session):
        user = make_user(UserRole.ADMIN)
        stale = datetime.now(UTC) - timedelta(minutes=settings.login_rate_limit_window_minutes + 5)
        for _ in range(settings.login_max_attempts_per_email + 3):
            db_session.add(
                AuditLog(
                    action="auth.login_failed",
                    target=user.email,
                    timestamp=stale,
                    ip_address="testclient",
                )
            )
        db_session.flush()
        assert attempt(api, user.email, user.raw_password).status_code == 200

    def test_failures_inside_the_window_do_count(self, api, make_user, db_session):
        user = make_user(UserRole.ADMIN)
        recent = datetime.now(UTC) - timedelta(minutes=1)
        for _ in range(settings.login_max_attempts_per_email):
            db_session.add(
                AuditLog(action="auth.login_failed", target=user.email, timestamp=recent)
            )
        db_session.flush()
        assert attempt(api, user.email, user.raw_password).status_code == 429


class TestPerSourceLimit:
    def test_spraying_many_accounts_from_one_host_is_throttled(self, api, db_session):
        """The per-account limit alone would never notice one guess each."""
        recent = datetime.now(UTC) - timedelta(minutes=1)
        for n in range(settings.login_max_attempts_per_ip):
            db_session.add(
                AuditLog(
                    action="auth.login_failed",
                    target=f"victim{n}@example.com",
                    ip_address="testclient",
                    timestamp=recent,
                )
            )
        db_session.flush()
        assert attempt(api, "someone-new@example.com").status_code == 429

    def test_a_different_source_is_unaffected(self, api, make_user, db_session):
        recent = datetime.now(UTC) - timedelta(minutes=1)
        for n in range(settings.login_max_attempts_per_ip + 5):
            db_session.add(
                AuditLog(
                    action="auth.login_failed",
                    target=f"victim{n}@example.com",
                    ip_address="198.51.100.9",
                    timestamp=recent,
                )
            )
        db_session.flush()
        user = make_user(UserRole.STAFF)
        assert attempt(api, user.email, user.raw_password).status_code == 200


class TestAuditTrail:
    def test_the_source_address_is_recorded_on_a_failure(self, api, make_user, db_session):
        from sqlalchemy import select

        user = make_user(UserRole.ADMIN)
        attempt(api, user.email)
        entry = db_session.scalar(
            select(AuditLog)
            .where(AuditLog.action == "auth.login_failed", AuditLog.target == user.email)
            .order_by(AuditLog.id.desc())
        )
        assert entry.ip_address == "testclient"
