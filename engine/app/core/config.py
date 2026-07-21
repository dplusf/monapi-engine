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

    worker_interval_seconds: int = 900

    rate_limit_default: str = "60/minute"
    rate_limit_email: str = "10/minute"

    smtp_enabled: bool = True
    smtp_timeout_seconds: int = 10
    smtp_helo_host: str = "api.monapi.io"
    smtp_mail_from: str = "postmaster@monapi.io"

    smtp_socks_enabled: bool = False
    smtp_proxy_addr: str = ""
    smtp_proxy_port: int = 1080

    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
