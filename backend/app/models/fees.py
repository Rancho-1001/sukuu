"""Fee types, fee assignments, and payments.

Money is ``Numeric(12, 2)`` everywhere and maps to :class:`~decimal.Decimal`
in Python. Never Float: the overpayment rule is a comparison against a SUM,
and binary rounding error in that comparison is a real bug, not a rounding
nicety.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import BillingPeriod, PaymentMethod

if TYPE_CHECKING:
    from app.models.school import Student, User

MONEY = Numeric(12, 2)


def _pg_enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class FeeType(Base, TimestampMixin):
    """A kind of fee the school charges - tuition, feeding, uniform."""

    __tablename__ = "fee_types"
    __table_args__ = (CheckConstraint("default_amount > 0", name="default_amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    billing_period: Mapped[BillingPeriod] = mapped_column(
        _pg_enum(BillingPeriod, "billing_period"), nullable=False
    )

    def __repr__(self) -> str:
        return f"<FeeType {self.id} {self.name} {self.default_amount}>"


class FeeAssignment(Base, TimestampMixin):
    """ "This student owes this much for this fee, this period" - the heart of the app."""

    __tablename__ = "fee_assignments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        # The same fee cannot be charged to the same student twice in one period.
        UniqueConstraint("student_id", "fee_type_id", "period_label", name="student_fee_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fee_type_id: Mapped[int] = mapped_column(
        ForeignKey("fee_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)

    student: Mapped[Student] = relationship(back_populates="fee_assignments")
    fee_type: Mapped[FeeType] = relationship()
    payments: Mapped[list[Payment]] = relationship(
        back_populates="fee_assignment", order_by="Payment.paid_at"
    )

    def __repr__(self) -> str:
        return f"<FeeAssignment {self.id} student={self.student_id} {self.amount}>"


class Payment(Base, TimestampMixin):
    """One payment against one fee assignment.

    Many payments may point at a single assignment - that is what makes
    installments possible. The rule that they may not sum past the amount owed
    lives in the payment service, which locks the assignment row first;
    a CHECK constraint cannot see other rows.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_paid > 0", name="amount_paid_positive"),
        # Stripe retries webhooks. Recording the event id under a unique index
        # is what makes a replayed delivery a no-op instead of a double credit.
        UniqueConstraint("stripe_event_id", name="stripe_event_id"),
        CheckConstraint(
            "(method = 'stripe' AND stripe_payment_intent_id IS NOT NULL)"
            " OR (method = 'cash' AND stripe_payment_intent_id IS NULL)",
            name="stripe_ids_match_method",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fee_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("fee_assignments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        _pg_enum(PaymentMethod, "payment_method"), nullable=False
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Nullable because a Stripe payment is recorded by the webhook, not a person.
    recorded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    fee_assignment: Mapped[FeeAssignment] = relationship(back_populates="payments")
    recorded_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<Payment {self.id} {self.amount_paid} {self.method.value}>"


class AuditLog(Base):
    """Append-only record of who did what.

    No TimestampMixin: an audit row is never updated, so an updated_at column
    would be a lie.

    ``user_id`` is ON DELETE SET NULL, unlike every other foreign key here.
    The log must never be the reason an account cannot be removed, and an entry
    that has lost its actor still records that the action happened. Contrast
    ``payments.recorded_by_id``, which stays RESTRICT: who accepted a cash
    payment is accountability data and may not be erased.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    user: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} {self.action} by={self.user_id}>"
