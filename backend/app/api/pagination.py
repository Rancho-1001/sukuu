"""Limit/offset paging for the list endpoints.

Offset paging, not cursors. At the size of a single school - hundreds of
students, not millions - the deep-offset cost that motivates cursors never
arrives, and offsets let the admin UI jump to a page number, which cursors
cannot. Worth revisiting only if a list ever spans more than a few thousand
rows.

``limit`` is capped rather than unbounded: without a ceiling, one client asking
for ``?limit=1000000`` decides how much memory the server spends.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PageParams = Annotated[Pagination, Depends(pagination)]


def count_of(db: Session, stmt: Select) -> int:
    """How many rows ``stmt`` would return without its limit and offset.

    Wrapping the statement in a subquery rather than swapping the columns for
    ``count(*)`` keeps GROUP BY and DISTINCT honest - a per-class student count
    returns one row per class, and that is the number to report.

    ``order_by(None)`` because sorting a set you are only counting is work
    Postgres does not need to do, and an ORDER BY over a column the outer query
    does not select is an error on some backends.
    """
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
