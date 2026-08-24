"""Shapes shared by every resource: money, short text, and paginated lists.

Money crosses the wire as a *string* - ``"250.00"``, not ``250.0``. A JSON
number becomes an IEEE 754 double the moment a browser parses it, which is the
same binary float the models refuse to store; sending two decimal places as
text hands the frontend an exact value and one obvious place to format it.
``Numeric(12, 2)`` in the database, ``Decimal`` in Python, string on the wire.

Request bodies accept either a number or a string - Pydantic parses both into
``Decimal`` - so a client that sends ``250.00`` unquoted is not punished for it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints

Money = Annotated[
    Decimal,
    # max_digits/decimal_places mirror NUMERIC(12, 2): a third decimal place is
    # rejected at the edge rather than silently rounded on the way in.
    Field(gt=0, max_digits=12, decimal_places=2, examples=["250.00"]),
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str),
]


def Name(max_length: int) -> type[str]:  # noqa: N802 - reads as a type, used as one
    """A required, trimmed, non-empty string.

    Trimming before the length check is the point: ``"   "`` is a name the
    database CHECK constraints reject, and catching it here turns a 500 into a
    422 that names the field.
    """
    return Annotated[  # type: ignore[return-value]
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


class Page[T](BaseModel):
    """One page of a list endpoint.

    ``total`` counts every row matching the filters, ignoring limit and offset,
    so a client can render "showing 1-50 of 214" without a second request.
    """

    items: list[T]
    total: int
    limit: int
    offset: int
