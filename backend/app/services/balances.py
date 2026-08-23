"""Money arithmetic for fee assignments.

Pure functions, no database. Keeping this layer free of the ORM is what makes
the financial rules cheap to test exhaustively.

Two rules the rest of the app depends on:

* Money is exact. Amounts move through :class:`~decimal.Decimal` quantized to
  two places; floats are converted via ``str`` so binary rounding error never
  enters the ledger.
* A fee assignment can never be overpaid. :func:`validate_payment` is the only
  sanctioned way to admit a new payment.

Callers writing to the database must hold a row lock on the fee assignment
(``SELECT ... FOR UPDATE``) across the read of existing payments and the insert
of the new one. These functions cannot enforce that on their own: two
concurrent callers reading the same pre-payment state would each be told their
payment is fine.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


class PaymentError(ValueError):
    """A payment was rejected. Base class for the specific reasons below."""


class NonPositivePaymentError(PaymentError):
    """A payment was zero or negative."""


class OverpaymentError(PaymentError):
    """A payment would push the total paid above the amount owed."""


class AlreadySettledError(OverpaymentError):
    """A payment was attempted against a fee assignment with nothing left owing."""


def to_money(value: Decimal | int | str) -> Decimal:
    """Normalise ``value`` to a two-place Decimal.

    Floats are routed through ``str`` so that ``0.1 + 0.2`` becomes ``0.30``
    rather than ``0.3000000000000000444...``.
    """
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def total_paid(payments: Iterable[Decimal | int | str]) -> Decimal:
    """Sum of ``payments``, or 0.00 when there are none."""
    return sum((to_money(p) for p in payments), ZERO)


def outstanding(amount: Decimal | int | str, payments: Iterable[Decimal | int | str]) -> Decimal:
    """What is still owed on a fee assignment.

    Never returns a negative number: a ledger that somehow holds an overpayment
    reads as settled rather than as a credit. Refunds are explicitly out of
    scope for v1.
    """
    remaining = to_money(amount) - total_paid(payments)
    return max(remaining, ZERO)


def is_settled(amount: Decimal | int | str, payments: Iterable[Decimal | int | str]) -> bool:
    """True when nothing is left owing."""
    return outstanding(amount, payments) == ZERO


def validate_payment(
    amount: Decimal | int | str,
    payments: Iterable[Decimal | int | str],
    new_payment: Decimal | int | str,
) -> Decimal:
    """Check that ``new_payment`` may be recorded, and return it normalised.

    Raises :class:`NonPositivePaymentError` for a zero or negative payment,
    :class:`AlreadySettledError` when nothing is owed, and
    :class:`OverpaymentError` when the payment exceeds what remains.
    """
    payment = to_money(new_payment)
    if payment <= ZERO:
        raise NonPositivePaymentError(f"Payment must be positive, got {payment}.")

    remaining = outstanding(amount, payments)
    if remaining == ZERO:
        raise AlreadySettledError("This fee has already been paid in full.")
    if payment > remaining:
        raise OverpaymentError(f"Payment of {payment} exceeds the {remaining} still owed.")

    return payment
