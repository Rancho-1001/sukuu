"""CORS is the only thing standing between this API and any page on the
internet making authenticated requests to it with a user's token.

These are cheap tests for a setting that is easy to get wrong once and never
look at again.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

BASE = {"database_url": "postgresql+psycopg://x/y", "jwt_secret": "z" * 32}


def settings_with(origin: str) -> Settings:
    return Settings(**BASE, frontend_origin=origin)  # type: ignore[arg-type]


class TestParsing:
    def test_a_single_origin(self):
        assert settings_with("https://sukuu.vercel.app").cors_origins == [
            "https://sukuu.vercel.app"
        ]

    def test_several_origins(self):
        """A deploy usually needs the real domain and localhost at once."""
        parsed = settings_with("https://sukuu.vercel.app,http://localhost:5173").cors_origins
        assert parsed == ["https://sukuu.vercel.app", "http://localhost:5173"]

    def test_whitespace_around_commas_is_forgiven(self):
        parsed = settings_with(" https://a.example , https://b.example ").cors_origins
        assert parsed == ["https://a.example", "https://b.example"]

    def test_a_trailing_comma_does_not_produce_an_empty_origin(self):
        """An empty string in the list would be an origin no browser sends and
        a reader would puzzle over."""
        assert settings_with("https://a.example,").cors_origins == ["https://a.example"]


class TestTheWildcardIsRefused:
    @pytest.mark.parametrize("value", ["*", "https://*.vercel.app", "http://localhost:5173,*"])
    def test_it_will_not_start(self, value):
        """allow_credentials is on, and a browser refuses a wildcard with
        credentials anyway - so setting it would make every cross-origin
        request fail in a way that looks like a frontend bug. Failing at
        startup names the cause instead."""
        with pytest.raises(ValueError, match="wildcard"):
            settings_with(value)

    def test_the_error_says_what_to_do(self):
        with pytest.raises(ValueError, match="deployed frontend"):
            settings_with("*")


def test_the_default_is_local_development_only():
    """Nothing is allowed by accident: the default names one localhost port,
    so a deploy that forgets to set this is broken loudly rather than open."""
    assert Settings(**BASE).cors_origins == ["http://localhost:5173"]  # type: ignore[arg-type]
