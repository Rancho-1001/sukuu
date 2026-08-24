"""Fee types: create, list, update.

The catalogue of what a school charges for - tuition, feeding, uniform - with
a default amount and how often it recurs.

No delete. A fee type that has ever been assigned is referenced by every
assignment and every payment underneath it, and the foreign key is RESTRICT
so the database would refuse anyway. A fee the school has stopped charging is
a fee nobody assigns any more; removing it would rewrite what parents were
billed last term.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession, require_admin, require_staff
from app.api.errors import commit_or_conflict
from app.api.pagination import PageParams, count_of
from app.api.search import contains
from app.models import FeeType
from app.models.enums import BillingPeriod
from app.schemas.common import Page
from app.schemas.fee_types import FeeTypeCreate, FeeTypeOut, FeeTypeUpdate

router = APIRouter(prefix="/fee-types", tags=["fee types"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Fee type not found")


def _load(db: DbSession, fee_type_id: int) -> FeeType:
    fee_type = db.get(FeeType, fee_type_id)
    if fee_type is None:
        raise NOT_FOUND
    return fee_type


@router.post(
    "",
    response_model=FeeTypeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_fee_type(payload: FeeTypeCreate, db: DbSession) -> FeeType:
    fee_type = FeeType(**payload.model_dump())
    db.add(fee_type)
    commit_or_conflict(db)
    return fee_type


@router.get("", response_model=Page[FeeTypeOut], dependencies=[Depends(require_staff)])
def list_fee_types(
    db: DbSession,
    page: PageParams,
    billing_period: Annotated[BillingPeriod | None, Query()] = None,
    q: Annotated[str | None, Query(description="Case-insensitive match on the name")] = None,
) -> Page[FeeTypeOut]:
    stmt = select(FeeType)
    if billing_period:
        stmt = stmt.where(FeeType.billing_period == billing_period)
    if q:
        stmt = stmt.where(contains(FeeType.name, q))
    stmt = stmt.order_by(FeeType.name)

    total = count_of(db, stmt)
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[FeeTypeOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{fee_type_id}", response_model=FeeTypeOut, dependencies=[Depends(require_staff)])
def read_fee_type(fee_type_id: int, db: DbSession) -> FeeType:
    return _load(db, fee_type_id)


@router.patch("/{fee_type_id}", response_model=FeeTypeOut, dependencies=[Depends(require_admin)])
def update_fee_type(fee_type_id: int, payload: FeeTypeUpdate, db: DbSession) -> FeeType:
    """Edit the catalogue entry.

    Changing ``default_amount`` deliberately does not touch fees already
    assigned. An assignment stores its own amount because that is what a
    particular student was actually billed; rewriting it would change what a
    parent owes - possibly to less than they have already paid - as a
    side-effect of editing a price list.
    """
    fee_type = _load(db, fee_type_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(fee_type, field, value)
    commit_or_conflict(db)
    return fee_type
