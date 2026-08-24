"""The overpayment rule under concurrency.

:mod:`app.services.balances` proves the arithmetic, but it cannot prove the
rule holds when two payments race - that depends on the database taking a row
lock. This is the test for that, and it needs real Postgres: SQLite has no
``SELECT ... FOR UPDATE``, so substituting it here would make the test pass
while proving nothing.

Two things make this test different from every other one in the suite, and
both are the point rather than an inconvenience:

* it uses two independent connections. The ``db_session`` fixture wraps a test
  in a transaction nobody else can see, and two transactions that cannot see
  the row cannot contend for it. A version of this test that runs both
  payments through one session passes whether or not the lock exists, because
  a single session serialises itself;
* its fixture data is committed, for the same reason, and is deleted
  afterwards rather than rolled back.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    BillingPeriod,
    FeeAssignment,
    FeeType,
    Payment,
    PaymentMethod,
    SchoolClass,
    Student,
)
from app.services.balances import OverpaymentError
from app.services.payments import record_payment

pytestmark = pytest.mark.db

FEE = Decimal("100.00")
HALF_PLUS = Decimal("60.00")


@pytest.fixture
def committed_assignment(engine):
    """A 100.00 fee assignment every connection can see.

    Committed on purpose: the rest of the suite rolls back, but a row inside an
    uncommitted transaction is invisible to the second connection, and this
    test is entirely about what two connections do to one row.
    """
    session = Session(bind=engine, future=True)
    tag = uuid4().hex[:10]

    school_class = SchoolClass(name=f"Concurrency {tag}", academic_year=f"YR{tag}")
    student = Student(
        first_name="Ama",
        last_name="Mensah",
        admission_number=f"CONC{tag}",
        school_class=school_class,
    )
    fee_type = FeeType(
        name=f"Concurrency fee {tag}", default_amount=FEE, billing_period=BillingPeriod.TERM
    )
    assignment = FeeAssignment(
        student=student, fee_type=fee_type, amount=FEE, period_label=f"Term {tag}"
    )
    session.add(assignment)
    session.commit()
    assignment_id = assignment.id
    ids = (assignment.id, student.id, fee_type.id, school_class.id)

    try:
        yield assignment_id
    finally:
        session.rollback()
        session.execute(delete(Payment).where(Payment.fee_assignment_id == ids[0]))
        session.execute(delete(FeeAssignment).where(FeeAssignment.id == ids[0]))
        session.execute(delete(Student).where(Student.id == ids[1]))
        session.execute(delete(FeeType).where(FeeType.id == ids[2]))
        session.execute(delete(SchoolClass).where(SchoolClass.id == ids[3]))
        session.commit()
        session.close()


def total_paid(engine, assignment_id: int) -> Decimal:
    with Session(bind=engine, future=True) as session:
        return session.scalar(
            select(func.coalesce(func.sum(Payment.amount_paid), 0)).where(
                Payment.fee_assignment_id == assignment_id
            )
        )


def test_concurrent_payments_cannot_overpay(engine, committed_assignment):
    """Two connections pay 60.00 against a 100.00 fee. Exactly one may win.

    Without the row lock both transactions read the same empty payment list,
    both conclude there is room for 60.00, and the fee collects 120.00. The
    total at the end is what proves the lock is doing its job; the liveness
    check in the middle is what says *why* when it is not.
    """
    outcome: dict[str, object] = {}
    second_finished = threading.Event()

    def pay_from_a_second_connection() -> None:
        session = Session(bind=engine, future=True)
        try:
            record_payment(
                session,
                fee_assignment_id=committed_assignment,
                amount=HALF_PLUS,
                method=PaymentMethod.CASH,
            )
            session.commit()
            outcome["result"] = "accepted"
        except OverpaymentError as exc:
            session.rollback()
            outcome["result"] = "rejected"
            outcome["message"] = str(exc)
        except Exception as exc:  # pragma: no cover - surfaces as a test failure
            session.rollback()
            outcome["result"] = f"error: {exc!r}"
        finally:
            session.close()
            second_finished.set()

    first = Session(bind=engine, future=True)
    try:
        record_payment(
            first,
            fee_assignment_id=committed_assignment,
            amount=HALF_PLUS,
            method=PaymentMethod.CASH,
        )
        # The row lock is now held and uncommitted.

        second = threading.Thread(target=pay_from_a_second_connection, daemon=True)
        second.start()

        # Still running after a second means it is waiting on the lock. Without
        # FOR UPDATE this insert takes milliseconds and the flag is already set.
        assert not second_finished.wait(timeout=1.0), (
            "the second payment did not block - the fee assignment row is not locked"
        )

        first.commit()
    finally:
        first.close()

    assert second_finished.wait(timeout=15), "the second payment never finished"
    second.join(timeout=5)

    assert outcome["result"] == "rejected", outcome
    assert "40.00" in outcome["message"], "the refusal should name what was actually left"
    assert total_paid(engine, committed_assignment) == HALF_PLUS


def test_the_loser_leaves_no_row_behind(engine, committed_assignment):
    """A rejected payment must not be a payment. Obvious, and worth pinning:
    the insert happens before the commit that would have made it real."""
    first = Session(bind=engine, future=True)
    try:
        record_payment(
            first,
            fee_assignment_id=committed_assignment,
            amount=FEE,
            method=PaymentMethod.CASH,
        )
        first.commit()
    finally:
        first.close()

    second = Session(bind=engine, future=True)
    try:
        with pytest.raises(OverpaymentError):
            record_payment(
                second,
                fee_assignment_id=committed_assignment,
                amount=Decimal("1.00"),
                method=PaymentMethod.CASH,
            )
        second.rollback()
    finally:
        second.close()

    with Session(bind=engine, future=True) as session:
        rows = session.scalars(
            select(Payment).where(Payment.fee_assignment_id == committed_assignment)
        ).all()
    assert len(rows) == 1
    assert total_paid(engine, committed_assignment) == FEE


def test_sequential_installments_settle_exactly(engine, committed_assignment):
    """The same service, used the way it will normally be used: four payments
    that add up, the last one exact, and nothing left owing."""
    for part in ("25.00", "25.00", "25.00", "25.00"):
        with Session(bind=engine, future=True) as session:
            record_payment(
                session,
                fee_assignment_id=committed_assignment,
                amount=Decimal(part),
                method=PaymentMethod.CASH,
            )
            session.commit()

    assert total_paid(engine, committed_assignment) == FEE

    with Session(bind=engine, future=True) as session:
        with pytest.raises(OverpaymentError):
            record_payment(
                session,
                fee_assignment_id=committed_assignment,
                amount=Decimal("0.01"),
                method=PaymentMethod.CASH,
            )
        session.rollback()
