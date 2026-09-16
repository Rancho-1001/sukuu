"""A gateway that captures checkouts and never touches the network.

Webhook parsing is *not* faked: it is delegated to the real implementation,
so the signature checks in the webhook tests exercise the real code. Only the
outbound call - the one that would need a processor on the other end - is
replaced.
"""

from __future__ import annotations

from app.models import PaymentProvider
from app.services.gateways import CheckoutSession, gateway_for


class FakeGateway:
    def __init__(self, provider: PaymentProvider = PaymentProvider.STRIPE) -> None:
        self._real = gateway_for(provider)
        self.provider = provider
        self.display_name = self._real.display_name
        self.currency = self._real.currency
        self.methods = self._real.methods
        self.test_mode = True
        self.calls: list[dict] = []

    def create_checkout(self, **kwargs) -> CheckoutSession:
        self.calls.append(kwargs)
        n = len(self.calls)
        if self.provider is PaymentProvider.PAYSTACK:
            return CheckoutSession(id=f"sukuu-ref-{n}", url=f"https://checkout.paystack.com/{n}")
        return CheckoutSession(id=f"cs_test_{n}", url=f"https://checkout.stripe.com/c/pay/cs_{n}")

    def parse_webhook(self, payload, headers):
        return self._real.parse_webhook(payload, headers)


def use_fake_gateway(
    monkeypatch, provider: PaymentProvider = PaymentProvider.STRIPE
) -> FakeGateway:
    """Make the checkout route open checkouts on a FakeGateway."""
    from app.services import gateways

    fake = FakeGateway(provider)
    monkeypatch.setattr(gateways, "get_gateway", lambda: fake)
    return fake
