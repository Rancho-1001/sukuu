"""The database-level guarantees, tested against real Postgres.

These constraints are the last line of defence: they hold even if a bug, a
migration, or a hand-typed SQL statement bypasses the service layer entirely.
A constraint that is never exercised is indistinguishable from one that was
silently dropped, so each one gets a test that tries to violate it.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from app.models import (
    BillingPeriod,
    FeeAssignment,
    FeeType,
    Payment,
    PaymentMethod,
    SchoolClass,
    Student,
    User,
    UserRole,
)

pytestmark = pytest.mark.db


def unique(prefix: str) -> str:
    """A value no other test and no seed data can collide with.

    These tests must pass against a database that already holds rows - a
    developer who seeded their test database should not see failures that look
    like constraint bugs.
    """
    return f"{prefix}-{uuid4().hex[:10]}"


def make_fee_type(session, name=None, amount="500.00"):
    ft = FeeType(
        name=name or unique("Fee"),
        default_amount=Decimal(amount),
        billing_period=BillingPeriod.TERM,
    )
    session.add(ft)
    session.flush()
    return ft


def make_student(session, admission=None):
    student = Student(
        first_name="Ama", last_name="Mensah", admission_number=admission or unique("ADM")
    )
    session.add(student)
    session.flush()
    return student


def make_assignment(session, student=None, fee_type=None, amount="500.00", period="Term 1 2026"):
    fa = FeeAssignment(
        student=student or make_student(session),
        fee_type=fee_type or make_fee_type(session),
        amount=Decimal(amount),
        period_label=period,
    )
    session.add(fa)
    session.flush()
    return fa


class TestMoneyIsExact:
    def test_amount_round_trips_as_decimal_not_float(self, db_session):
        fa = make_assignment(db_session, amount="1234.56")
        db_session.expire(fa)
        assert isinstance(fa.amount, Decimal)
        assert fa.amount == Decimal("1234.56")

    def test_more_than_two_decimal_places_is_rounded_by_the_column(self, db_session):
        fa = make_assignment(db_session, amount="10.999")
        db_session.expire(fa)
        assert fa.amount == Decimal("11.00")

    def test_amount_beyond_precision_is_rejected(self, db_session):
        with pytest.raises(DataError):
            make_assignment(db_session, amount="12345678901.00")


class TestPositiveAmounts:
    def test_zero_fee_assignment_is_rejected(self, db_session):
        with pytest.raises(IntegrityError, match="amount_positive"):
            make_assignment(db_session, amount="0.00")

    def test_negative_fee_assignment_is_rejected(self, db_session):
        with pytest.raises(IntegrityError, match="amount_positive"):
            make_assignment(db_session, amount="-5.00")

    def test_zero_payment_is_rejected(self, db_session):
        fa = make_assignment(db_session)
        db_session.add(
            Payment(fee_assignment=fa, amount_paid=Decimal("0.00"), method=PaymentMethod.CASH)
        )
        with pytest.raises(IntegrityError, match="amount_paid_positive"):
            db_session.flush()

    def test_zero_default_fee_amount_is_rejected(self, db_session):
        with pytest.raises(IntegrityError, match="default_amount_positive"):
            make_fee_type(db_session, amount="0.00")


class TestUniqueness:
    def test_admission_number_must_be_unique(self, db_session):
        dup = unique("ADM")
        make_student(db_session, admission=dup)
        with pytest.raises(IntegrityError, match="admission_number"):
            make_student(db_session, admission=dup)

    def test_email_must_be_unique(self, db_session):
        shared_email = unique("dup") + "@example.com"
        for _ in range(2):
            db_session.add(
                User(
                    email=shared_email,
                    password_hash="x",
                    name="Dup",
                    role=UserRole.PARENT,
                )
            )
        with pytest.raises(IntegrityError, match="email"):
            db_session.flush()

    def test_same_fee_cannot_be_charged_twice_for_one_period(self, db_session):
        student = make_student(db_session, admission=unique("ADM"))
        fee_type = make_fee_type(db_session)
        make_assignment(db_session, student=student, fee_type=fee_type, period="Term 1 2026")
        with pytest.raises(IntegrityError, match="student_fee_period"):
            make_assignment(db_session, student=student, fee_type=fee_type, period="Term 1 2026")

    def test_the_same_fee_in_a_different_period_is_fine(self, db_session):
        student = make_student(db_session, admission=unique("ADM"))
        fee_type = make_fee_type(db_session)
        make_assignment(db_session, student=student, fee_type=fee_type, period="Term 1 2026")
        make_assignment(db_session, student=student, fee_type=fee_type, period="Term 2 2026")

    def test_a_stripe_event_can_only_be_recorded_once(self, db_session):
        """The guarantee that makes a replayed webhook a no-op."""
        fa = make_assignment(db_session)
        shared_event = unique("evt")
        for _ in range(2):
            db_session.add(
                Payment(
                    fee_assignment=fa,
                    amount_paid=Decimal("10.00"),
                    method=PaymentMethod.STRIPE,
                    stripe_payment_intent_id="pi_123",
                    stripe_event_id=shared_event,
                )
            )
        with pytest.raises(IntegrityError, match="stripe_event_id"):
            db_session.flush()

    def test_many_cash_payments_may_have_no_event_id(self, db_session):
        """NULLs are distinct in Postgres, so the unique index must not block cash."""
        fa = make_assignment(db_session)
        for _ in range(3):
            db_session.add(
                Payment(fee_assignment=fa, amount_paid=Decimal("1.00"), method=PaymentMethod.CASH)
            )
        db_session.flush()


class TestMethodAndStripeIdsAgree:
    def test_cash_payment_carrying_a_stripe_id_is_rejected(self, db_session):
        fa = make_assignment(db_session)
        db_session.add(
            Payment(
                fee_assignment=fa,
                amount_paid=Decimal("10.00"),
                method=PaymentMethod.CASH,
                stripe_payment_intent_id="pi_should_not_be_here",
            )
        )
        with pytest.raises(IntegrityError, match="stripe_ids_match_method"):
            db_session.flush()

    def test_stripe_payment_without_an_intent_id_is_rejected(self, db_session):
        fa = make_assignment(db_session)
        db_session.add(
            Payment(fee_assignment=fa, amount_paid=Decimal("10.00"), method=PaymentMethod.STRIPE)
        )
        with pytest.raises(IntegrityError, match="stripe_ids_match_method"):
            db_session.flush()


class TestReferentialIntegrity:
    def test_a_class_with_students_cannot_be_deleted(self, db_session):
        """The FK is ON DELETE RESTRICT, so the database refuses the delete.

        Issued as raw SQL on purpose. ``session.delete()`` would set the
        student's class_id to NULL first and the delete would succeed, so going
        through the ORM would test SQLAlchemy's cascade behaviour rather than
        the constraint this test exists to prove.
        """
        school_class = SchoolClass(name=unique("Grade"), academic_year="2026")
        db_session.add(school_class)
        db_session.flush()
        student = make_student(db_session, admission=unique("ADM"))
        student.school_class = school_class
        db_session.flush()

        with pytest.raises(IntegrityError, match="students"):
            db_session.execute(
                text("DELETE FROM classes WHERE id = :cid"), {"cid": school_class.id}
            )

    def test_blank_student_name_is_rejected(self, db_session):
        db_session.add(
            Student(first_name="   ", last_name="Mensah", admission_number=unique("ADM"))
        )
        with pytest.raises(IntegrityError, match="first_name_not_blank"):
            db_session.flush()
