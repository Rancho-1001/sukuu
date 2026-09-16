"""What we hand Stripe.

No network: ``Session.create`` is replaced and the arguments inspected. The
value is in the arguments - a wrong ``unit_amount`` charges the wrong money,
and missing metadata means a webhook that cannot tell which bill was paid.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.models import PaymentMethod, PaymentProvider
from app.services.gateways import base
from app.services.gateways import stripe as stripe_gateway
from app.services.gateways.stripe import StripeGateway


def gateway(**overrides) -> StripeGateway:
    params = {"secret_key": "sk_test_x", "webhook_secret": "whsec_x", "currency": "usd"}
    return StripeGateway(**{**params, **overrides})


class TestMinorUnits:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [("250.00", 25000), ("0.01", 1), ("99.90", 9990), ("1234.56", 123456)],
    )
    def test_conversion(self, amount, expected):
        assert base.to_minor_units(Decimal(amount)) == expected

    def test_the_amount_never_passes_through_a_float(self):
        """``amount * 100`` on a float is how 1.15 becomes 114. scaleb shifts
        the point on the Decimal itself."""
        assert base.to_minor_units(Decimal("1.15")) == 115
        assert base.to_minor_units(Decimal("8.20")) == 820

    def test_a_whole_number_still_gets_its_places(self):
        assert base.to_minor_units(Decimal("7")) == 700

    @pytest.mark.parametrize("minor", [25000, 1, 9990, 115])
    def test_the_way_back_is_exact(self, minor):
        assert base.to_minor_units(base.from_minor_units(minor)) == minor


class TestIdentity:
    def test_it_is_stripe_and_takes_cards(self):
        assert gateway().provider is PaymentProvider.STRIPE
        assert gateway().methods == (PaymentMethod.CARD,)

    def test_the_currency_is_normalised(self):
        assert gateway(currency="USD").currency == "usd"

    @pytest.mark.parametrize(
        ("key", "expected"), [("sk_test_abc", True), ("sk_live_abc", False), ("", False)]
    )
    def test_test_mode_is_read_off_the_key(self, key, expected):
        assert gateway(secret_key=key).test_mode is expected


class TestCheckoutArguments:
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
        gateway().create_checkout(
            amount=Decimal("250.00"),
            fee_assignment_id=42,
            paid_by_user_id=7,
            payer_email="parent@example.com",
            description="Tuition - Term 1 2026",
            success_url="https://app/success?fee=42",
            cancel_url="https://app/cancelled?fee=42",
        )
        return calls

    def test_the_amount_is_sent_in_minor_units(self, captured):
        assert captured["line_items"][0]["price_data"]["unit_amount"] == 25000

    def test_the_configured_currency_is_used(self, captured):
        assert captured["line_items"][0]["price_data"]["currency"] == "usd"

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

    def test_cards_only_so_that_card_is_what_gets_recorded(self, captured):
        """Every Stripe payment lands in the ledger as a card payment. That is
        true by construction only if cards are the only thing offered."""
        assert captured["payment_method_types"] == ["card"]

    def test_the_return_urls_are_passed_through(self, captured):
        assert captured["success_url"] == "https://app/success?fee=42"
        assert captured["cancel_url"] == "https://app/cancelled?fee=42"

    def test_the_payer_is_prefilled(self, captured):
        assert captured["customer_email"] == "parent@example.com"

    def test_the_session_id_and_url_come_back(self, monkeypatch):
        class FakeSession:
            id = "cs_test_abc"
            url = "https://checkout.stripe.com/c/pay/cs_test_abc"

        monkeypatch.setattr(
            stripe_gateway.stripe.checkout.Session, "create", lambda **_: FakeSession()
        )
        session = gateway().create_checkout(
            amount=Decimal("10.00"),
            fee_assignment_id=1,
            paid_by_user_id=1,
            payer_email="p@example.com",
            description="x",
            success_url="s",
            cancel_url="c",
        )
        assert session.id == "cs_test_abc"
        assert session.url.startswith("https://checkout.stripe.com/")


class TestWebhookWithoutASecret:
    def test_refuses_before_looking_at_the_body(self):
        """An HMAC against an empty key is a signature anyone can produce."""
        with pytest.raises(base.GatewayNotConfiguredError):
            gateway(webhook_secret="").parse_webhook(b"{}", {"stripe-signature": "t=1,v1=00"})


class TestReadingACompletedSession:
    """Through the real verifier, with a real signature."""

    def deliver(self, **fields):
        from tests.stripe_helpers import event_body, sign

        payload = event_body(**fields)
        return gateway(webhook_secret="whsec_x").parse_webhook(
            payload, {"stripe-signature": sign(payload, secret="whsec_x")}
        )

    def test_a_paid_session_is_a_card_payment_in_major_units(self):
        event = self.deliver(amount_total=12345, fee_assignment_id=9)
        assert event.outcome is base.WebhookOutcome.PAID
        assert event.amount == Decimal("123.45")
        assert event.method is PaymentMethod.CARD
        assert event.fee_assignment_id == 9
        assert event.reference == "pi_test_1"

    def test_an_expanded_payment_intent_still_yields_its_id(self):
        """Stripe sends the intent as a string or, if the endpoint asked for
        expansion, as an object. Both are the same payment."""
        from tests.stripe_helpers import sign

        payload = json.dumps(
            {
                "id": "evt_x",
                "object": "event",
                "api_version": "2024-06-20",
                "created": 1,
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_x",
                        "object": "checkout.session",
                        "payment_status": "paid",
                        "amount_total": 100,
                        "currency": "usd",
                        "payment_intent": {"id": "pi_expanded", "object": "payment_intent"},
                        "metadata": {"fee_assignment_id": "1"},
                    }
                },
            }
        ).encode()
        event = gateway(webhook_secret="whsec_x").parse_webhook(
            payload, {"stripe-signature": sign(payload, secret="whsec_x")}
        )
        assert event.reference == "pi_expanded"
