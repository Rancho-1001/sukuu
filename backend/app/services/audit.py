"""Recording who did what.

Two entry points:

* :func:`record` for deliberate, described events - a login, a fee assigned.
* :class:`AuditMiddleware` for blanket coverage of every mutating request, so
  a new endpoint is audited the moment it exists rather than whenever someone
  remembers to add the call.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.db.session import SessionLocal
from app.models import AuditLog

logger = logging.getLogger(__name__)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def record(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    target: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    """Append one audit row. The caller owns the commit."""
    entry = AuditLog(user_id=user_id, action=action, target=target, detail=detail)
    db.add(entry)
    return entry


class AuditMiddleware(BaseHTTPMiddleware):
    """Log every mutating request once its response is known.

    Runs after the route, so ``request.state.user_id`` - set by
    ``get_current_user`` - is populated for authenticated calls and absent for
    anonymous ones, which is itself worth recording.

    Uses its own session by default: the request's session is closed by the
    time the response comes back. Tests override
    ``app.state.audit_session_factory`` so the write joins the test's
    transaction instead of committing beside it.

    Failures here are logged and swallowed. An audit write must never be the
    reason an otherwise successful request turns into a 500 - but see the
    tests, which assert the write really happens, so "swallowed" cannot quietly
    become "never worked".
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        if request.method not in MUTATING_METHODS:
            return response

        session_factory = getattr(request.app.state, "audit_session_factory", None) or SessionLocal

        try:
            with session_factory() as session:
                record(
                    session,
                    action=f"{request.method} {request.url.path}",
                    user_id=getattr(request.state, "user_id", None),
                    target=request.url.path,
                    detail=f"status={response.status_code}",
                )
                session.commit()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to write audit entry for %s", request.url.path)

        return response
