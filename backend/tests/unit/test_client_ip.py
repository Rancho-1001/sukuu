"""Working out who the caller is, which the per-source limit depends on."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.rate_limit import client_ip


def fake_request(peer: str | None, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(
        client=SimpleNamespace(host=peer) if peer else None,
        headers=headers,
    )


@pytest.fixture
def trust_proxy(monkeypatch):
    def _set(value: bool):
        monkeypatch.setattr(settings, "trust_proxy_headers", value)

    return _set


class TestUntrustedProxyHeaders:
    def test_uses_the_socket_peer(self, trust_proxy):
        trust_proxy(False)
        assert client_ip(fake_request("203.0.113.7")) == "203.0.113.7"

    def test_ignores_x_forwarded_for(self, trust_proxy):
        """The default. A client can set this header itself.

        Honouring it with no proxy in front would let an attacker present a new
        address on every request, so the per-source count would never exceed
        one and the limit would be worse than absent.
        """
        trust_proxy(False)
        request = fake_request("203.0.113.7", forwarded="1.2.3.4")
        assert client_ip(request) == "203.0.113.7"

    def test_handles_a_missing_client(self, trust_proxy):
        trust_proxy(False)
        assert client_ip(fake_request(None)) is None


class TestTrustedProxyHeaders:
    def test_uses_the_leftmost_forwarded_entry(self, trust_proxy):
        trust_proxy(True)
        request = fake_request("10.0.0.1", forwarded="203.0.113.7, 10.0.0.2, 10.0.0.3")
        assert client_ip(request) == "203.0.113.7"

    def test_falls_back_to_the_peer_when_the_header_is_absent(self, trust_proxy):
        trust_proxy(True)
        assert client_ip(fake_request("10.0.0.1")) == "10.0.0.1"

    def test_truncates_to_the_column_width(self, trust_proxy):
        trust_proxy(True)
        assert len(client_ip(fake_request("10.0.0.1", forwarded="x" * 200))) == 45
