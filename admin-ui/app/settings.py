from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://powerblockade:change-me@postgres:5432/powerblockade"
    admin_secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me"

    # Node auth: primary's local dnstap-processor uses this key.
    primary_api_key: str | None = None


def get_settings() -> Settings:
    return Settings()
