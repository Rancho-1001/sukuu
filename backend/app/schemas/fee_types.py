"""Request and response shapes for fee types."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.models.enums import BillingPeriod
from app.schemas.common import Money, Name


def _blank_is_absent(value: str | None) -> str | None:
    """An empty description is no description.

    Otherwise a form that submits its untouched field stores ``""``, and every
    consumer downstream has to treat "" and null as the same thing forever.
    """
    return value or None


Description = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None,
    AfterValidator(_blank_is_absent),
]


class FeeTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(80)
    description: Description = None
    default_amount: Money
    billing_period: BillingPeriod


class FeeTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(80) | None = None
    description: Description = None
    default_amount: Money | None = None
    billing_period: BillingPeriod | None = None


class FeeTypeSummary(BaseModel):
    """A fee type as it appears nested inside a fee assignment."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    billing_period: BillingPeriod


class FeeTypeOut(FeeTypeSummary):
    description: str | None = None
    default_amount: Money
