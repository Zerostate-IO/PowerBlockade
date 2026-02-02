from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://powerblockade:change-me@postgres:5432/powerblockade"
    admin_secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me"

    primary_api_key: str | None = None
    # Local node API key for the primary's own node identity
    # If not set, auto-generates one based on hostname + secret
    local_node_api_key: str | None = None
    # Node name for the primary (defaults to hostname)
    node_name: str | None = None
    grafana_url: str = "http://grafana:3000"
    recursor_api_url: str = "http://recursor:8082"

    metrics_retention_days: int = 365
    events_retention_days: int = 15

    # Cache hit detection threshold (milliseconds)
    # Queries faster than this are considered cache hits for precache analytics
    # Default 5ms based on typical local cache latency; adjust based on your hardware
    cache_hit_threshold_ms: int = 5

    # Version info (injected at build time)
    pb_version: str = "0.3.1"
    pb_git_sha: str = "unknown"
    pb_build_date: str = "unknown"

    # Node sync protocol version
    node_protocol_version: int = 1
    node_protocol_min_supported: int = 1


def get_settings() -> Settings:
    return Settings()
