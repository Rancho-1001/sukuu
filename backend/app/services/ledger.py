"""Balance queries: the money rules of :mod:`app.services.balances`, applied
to rows instead of lists.

``balances.py`` stays pure - no ORM, no session - because that is what makes
the financial rules cheap to test exhaustively. This module is where those
rules meet SQL, and it is separate for one reason: aggregating money across
two joins is easy to get wrong in a way that looks right.

**The fan-out.** The obvious way to total what a student has been billed and
has paid is to join students to assignments to payments and sum both columns::

    SELECT sum(fee_assignments.amount), sum(payments.amount_paid)
    FROM students
    LEFT JOIN fee_assignments ON ...
    LEFT JOIN payments ON ...

That is wrong, and quietly. The join produces one row per *payment*, so an
assignment for 250.00 settled in three installments contributes its 250.00
three times: the student appears to owe 750.00 and to have paid 250.00. With
one payment per fee - which is what a hand-check usually looks like - the
numbers agree perfectly. It breaks only for the students who paid in
installments, which is the feature the product is built around.

The fix is to collapse the payments to one row per assignment *first*, in a
subquery, and join that. Every function here builds on ``_paid_per_assignment``
for exactly that reason.

**Outstanding is not computed here.** SQL supplies ``amount`` and how much has
been paid; the subtraction, and the rule that a balance never reads negative,
stay in ``balances.outstanding`` so there is one definition rather than one in
Python and a second in SQL that drift apart. The only exception is the
``outstanding`` *filter* on the assignment list, which asks whether anything is
left rather than how much - see :func:`only_outstanding`.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ColumnElement, Select, Subquery, func, select
from sqlalchemy.orm import Session

from app.models import FeeAssignment, Payment, SchoolClass, Student


def _paid_per_assignment() -> Subquery:
    """One row per fee assignment, holding everything paid against it.

    This collapse is what keeps the joins above it from multiplying money.
    """
    return (
        select(
            Payment.fee_assignment_id.label("fee_assignment_id"),
            func.sum(Payment.amount_paid).label("paid"),
        )
        .group_by(Payment.fee_assignment_id)
        .subquery("paid_per_assignment")
    )


def assignments_with_paid() -> Select:
    """Fee assignments, each with the total paid against it.

    No GROUP BY on the outer query: the subquery is already one row per
    assignment, so this composes with further joins and filters without
    changing what the aggregate means.
    """
    paid = _paid_per_assignment()
    return select(
        FeeAssignment,
        func.coalesce(paid.c.paid, 0).label("amount_paid"),
    ).outerjoin(paid, paid.c.fee_assignment_id == FeeAssignment.id)


def only_outstanding(stmt: Select) -> Select:
    """Narrow an :func:`assignments_with_paid` query to fees still owed.

    A correlated subquery rather than a HAVING over the joined aggregate: it
    keeps this filter independent of how the caller built the rest of the
    statement, which is what lets it be applied or not without changing the
    shape of the result.
    """
    return stmt.where(
        FeeAssignment.amount
        > select(func.coalesce(func.sum(Payment.amount_paid), 0))
        .where(Payment.fee_assignment_id == FeeAssignment.id)
        .scalar_subquery()
    )


def student_balances() -> Select:
    """Students, each with what they have been billed and what they have paid.

    Both sums are over one row per assignment, so installments do not inflate
    the billed figure. See the module docstring.
    """
    paid = _paid_per_assignment()
    return (
        select(
            Student,
            func.coalesce(func.sum(FeeAssignment.amount), 0).label("billed"),
            func.coalesce(func.sum(paid.c.paid), 0).label("paid"),
        )
        .outerjoin(FeeAssignment, FeeAssignment.student_id == Student.id)
        .outerjoin(paid, paid.c.fee_assignment_id == FeeAssignment.id)
        .group_by(Student.id)
    )


def class_balances() -> Select:
    """Every class with what its students have been billed and have paid.

    Three joins deep - class to student to assignment to payments - and the
    payments are still collapsed first, so a student paying in installments
    inflates neither their class's billed figure nor the school's.
    """
    paid = _paid_per_assignment()
    return (
        select(
            SchoolClass,
            func.coalesce(func.sum(FeeAssignment.amount), 0).label("billed"),
            func.coalesce(func.sum(paid.c.paid), 0).label("paid"),
        )
        .outerjoin(Student, Student.class_id == SchoolClass.id)
        .outerjoin(FeeAssignment, FeeAssignment.student_id == Student.id)
        .outerjoin(paid, paid.c.fee_assignment_id == FeeAssignment.id)
        .group_by(SchoolClass.id)
    )


def totals_where(db: Session, *conditions: ColumnElement[bool]) -> tuple[Decimal, Decimal]:
    """Billed and paid across every student matching ``conditions``.

    Deliberately a separate query from the paginated rows beside it: a total
    that covers only the current page is not a total, and is the kind of wrong
    number a dashboard reports with complete confidence.
    """
    # Bound once. Calling _paid_per_assignment() again would build a second,
    # separately-aliased subquery, and the SELECT would then be reading a
    # different one from the JOIN.
    paid = _paid_per_assignment()
    billed_total, paid_total = db.execute(
        select(
            func.coalesce(func.sum(FeeAssignment.amount), 0),
            func.coalesce(func.sum(paid.c.paid), 0),
        )
        .select_from(Student)
        .outerjoin(FeeAssignment, FeeAssignment.student_id == Student.id)
        .outerjoin(paid, paid.c.fee_assignment_id == FeeAssignment.id)
        .where(*conditions)
    ).one()
    return Decimal(billed_total), Decimal(paid_total)
