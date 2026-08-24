"""Users, classes, and students."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, TimestampMixin
from app.models.enums import StudentStatus, UserRole

if TYPE_CHECKING:
    from app.models.fees import FeeAssignment


def _pg_enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(Base, TimestampMixin):
    """An account.

    Emails are stored lower-cased. Without that, a user created as
    "Ama@example.com" could never log in - the login lookup lower-cases what
    the user typed, so neither spelling would match the stored value - and
    "ama@example.com" could be registered a second time, because a plain unique
    constraint is case-sensitive. The validator normalises on write and the
    CHECK constraint means a raw INSERT cannot bypass it.
    """

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_is_lowercase"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(_pg_enum(UserRole, "user_role"), nullable=False)

    children: Mapped[list[Student]] = relationship(
        back_populates="parent", foreign_keys="Student.parent_id"
    )

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return value.strip().lower() if value else value

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} {self.role.value}>"


class SchoolClass(Base, TimestampMixin):
    """A class group, e.g. "Grade 5B" for a given academic year.

    Named SchoolClass because ``class`` is a Python keyword; the table stays
    ``classes`` as in the spec.

    Classes are archived, never deleted. A class that has held students is
    referenced by their records for as long as those records exist, and the
    foreign key is RESTRICT precisely so a delete cannot take the history with
    it. ``archived_at`` is what "Grade 5B, 2025" looks like once the year ends:
    out of the pickers, still attached to everyone who was in it.
    """

    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("name", "academic_year", name="name_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    students: Mapped[list[Student]] = relationship(back_populates="school_class")

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __repr__(self) -> str:
        return f"<SchoolClass {self.id} {self.name} {self.academic_year}>"


class Student(Base, TimestampMixin):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("length(trim(first_name)) > 0", name="first_name_not_blank"),
        CheckConstraint("length(trim(last_name)) > 0", name="last_name_not_blank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    admission_number: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True
    )
    status: Mapped[StudentStatus] = mapped_column(
        _pg_enum(StudentStatus, "student_status"),
        nullable=False,
        default=StudentStatus.ACTIVE,
        server_default=StudentStatus.ACTIVE.value,
    )

    # RESTRICT rather than CASCADE: deleting a class or a parent must never
    # silently take student and payment records with it.
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    school_class: Mapped[SchoolClass | None] = relationship(back_populates="students")
    parent: Mapped[User | None] = relationship(back_populates="children", foreign_keys=[parent_id])
    fee_assignments: Mapped[list[FeeAssignment]] = relationship(back_populates="student")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Student {self.id} {self.admission_number} {self.full_name}>"
