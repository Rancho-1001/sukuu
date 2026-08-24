from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
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


settings = Settings()  # type: ignore[call-arg]
