from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Stripe does not operate in Ghana, so a real deployment for this market
    # would use Paystack or Flutterwave; Stripe is here because test mode makes
    # the payment flow demonstrable. Charging in USD follows from that - the
    # money rules and the reconciliation are the transferable part, not the
    # processor.
    stripe_currency: str = "usd"
    stripe_success_url: str = "http://localhost:5173/payments/success"
    stripe_cancel_url: str = "http://localhost:5173/payments/cancelled"
    # One origin, or several separated by commas. A deployed API needs the
    # frontend's real domain here; CORS is the only thing standing between this
    # API and any page on the internet making authenticated requests to it with
    # a user's token.
    frontend_origin: str = "http://localhost:5173"

    # Failed logins tolerated per window, counted separately per account and
    # per source address. See app/services/rate_limit.py for why both.
    login_max_attempts_per_email: int = 5
    login_max_attempts_per_ip: int = 15
    login_rate_limit_window_minutes: int = 15

    # Only enable behind a proxy that overwrites X-Forwarded-For. With no proxy
    # in front, a client can set the header itself and pick a fresh "address"
    # for every request, which turns the per-IP limit off.
    trust_proxy_headers: bool = False

    @field_validator("frontend_origin")
    @classmethod
    def _never_a_wildcard(cls, value: str) -> str:
        """Refuse to start rather than allow every origin.

        ``allow_credentials`` is on, and a wildcard with credentials is a
        configuration a browser refuses anyway - so the practical effect of
        setting it would be that every cross-origin request fails, in a way
        that looks like a bug in the frontend. Failing here instead names the
        cause. The roadmap's rule, enforced rather than remembered.
        """
        if "*" in value:
            raise ValueError(
                "frontend_origin must name real origins, not a wildcard. "
                "Set it to the deployed frontend's URL."
            )
        return value

    @property
    def cors_origins(self) -> list[str]:
        """The origins allowed to call this API, in the order given."""
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]


settings = Settings()  # type: ignore[call-arg]
