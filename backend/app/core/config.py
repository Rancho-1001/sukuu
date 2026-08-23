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


settings = Settings()  # type: ignore[call-arg]
