"""What we hand Stripe.

No network: ``Session.create`` is replaced and the arguments inspected. The
value is in the arguments - a wrong ``unit_amount`` charges the wrong money,
and missing metadata means a webhook that cannot tell which bill was paid.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services import stripe_gateway


class TestMinorUnits:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [("250.00", 25000), ("0.01", 1), ("99.90", 9990), ("1234.56", 123456)],
    )
    def test_conversion(self, amount, expected):
        assert stripe_gateway.to_minor_units(Decimal(amount)) == expected

    def test_the_amount_never_passes_through_a_float(self):
        """``amount * 100`` on a float is how 1.15 becomes 114. scaleb shifts
        the point on the Decimal itself."""
        assert stripe_gateway.to_minor_units(Decimal("1.15")) == 115
        assert stripe_gateway.to_minor_units(Decimal("8.20")) == 820

    def test_a_whole_number_still_gets_its_places(self):
        assert stripe_gateway.to_minor_units(Decimal("7")) == 700


class TestCheckoutSessionArguments:
    @pytest.fixture
    def captured(self, monkeypatch):
        calls = {}

        class FakeSession:
            id = "cs_test_123"
            url = "https://checkout.stripe.com/c/pay/cs_test_123"

        def fake_create(**params):
            calls.update(params)
            return FakeSession()

        monkeypatch.setattr(stripe_gateway.stripe.checkout.Session, "create", fake_create)
        stripe_gateway.create_checkout_session(
            amount=Decimal("250.00"),
            fee_assignment_id=42,
            paid_by_user_id=7,
            description="Tuition - Term 1 2026",
        )
        return calls

    def test_the_amount_is_sent_in_minor_units(self, captured):
        assert captured["line_items"][0]["price_data"]["unit_amount"] == 25000

    def test_the_description_reaches_the_payment_page(self, captured):
        assert captured["line_items"][0]["price_data"]["product_data"]["name"] == (
            "Tuition - Term 1 2026"
        )

    def test_the_session_carries_the_fee_assignment(self, captured):
        """A webhook arrives with no session, no cookie and no user. Metadata
        is the only way it learns which bill was being paid."""
        assert captured["metadata"]["fee_assignment_id"] == "42"
        assert captured["metadata"]["paid_by_user_id"] == "7"

    def test_the_payment_intent_carries_it_too(self, captured):
        """The session and the intent are different objects, and which one an
        event carries depends on the event type."""
        assert captured["payment_intent_data"]["metadata"]["fee_assignment_id"] == "42"

    def test_it_is_a_one_off_payment_not_a_subscription(self, captured):
        assert captured["mode"] == "payment"

    def test_the_session_id_and_url_come_back(self, monkeypatch):
        class FakeSession:
            id = "cs_test_abc"
            url = "https://checkout.stripe.com/c/pay/cs_test_abc"

        monkeypatch.setattr(
            stripe_gateway.stripe.checkout.Session, "create", lambda **_: FakeSession()
        )
        session = stripe_gateway.create_checkout_session(
            amount=Decimal("10.00"), fee_assignment_id=1, paid_by_user_id=1, description="x"
        )
        assert session.id == "cs_test_abc"
        assert session.url.startswith("https://checkout.stripe.com/")
