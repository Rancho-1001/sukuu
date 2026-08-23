"""Tests for the money rules in :mod:`app.services.balances`.

These are the rules the whole product rests on, so they are tested harder than
anything else in the codebase and deliberately depend on nothing — no database,
no HTTP, no fixtures.
"""

from decimal import Decimal

import pytest

from app.services.balances import (
    AlreadySettledError,
    NonPositivePaymentError,
    OverpaymentError,
    is_settled,
    outstanding,
    to_money,
    total_paid,
    validate_payment,
)


class TestToMoney:
    def test_normalises_to_two_places(self):
        assert to_money("5") == Decimal("5.00")

    def test_accepts_integers(self):
        assert to_money(150) == Decimal("150.00")

    def test_rounds_half_up_not_bankers(self):
        # Python's default is banker's rounding, which would give 0.02 here.
        assert to_money("0.025") == Decimal("0.03")

    def test_float_input_does_not_leak_binary_error(self):
        assert to_money(0.1 + 0.2) == Decimal("0.30")


class TestTotalPaid:
    def test_no_payments_is_zero(self):
        assert total_paid([]) == Decimal("0.00")

    def test_sums_payments(self):
        assert total_paid(["100.00", "50.50", "25.25"]) == Decimal("175.75")

    def test_accepts_a_generator(self):
        assert total_paid(Decimal("10.00") for _ in range(3)) == Decimal("30.00")


class TestOutstanding:
    def test_unpaid_fee_owes_the_full_amount(self):
        assert outstanding("500.00", []) == Decimal("500.00")

    def test_partial_payment_reduces_the_balance(self):
        assert outstanding("500.00", ["200.00"]) == Decimal("300.00")

    def test_installments_accumulate(self):
        assert outstanding("500.00", ["200.00", "150.00", "100.00"]) == Decimal("50.00")

    def test_exact_payoff_leaves_nothing(self):
        assert outstanding("500.00", ["500.00"]) == Decimal("0.00")

    def test_never_reports_a_negative_balance(self):
        # A credit balance is not a v1 concept; refunds are on the roadmap.
        assert outstanding("100.00", ["150.00"]) == Decimal("0.00")

    def test_uneven_thirds_leave_a_remainder_cent(self):
        # The classic float-drift trap: three payments of 33.33 do not clear 100.
        assert outstanding("100.00", ["33.33", "33.33", "33.33"]) == Decimal("0.01")


class TestIsSettled:
    def test_unpaid_is_not_settled(self):
        assert is_settled("100.00", []) is False

    def test_partially_paid_is_not_settled(self):
        assert is_settled("100.00", ["99.99"]) is False

    def test_fully_paid_is_settled(self):
        assert is_settled("100.00", ["100.00"]) is True


class TestValidatePayment:
    def test_accepts_a_partial_payment(self):
        assert validate_payment("500.00", [], "200.00") == Decimal("200.00")

    def test_accepts_a_payment_against_an_existing_balance(self):
        assert validate_payment("500.00", ["200.00"], "100.00") == Decimal("100.00")

    def test_accepts_a_payment_that_exactly_clears_the_balance(self):
        assert validate_payment("500.00", ["450.00"], "50.00") == Decimal("50.00")

    @pytest.mark.parametrize("bad", ["0", "0.00", "-1.00", "-0.01"])
    def test_rejects_non_positive_payments(self, bad):
        with pytest.raises(NonPositivePaymentError):
            validate_payment("500.00", [], bad)

    def test_rejects_overpayment_on_an_untouched_fee(self):
        with pytest.raises(OverpaymentError):
            validate_payment("500.00", [], "500.01")

    def test_rejects_overpayment_by_a_single_cent(self):
        with pytest.raises(OverpaymentError):
            validate_payment("500.00", ["499.99"], "0.02")

    def test_rejects_any_payment_once_settled(self):
        with pytest.raises(AlreadySettledError):
            validate_payment("500.00", ["500.00"], "0.01")

    def test_already_settled_is_catchable_as_overpayment(self):
        # Callers that only care "this payment is too much" need one except clause.
        with pytest.raises(OverpaymentError):
            validate_payment("500.00", ["500.00"], "10.00")

    def test_rejection_message_names_the_remaining_balance(self):
        with pytest.raises(OverpaymentError, match="300.00"):
            validate_payment("500.00", ["200.00"], "400.00")

    def test_installment_sequence_settles_exactly(self):
        amount = Decimal("450.00")
        paid: list[Decimal] = []
        for installment in ("150.00", "150.00", "150.00"):
            paid.append(validate_payment(amount, paid, installment))
        assert outstanding(amount, paid) == Decimal("0.00")
        assert is_settled(amount, paid) is True
