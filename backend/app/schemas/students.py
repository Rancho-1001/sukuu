"""Request and response shapes for students."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import StudentStatus
from app.schemas.classes import ClassSummary
from app.schemas.common import Name


class ParentSummary(BaseModel):
    """The parent as they appear on a student record.

    Enough to call someone about an unpaid fee, and nothing more: no role, no
    timestamps, and - the reason this is a separate model from the ORM one - no
    password hash.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr


class StudentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Name(80)
    last_name: Name(80)
    admission_number: Name(40)
    class_id: int | None = None
    parent_id: int | None = None
    status: StudentStatus = StudentStatus.ACTIVE


class StudentUpdate(BaseModel):
    """A PATCH body, and the endpoint that moves a student between classes.

    ``class_id`` and ``parent_id`` are nullable *and* optional, which are two
    different things here: omitting the field leaves the current value alone,
    while sending ``null`` detaches the student. The route reads
    ``exclude_unset`` rather than ``exclude_none`` so the two stay distinct.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: Name(80) | None = None
    last_name: Name(80) | None = None
    admission_number: Name(40) | None = None
    class_id: int | None = None
    parent_id: int | None = None
    status: StudentStatus | None = None


class StudentSummary(BaseModel):
    """A student as they appear nested inside a fee assignment."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    admission_number: str


class StudentOut(StudentSummary):
    first_name: str
    last_name: str
    status: StudentStatus
    school_class: ClassSummary | None = None
    parent: ParentSummary | None = None
