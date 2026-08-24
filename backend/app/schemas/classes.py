"""Request and response shapes for classes.

Separate from the SQLAlchemy models on purpose. A model that doubles as a
response schema leaks whatever column is added to it next - and the day
``users`` grew ``password_hash``, that would have been the API's problem.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Name


class ClassCreate(BaseModel):
    # extra="forbid" so a typo'd field is a 422 rather than a silent no-op. A
    # client that sends {"nmae": "Grade 5B"} should be told, not ignored.
    model_config = ConfigDict(extra="forbid")

    name: Name(60)
    academic_year: Name(20)


class ClassUpdate(BaseModel):
    """A PATCH body. Every field optional; omitted means "leave it alone"."""

    model_config = ConfigDict(extra="forbid")

    name: Name(60) | None = None
    academic_year: Name(20) | None = None


class ClassSummary(BaseModel):
    """A class as it appears nested inside another resource."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    academic_year: str


class ClassOut(ClassSummary):
    archived_at: datetime | None = None
    # Active students only: a withdrawn student still belongs to the class
    # historically, but a roll that counts them reads as wrong to the person
    # standing in front of the room.
    active_student_count: int = 0
