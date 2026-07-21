from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    public_host: str = "api.monapi.io"
    api_key_header: str = "X-API-Key"
    api_key_pepper: str = "change-me"
    bootstrap_api_keys: str = "dev-key-1,dev-key-2"

    sqlite_path: str = "/data/monapi.sqlite3"
    index_dir: str = "/data/index"
    feeds_config: str = "/app/app/data/feeds.yaml"
    policies_config: str = "/app/app/data/policies.yaml"

    # Adapter selection (Phase 1b wires concrete implementations).
    enricher: str = "null"  # null | geoip
    email_verifier: str = "null"  # null | reoon

    geoip_mmdb_path: str = "/data/geoip/ip66.mmdb"
    geoip_url: str = "https://downloads.ip66.dev/db/ip66.mmdb"
    geoip_max_age_seconds: int = 86400
    rdns_enabled: bool = True
    rdns_timeout_seconds: float = 2.0

    reoon_api_key: str = ""
    reoon_mode: str = "quick"  # quick | power

    worker_interval_seconds: int = 900

    rate_limit_default: str = "60/minute"
    rate_limit_email: str = "10/minute"

    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
