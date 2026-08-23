"""The overpayment rule under concurrency.

:mod:`app.services.balances` proves the arithmetic, but it cannot prove the
rule holds when two payments race — that depends on the database taking a row
lock. This is the test for that, and it needs real Postgres: SQLite has no
``SELECT ... FOR UPDATE``, so substituting it here would make the test pass
while proving nothing.

The module skips itself until the payment service exists, then starts running
on its own. Nothing needs to be un-skipped by hand.
"""

import pytest

pytest.importorskip(
    "app.services.payments",
    reason="app.services.payments not built yet — see the week 2 build order",
)

pytestmark = pytest.mark.db


@pytest.mark.xfail(reason="Test body is a template; fill in once the models land.", strict=False)
def test_concurrent_payments_cannot_overpay(engine, db_session):
    """Two sessions paying the same fee at once: exactly one must be rejected.

    Sketch of the shape this needs to take:

    1. Create a fee assignment for 100.00 with no payments.
    2. Open a second database connection (a separate transaction, not a nested
       one — the whole point is two independent lockers).
    3. In both, call the payment service for 60.00 without committing.
    4. The second call must block on the row lock, then fail with
       ``OverpaymentError`` once the first commits.
    5. Assert the assignment's total paid is 60.00, not 120.00.

    A version that passes without step 2 is not testing anything: a single
    session serialises itself.
    """
    raise NotImplementedError
