"""The payment service's own guards, away from HTTP and away from the race.

The concurrency test next door proves the lock. This proves everything the
service refuses before it ever gets that far, including the two Stripe
pairings that only Phase 5 will exercise for real - written now because the
CHECK constraint enforcing them is already in the database, and an
IntegrityError at commit is a much worse way to learn about it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import PaymentMethod
from app.services.balances import (
    AlreadySettledError,
    NonPositivePaymentError,
    OverpaymentError,
)
from app.services.payments import UnknownFeeAssignmentError, record_payment

pytestmark = pytest.mark.db


@pytest.fixture
def assignment(make_student, make_fee_type, make_fee_assignment):
    return make_fee_assignment(make_student(), make_fee_type(default_amount="100.00"))


def cash(db_session, assignment_id, amount, **kwargs):
    return record_payment(
        db_session,
        fee_assignment_id=assignment_id,
        amount=amount,
        method=PaymentMethod.CASH,
        **kwargs,
    )


class TestAcceptedPayments:
    def test_a_payment_is_written_and_given_an_id(self, db_session, assignment):
        payment = cash(db_session, assignment.id, Decimal("40.00"))
        assert payment.id is not None
        assert payment.amount_paid == Decimal("40.00")
        assert payment.fee_assignment_id == assignment.id

    def test_the_amount_is_normalised_to_two_places(self, db_session, assignment):
        assert cash(db_session, assignment.id, "40.5").amount_paid == Decimal("40.50")

    def test_who_recorded_it_is_kept(self, db_session, assignment, make_user):
        from app.models import UserRole

        bursar = make_user(UserRole.STAFF)
        payment = cash(db_session, assignment.id, Decimal("10.00"), recorded_by_id=bursar.id)
        assert payment.recorded_by_id == bursar.id

    def test_installments_accumulate_against_the_same_assignment(self, db_session, assignment):
        cash(db_session, assignment.id, Decimal("60.00"))
        cash(db_session, assignment.id, Decimal("40.00"))
        assert sum(p.amount_paid for p in assignment.payments) == Decimal("100.00")

    def test_a_payment_that_exactly_clears_the_balance_is_allowed(self, db_session, assignment):
        assert cash(db_session, assignment.id, Decimal("100.00")).amount_paid == Decimal("100.00")


class TestRefusedPayments:
    def test_an_unknown_assignment(self, db_session):
        with pytest.raises(UnknownFeeAssignmentError):
            cash(db_session, 99999999, Decimal("10.00"))

    @pytest.mark.parametrize("amount", ["0.00", "-10.00"])
    def test_a_non_positive_amount(self, db_session, assignment, amount):
        with pytest.raises(NonPositivePaymentError):
            cash(db_session, assignment.id, Decimal(amount))

    def test_more_than_is_owed(self, db_session, assignment):
        with pytest.raises(OverpaymentError):
            cash(db_session, assignment.id, Decimal("100.01"))

    def test_a_single_cent_past_the_remaining_balance(self, db_session, assignment):
        cash(db_session, assignment.id, Decimal("99.99"))
        with pytest.raises(OverpaymentError):
            cash(db_session, assignment.id, Decimal("0.02"))

    def test_anything_at_all_once_settled(self, db_session, assignment):
        cash(db_session, assignment.id, Decimal("100.00"))
        with pytest.raises(AlreadySettledError):
            cash(db_session, assignment.id, Decimal("0.01"))


class TestMethodAndIdentifiersAgree:
    """The database's CHECK constraint, enforced at the call that breaks it.

    Left to the constraint, these surface as an IntegrityError at commit -
    after the caller has done other work, and pointing at the commit rather
    than at the mistake.
    """

    def test_cash_cannot_carry_a_payment_intent(self, db_session, assignment):
        with pytest.raises(ValueError, match="cash payment"):
            cash(db_session, assignment.id, Decimal("10.00"), stripe_payment_intent_id="pi_123")

    def test_cash_cannot_carry_an_event_id(self, db_session, assignment):
        with pytest.raises(ValueError, match="cash payment"):
            cash(db_session, assignment.id, Decimal("10.00"), stripe_event_id="evt_123")

    def test_stripe_needs_a_payment_intent(self, db_session, assignment):
        with pytest.raises(ValueError, match="payment intent"):
            record_payment(
                db_session,
                fee_assignment_id=assignment.id,
                amount=Decimal("10.00"),
                method=PaymentMethod.STRIPE,
            )

    def test_a_stripe_payment_with_its_identifiers_is_accepted(self, db_session, assignment):
        """Phase 5's path, open before Phase 5 needs it."""
        payment = record_payment(
            db_session,
            fee_assignment_id=assignment.id,
            amount=Decimal("10.00"),
            method=PaymentMethod.STRIPE,
            stripe_payment_intent_id="pi_123",
            stripe_event_id="evt_123",
        )
        assert payment.method is PaymentMethod.STRIPE
        assert payment.recorded_by_id is None
