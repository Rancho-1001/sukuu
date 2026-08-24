"""The admin dashboard's numbers, in one request.

Everything here could be assembled by the client from endpoints that already
exist - list the classes, then ask each one for its balance. That is an N+1
moved into the browser: four classes on a demo, sixty on a real school roll,
and the page gets slower the more there is to show. One query answers it
instead.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_staff
from app.models import SchoolClass
from app.schemas.classes import ClassSummary
from app.schemas.payments import ClassCollectionRow, SchoolSummaryOut
from app.services import ledger
from app.services.balances import outstanding, to_money

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/summary", response_model=SchoolSummaryOut, dependencies=[Depends(require_staff)])
def read_school_summary(db: DbSession) -> SchoolSummaryOut:
    """Collected and outstanding across the school, with a per-class breakdown.

    The class rows will not always sum to the school totals, and that is
    deliberate rather than a rounding bug: a student who has been enrolled but
    not yet placed in a class is billed like anyone else and belongs in the
    school figure, while having no class row to appear in. The gap is the
    admin's cue that somebody needs placing.
    """
    billed, paid = ledger.totals_where(db)

    # Newest year first, then by name - the same order as the classes list, so
    # the dashboard and the page it links to do not disagree about position.
    rows = db.execute(
        ledger.class_balances().order_by(SchoolClass.academic_year.desc(), SchoolClass.name)
    ).all()

    return SchoolSummaryOut(
        billed=to_money(billed),
        paid=to_money(paid),
        outstanding=outstanding(billed, [paid]),
        classes=[
            ClassCollectionRow(
                school_class=ClassSummary.model_validate(school_class),
                billed=to_money(class_billed),
                paid=to_money(class_paid),
                outstanding=outstanding(class_billed, [class_paid]),
            )
            for school_class, class_billed, class_paid in rows
        ],
    )
