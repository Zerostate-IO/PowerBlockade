from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://powerblockade:change-me@postgres:5432/powerblockade"
    admin_secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me"

    primary_api_key: str | None = None
    grafana_url: str = "http://grafana:3000"

    metrics_retention_days: int = 365
    events_retention_days: int = 15


def get_settings() -> Settings:
    return Settings()
