"""Throttling repeated failed logins.

Counts live in ``audit_log``, which already records every failed attempt with a
timestamp. That choice is deliberate:

* no new infrastructure, and nothing to run alongside Postgres;
* the count is shared across processes, so it still holds when the API runs
  more than one worker or instance - an in-memory counter would give an
  attacker one full allowance per process;
* the evidence and the enforcement are the same rows, so a lockout can always
  be explained from the audit trail.

The cost is a query per login attempt. At this scale that is nothing, and both
filtered columns are indexed.

**Two limits, because one is not enough.** Counting only by source address lets
an attacker spread guesses for one account across many addresses. Counting only
by account lets an attacker spray one guess against thousands of accounts from
a single host. Neither alone is much use.

**The account limit is a denial-of-service trade-off, taken knowingly.** Anyone
who knows an email can lock its owner out for the window by failing five times.
The alternatives are worse for a project this size: no account limit at all
leaves targeted brute force wide open. Production would key on the
(account, source) pair and escalate to a challenge rather than a flat refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog

LOGIN_FAILED = "auth.login_failed"


@dataclass(frozen=True)
class RateLimitVerdict:
    allowed: bool
    retry_after_seconds: int
    reason: str | None = None


def client_ip(request: Request) -> str | None:
    """The caller's address, as far as it can be trusted.

    ``X-Forwarded-For`` is only consulted when ``trust_proxy_headers`` is on.
    Reading it unconditionally would be worse than having no limit at all: with
    no proxy in front, a client sets the header itself and presents a fresh
    address on every request, so the per-IP count never rises above one.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


def _failures_since(db: Session, since: datetime, *, target: str | None, ip: str | None) -> int:
    stmt = (
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == LOGIN_FAILED, AuditLog.timestamp >= since)
    )
    if target is not None:
        stmt = stmt.where(AuditLog.target == target)
    if ip is not None:
        stmt = stmt.where(AuditLog.ip_address == ip)
    return db.scalar(stmt) or 0


def check_login_allowed(db: Session, *, email: str, ip: str | None) -> RateLimitVerdict:
    """Decide whether this login attempt may proceed."""
    window = timedelta(minutes=settings.login_rate_limit_window_minutes)
    since = datetime.now(UTC) - window
    retry_after = int(window.total_seconds())

    by_email = _failures_since(db, since, target=email, ip=None)
    if by_email >= settings.login_max_attempts_per_email:
        return RateLimitVerdict(False, retry_after, "too many failed attempts for this account")

    if ip is not None:
        by_ip = _failures_since(db, since, target=None, ip=ip)
        if by_ip >= settings.login_max_attempts_per_ip:
            return RateLimitVerdict(
                False, retry_after, "too many failed attempts from this address"
            )

    return RateLimitVerdict(True, 0)


def enforce_login_rate_limit(db: Session, *, email: str, ip: str | None) -> None:
    """Raise 429 when the caller has spent their allowance."""
    verdict = check_login_allowed(db, email=email, ip=ip)
    if verdict.allowed:
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        # Deliberately vague: the same message whether or not the account
        # exists, so the throttle does not become an account oracle.
        detail="Too many failed login attempts. Try again later.",
        headers={"Retry-After": str(verdict.retry_after_seconds)},
    )
