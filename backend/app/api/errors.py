"""One error shape for the whole API.

Out of the box FastAPI answers an ``HTTPException`` with
``{"detail": "Student not found"}`` and a request validation failure with
``{"detail": [{"loc": [...], "msg": ..., "type": ...}, ...]}``. A client that
renders ``error.detail`` gets a sentence for one and ``[object Object]`` for
the other, so every frontend ends up writing the same type check.

The contract here: ``detail`` is *always* a human-readable sentence, and
field-level problems arrive beside it under ``errors`` so a form can highlight
the offending input rather than parse the sentence.

Status codes used across the CRUD routes:

``409`` a unique constraint the client could not have known about - a duplicate
admission number, a fee already assigned for that period.
``422`` the request is well-formed but the values are wrong, including ids that
reference nothing. Pydantic's own failures land here too, so "the amount is
negative" and "that class does not exist" reach the client the same way.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Constraint names as the database knows them, mapped to something a person can
# act on. Keyed on the name rather than the message text because Postgres
# wording varies between versions; the names are ours and are asserted by the
# schema tests.
CONFLICT_MESSAGES = {
    "ix_users_email": "An account with that email already exists.",
    "ix_students_admission_number": "A student with that admission number already exists.",
    "uq_fee_types_name": "A fee type with that name already exists.",
    "name_year": "That class already exists for that academic year.",
    "student_fee_period": "That fee is already assigned to this student for this period.",
}

# Sources FastAPI puts at the front of a validation error's location tuple.
_LOCATION_SOURCES = frozenset({"body", "query", "path", "header", "cookie"})


def unprocessable(field: str, message: str) -> HTTPException:
    """A 422 in the same shape Pydantic produces, for checks it cannot make.

    "class_id 7 does not exist" needs a database round trip, so it cannot be a
    Pydantic validator - but to the client it is the same kind of problem as a
    negative amount and should not arrive in a different envelope.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"{field}: {message}",
    )


def commit_or_conflict(db: Session) -> None:
    """Commit, translating a unique-constraint violation into a 409.

    Routes check for duplicates before inserting so the common case gets a
    precise message, but two admins can submit the same admission number in the
    same millisecond and both checks pass. The database is the only place that
    race can be settled, so the answer is caught here rather than pretended
    away with a pre-check alone.

    An integrity error whose constraint we do not recognise is re-raised. A
    blanket 409 would turn a genuine bug - a null in a NOT NULL column, a
    foreign key pointing at a deleted row - into a message telling the user to
    change their input, and it would never reach the logs.
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        message = CONFLICT_MESSAGES.get(constraint or "")
        if message is None:
            raise
        raise HTTPException(status.HTTP_409_CONFLICT, message) from exc


def _field_name(location: tuple[object, ...]) -> str:
    """Turn ``("body", "amount")`` into ``"amount"``, keeping nested paths."""
    parts = [str(part) for part in location]
    if parts and parts[0] in _LOCATION_SOURCES and len(parts) > 1:
        parts = parts[1:]
    return ".".join(parts) if parts else "request"


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": _field_name(error["loc"]), "message": error["msg"]} for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "; ".join(f"{e['field']}: {e['message']}" for e in errors)
            or "The request could not be validated.",
            "errors": errors,
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
