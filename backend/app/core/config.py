from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.enums import PaymentProvider

# What each processor is charged in when nothing says otherwise. Stripe is the
# North American gateway; Paystack is the Ghanaian one.
DEFAULT_CURRENCY = {PaymentProvider.STRIPE: "usd", PaymentProvider.PAYSTACK: "ghs"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Which processor a parent's pay button opens. Stripe for the United
    # States and Canada; Paystack - cards and mobile money - for Ghana. Each
    # brings its own secrets, and the API refuses to start if the chosen one
    # has none: a gateway with no secret cannot verify a webhook, and an HMAC
    # against an empty key is a signature anyone can produce.
    payment_gateway: PaymentProvider = PaymentProvider.STRIPE
    # Lower-case ISO code. Defaults per gateway; set it to override.
    payment_currency: str = Field(
        default="", validation_alias=AliasChoices("PAYMENT_CURRENCY", "STRIPE_CURRENCY")
    )
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # One key for both the API and webhook signatures - that is how Paystack
    # works, not a shortcut.
    paystack_secret_key: str = ""

    # Where the processor sends a parent afterwards. The old STRIPE_* names
    # still work so a deployment does not break on the rename.
    payment_success_url: str = Field(
        default="http://localhost:5173/payments/success",
        validation_alias=AliasChoices("PAYMENT_SUCCESS_URL", "STRIPE_SUCCESS_URL"),
    )
    payment_cancel_url: str = Field(
        default="http://localhost:5173/payments/cancelled",
        validation_alias=AliasChoices("PAYMENT_CANCEL_URL", "STRIPE_CANCEL_URL"),
    )
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

    @field_validator(
        "stripe_secret_key",
        "stripe_webhook_secret",
        "paystack_secret_key",
        "jwt_secret",
        "database_url",
    )
    @classmethod
    def _strip_pasted_whitespace(cls, value: str) -> str:
        """A trailing newline from a copy-paste is invisible in a dashboard and
        fatal to an HMAC. Every one of these is pasted into a form at some
        point, so tolerate it here rather than debug it from a 400."""
        return value.strip()

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

    @model_validator(mode="after")
    def _the_chosen_gateway_has_its_secrets(self) -> Settings:
        """Refuse to start with a gateway that cannot verify its own webhooks."""
        missing = [name for name, value in self.gateway_secrets.items() if not value]
        if missing:
            raise ValueError(
                f"PAYMENT_GATEWAY={self.payment_gateway.value} needs {', '.join(missing)}. "
                "Set them, or choose a gateway whose secrets are set."
            )
        return self

    @property
    def gateway_secrets(self) -> dict[str, str]:
        """The environment variables the chosen gateway lives on, by name."""
        if self.payment_gateway is PaymentProvider.PAYSTACK:
            return {"PAYSTACK_SECRET_KEY": self.paystack_secret_key}
        return {
            "STRIPE_SECRET_KEY": self.stripe_secret_key,
            "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret,
        }

    @property
    def currency(self) -> str:
        """Lower-case ISO code the chosen gateway charges in."""
        return (self.payment_currency or DEFAULT_CURRENCY[self.payment_gateway]).lower()

    @property
    def cors_origins(self) -> list[str]:
        """The origins allowed to call this API, in the order given."""
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]


settings = Settings()  # type: ignore[call-arg]
