"""What we hand Paystack, and how we read what it sends back.

No network: ``httpx.post`` is replaced and the request inspected. Webhook
parsing is exercised with real HMAC-SHA512 signatures, because the parser is
the verification.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.models import PaymentMethod, PaymentProvider
from app.services.gateways import base
from app.services.gateways import paystack as paystack_gateway
from app.services.gateways.paystack import PaystackError, PaystackGateway
from tests.paystack_helpers import event_body, sign

SECRET = "sk_test_paystack_unit"


def gateway(**overrides) -> PaystackGateway:
    return PaystackGateway(**{"secret_key": SECRET, "currency": "ghs", **overrides})


def parse(payload: bytes, *, signature: str | None = None, g: PaystackGateway | None = None):
    g = g or gateway()
    header = signature if signature is not None else sign(payload, secret=SECRET)
    return g.parse_webhook(payload, {"x-paystack-signature": header})


class TestIdentity:
    def test_it_is_paystack_and_takes_mobile_money(self):
        assert gateway().provider is PaymentProvider.PAYSTACK
        assert PaymentMethod.MOBILE_MONEY in gateway().methods

    @pytest.mark.parametrize(
        ("key", "expected"), [("sk_test_abc", True), ("sk_live_abc", False), ("", False)]
    )
    def test_test_mode_is_read_off_the_key(self, key, expected):
        assert gateway(secret_key=key).test_mode is expected


class FakeResponse:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class TestInitialize:
    @pytest.fixture
    def captured(self, monkeypatch):
        calls = {}

        def fake_post(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            return FakeResponse(
                200,
                {
                    "status": True,
                    "message": "Authorization URL created",
                    "data": {
                        "authorization_url": "https://checkout.paystack.com/abc123",
                        "access_code": "abc123",
                        "reference": kwargs["json"]["reference"],
                    },
                },
            )

        monkeypatch.setattr(paystack_gateway.httpx, "post", fake_post)
        calls["session"] = gateway().create_checkout(
            amount=Decimal("250.00"),
            fee_assignment_id=42,
            paid_by_user_id=7,
            payer_email="parent@example.com",
            description="Tuition - Term 1 2026",
            success_url="https://app/success?fee=42",
            cancel_url="https://app/cancelled?fee=42",
        )
        return calls

    def test_it_initialises_a_transaction(self, captured):
        assert captured["url"] == "https://api.paystack.co/transaction/initialize"

    def test_the_key_goes_in_the_bearer_header(self, captured):
        assert captured["headers"]["Authorization"] == f"Bearer {SECRET}"

    def test_the_amount_is_sent_in_pesewas(self, captured):
        assert captured["json"]["amount"] == 25000

    def test_the_currency_is_upper_case_as_paystack_wants_it(self, captured):
        assert captured["json"]["currency"] == "GHS"

    def test_the_payer_email_is_required_and_sent(self, captured):
        assert captured["json"]["email"] == "parent@example.com"

    def test_the_bill_travels_in_metadata(self, captured):
        metadata = captured["json"]["metadata"]
        assert metadata["fee_assignment_id"] == "42"
        assert metadata["paid_by_user_id"] == "7"

    def test_both_return_urls_are_sent(self, captured):
        """Paystack has one callback URL; backing out goes through
        ``metadata.cancel_action``."""
        assert captured["json"]["callback_url"] == "https://app/success?fee=42"
        assert captured["json"]["metadata"]["cancel_action"] == "https://app/cancelled?fee=42"

    def test_the_reference_is_ours_and_names_the_bill(self, captured):
        """So the audit row at checkout start already carries what the webhook
        will bring back."""
        reference = captured["json"]["reference"]
        assert reference.startswith("sukuu-42-")
        assert captured["session"].id == reference

    def test_the_hosted_page_url_comes_back(self, captured):
        assert captured["session"].url == "https://checkout.paystack.com/abc123"

    def test_a_refusal_is_an_error_not_a_url(self, monkeypatch):
        monkeypatch.setattr(
            paystack_gateway.httpx,
            "post",
            lambda *_, **__: FakeResponse(400, {"status": False, "message": "Invalid key"}),
        )
        with pytest.raises(PaystackError, match="Invalid key"):
            gateway().create_checkout(
                amount=Decimal("1.00"),
                fee_assignment_id=1,
                paid_by_user_id=1,
                payer_email="p@example.com",
                description="x",
                success_url="s",
                cancel_url="c",
            )

    def test_a_non_json_answer_is_an_error(self, monkeypatch):
        monkeypatch.setattr(
            paystack_gateway.httpx, "post", lambda *_, **__: FakeResponse(502, "<html>")
        )
        with pytest.raises(PaystackError, match="502"):
            gateway().create_checkout(
                amount=Decimal("1.00"),
                fee_assignment_id=1,
                paid_by_user_id=1,
                payer_email="p@example.com",
                description="x",
                success_url="s",
                cancel_url="c",
            )

    def test_without_a_key_nothing_is_sent(self, monkeypatch):
        monkeypatch.setattr(
            paystack_gateway.httpx, "post", lambda *_, **__: pytest.fail("must not be called")
        )
        with pytest.raises(base.GatewayNotConfiguredError):
            gateway(secret_key="").create_checkout(
                amount=Decimal("1.00"),
                fee_assignment_id=1,
                paid_by_user_id=1,
                payer_email="p@example.com",
                description="x",
                success_url="s",
                cancel_url="c",
            )


class TestWebhookSignature:
    def test_a_correctly_signed_body_is_read(self):
        assert parse(event_body()).outcome is base.WebhookOutcome.PAID

    def test_a_missing_header_is_refused(self):
        with pytest.raises(base.WebhookVerificationError):
            gateway().parse_webhook(event_body(), {})

    def test_a_wrong_secret_is_refused(self):
        payload = event_body()
        with pytest.raises(base.WebhookVerificationError):
            parse(payload, signature=sign(payload, secret="sk_test_someone_else"))

    def test_a_tampered_body_is_refused(self):
        """Sign a 1.00 payment, deliver a 5000.00 one."""
        honest = event_body(amount=100)
        tampered = honest.replace(b'"amount": 100', b'"amount": 500000')
        assert tampered != honest
        with pytest.raises(base.WebhookVerificationError):
            parse(tampered, signature=sign(honest, secret=SECRET))

    def test_no_secret_means_no_verification_means_refusal(self):
        with pytest.raises(base.GatewayNotConfiguredError):
            parse(event_body(), signature="anything", g=gateway(secret_key=""))

    def test_signed_garbage_is_still_unreadable(self):
        with pytest.raises(ValueError):
            parse(b"not json")

    def test_a_signed_body_with_no_event_is_unreadable(self):
        with pytest.raises(ValueError):
            parse(json.dumps({"data": {}}).encode())


class TestReadingACharge:
    def test_the_amount_comes_back_in_cedis(self):
        assert parse(event_body(amount=25000)).amount == Decimal("250.00")

    def test_the_currency_is_normalised(self):
        assert parse(event_body(currency="GHS")).currency == "ghs"

    @pytest.mark.parametrize(
        ("channel", "method"),
        [
            ("mobile_money", PaymentMethod.MOBILE_MONEY),
            ("card", PaymentMethod.CARD),
            ("apple_pay", PaymentMethod.CARD),
            ("bank", PaymentMethod.BANK),
            ("bank_transfer", PaymentMethod.BANK),
            ("ussd", PaymentMethod.BANK),
            ("something_new", PaymentMethod.BANK),
        ],
    )
    def test_the_channel_becomes_the_method(self, channel, method):
        assert parse(event_body(channel=channel)).method is method

    def test_the_reference_is_the_idempotency_key(self):
        """Paystack has no event id. A transaction succeeds at most once, and
        its reference is unique, so the two together are the key."""
        event = parse(event_body(reference="sukuu-9-deadbeef"))
        assert event.id == "charge.success:sukuu-9-deadbeef"
        assert event.reference == "sukuu-9-deadbeef"

    def test_a_success_without_a_reference_cannot_be_recorded(self):
        with pytest.raises(ValueError):
            parse(event_body(reference=None))

    def test_the_bill_is_read_from_metadata(self):
        event = parse(event_body(fee_assignment_id=42, paid_by_user_id=7))
        assert event.fee_assignment_id == 42
        assert event.paid_by_user_id == 7

    def test_metadata_sent_back_as_a_string_is_still_read(self):
        event = parse(event_body(fee_assignment_id=42, metadata_as_string=True))
        assert event.fee_assignment_id == 42

    def test_no_metadata_means_no_bill(self):
        assert parse(event_body(fee_assignment_id=None)).fee_assignment_id is None

    def test_a_charge_that_is_not_a_success_is_unpaid(self):
        assert parse(event_body(status="failed")).outcome is base.WebhookOutcome.UNPAID

    def test_other_events_are_ignored(self):
        event = parse(event_body(event_type="transfer.success"))
        assert event.outcome is base.WebhookOutcome.IGNORED
        assert event.type == "transfer.success"

    def test_metadata_that_is_an_unreadable_string_is_no_metadata(self):
        payload = event_body(fee_assignment_id=1)
        broken = payload.replace(
            b'"metadata": {"fee_assignment_id": "1"}', b'"metadata": "{not json"'
        )
        assert broken != payload
        assert parse(broken).fee_assignment_id is None

    def test_a_data_field_that_is_not_an_object_is_unreadable(self):
        with pytest.raises(ValueError):
            parse(json.dumps({"event": "charge.success", "data": "nope"}).encode())
