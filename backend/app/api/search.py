"""Text filters for the list endpoints.

One function, but it earns a module: getting LIKE escaping wrong is quiet.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute


def contains(column: InstrumentedAttribute, term: str) -> ColumnElement[bool]:
    """Case-insensitive "contains" over ``column``.

    ``%`` and ``_`` are wildcards inside a LIKE pattern, so a search for
    ``"5_B"`` would quietly match ``"5xB"`` and a search for ``"%"`` would
    match everything. Escaping them means the search box searches for what was
    typed. This is a correctness problem rather than an injection one - the
    term is still a bound parameter - but a search that matches the wrong rows
    is not obviously broken, which is what makes it worth handling here rather
    than at each call site.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")
