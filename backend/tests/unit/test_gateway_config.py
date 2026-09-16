"""Choosing a processor is one setting, and a deployment that chooses one it
cannot use should not start."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models import PaymentProvider

BASE = {"database_url": "postgresql+psycopg://x/y", "jwt_secret": "z" * 32}


def settings_with(**overrides) -> Settings:
    # No .env: a developer's local Stripe keys must not decide these tests.
    return Settings(_env_file=None, **BASE, **overrides)  # type: ignore[arg-type]


class TestChoosingAGateway:
    def test_stripe_is_the_default(self):
        s = settings_with(stripe_secret_key="sk_test_a", stripe_webhook_secret="whsec_b")
        assert s.payment_gateway is PaymentProvider.STRIPE
        assert s.currency == "usd"

    def test_paystack_defaults_to_cedis(self):
        s = settings_with(payment_gateway="paystack", paystack_secret_key="sk_test_p")
        assert s.payment_gateway is PaymentProvider.PAYSTACK
        assert s.currency == "ghs"

    def test_the_currency_can_be_overridden(self):
        """A Canadian school on Stripe charges in CAD; a Nigerian one on
        Paystack in NGN. The default is a default."""
        s = settings_with(
            stripe_secret_key="sk_test_a", stripe_webhook_secret="whsec_b", payment_currency="CAD"
        )
        assert s.currency == "cad"

    def test_an_unknown_gateway_is_refused(self):
        with pytest.raises(ValueError, match="payment_gateway"):
            settings_with(payment_gateway="flutterwave")


class TestAGatewayNeedsItsSecrets:
    def test_stripe_without_a_webhook_secret_does_not_start(self):
        with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET"):
            settings_with(stripe_secret_key="sk_test_a", stripe_webhook_secret="")

    def test_stripe_without_an_api_key_does_not_start(self):
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
            settings_with(stripe_secret_key="", stripe_webhook_secret="whsec_b")

    def test_paystack_without_its_key_does_not_start(self):
        with pytest.raises(ValueError, match="PAYSTACK_SECRET_KEY"):
            settings_with(payment_gateway="paystack", paystack_secret_key="")

    def test_the_other_gateways_secrets_are_not_required(self, monkeypatch):
        """A Ghanaian deployment has no Stripe account and should not need
        to invent one."""
        monkeypatch.delenv("STRIPE_SECRET_KEY")
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
        s = settings_with(payment_gateway="paystack", paystack_secret_key="sk_test_p")
        assert s.stripe_secret_key == ""

    def test_pasted_whitespace_is_stripped_from_the_paystack_key(self):
        s = settings_with(payment_gateway="paystack", paystack_secret_key=" sk_test_p\n")
        assert s.paystack_secret_key == "sk_test_p"


class TestTheOldStripeNamesStillWork:
    """The return URLs were renamed from STRIPE_* to PAYMENT_*. A deployment
    that set the old names keeps working until someone gets round to it."""

    def test_old_success_url(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SUCCESS_URL", "https://old/success")
        s = settings_with(stripe_secret_key="sk_test_a", stripe_webhook_secret="whsec_b")
        assert s.payment_success_url == "https://old/success"

    def test_new_name_wins_when_both_are_set(self, monkeypatch):
        monkeypatch.setenv("STRIPE_CANCEL_URL", "https://old/cancelled")
        monkeypatch.setenv("PAYMENT_CANCEL_URL", "https://new/cancelled")
        s = settings_with(stripe_secret_key="sk_test_a", stripe_webhook_secret="whsec_b")
        assert s.payment_cancel_url == "https://new/cancelled"

    def test_old_currency_name(self, monkeypatch):
        monkeypatch.setenv("STRIPE_CURRENCY", "cad")
        s = settings_with(stripe_secret_key="sk_test_a", stripe_webhook_secret="whsec_b")
        assert s.currency == "cad"
