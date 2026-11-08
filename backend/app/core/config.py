"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Trading Intelligence Platform"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    api_prefix: str = "/api/v1"

    # Security
    secret_key: str = Field(default="dev-insecure-secret-change-me", min_length=16)
    session_ttl_hours: int = 72
    session_cookie_name: str = "ti_session"
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    # X-Forwarded-For is honoured only from these peers, or from a proxy presenting
    # PROXY_SHARED_SECRET (the Next.js server sends it). Prevents rate-limit spoofing.
    trusted_proxies: Annotated[list[str], NoDecode] = ["127.0.0.1/32", "::1/128"]
    proxy_shared_secret: str | None = None
    login_max_failures: int = 10
    login_lockout_minutes: int = 15
    admin_emails: Annotated[list[str], NoDecode] = []  # granted admin once the address is verified

    # Email (verification and password reset). "console" logs messages instead of sending them.
    email_backend: Literal["console", "smtp"] = "console"
    email_from: str = "Kestrel Intelligence <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    public_app_url: str = "http://localhost:3000"  # base for links in emails
    email_verification_ttl_hours: int = 48
    # Public demo: "Try the demo" creates a throwaway sandbox account per visitor.
    demo_mode: bool = False
    demo_ttl_hours: int = 24
    demo_max_accounts: int = 500  # live sandboxes at once; protects the database and CPU from mass sign-ups
    demo_allow_llm: bool = False  # anonymous demo visitors get the rule-based engine, not paid LLM calls
    password_reset_ttl_minutes: int = 60

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./data/dev.db"
    redis_url: str | None = None

    # Rate limiting
    rate_limit_per_minute: int = 240
    auth_rate_limit_per_minute: int = 15
    compute_rate_limit_per_minute: int = 30  # analysis, backtests, assistant

    # Market data
    market_data_provider: Literal["coinbase", "sample"] = "coinbase"
    market_ws_poll_seconds: float = 5.0
    # Gradually download long history for tracked assets (1h/6h/1d) so long backtests start fast.
    history_backfill_enabled: bool = True
    history_backfill_bars_per_minute: int = 3000  # ~10 Coinbase requests/minute
    coinbase_base_url: str = "https://api.exchange.coinbase.com"
    # Live prices from Coinbase's public WebSocket feed (REST polling remains the fallback).
    market_stream_enabled: bool = True
    coinbase_ws_url: str = "wss://ws-feed.exchange.coinbase.com"
    sentiment_url: str = "https://api.alternative.me/fng/"

    # AI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str | None = None

    # Paper trading
    paper_starting_balance: float = 100_000.0
    paper_fee_bps: float = 10.0
    paper_slippage_bps: float = 5.0

    @field_validator("cors_origins", "admin_emails", "trusted_proxies", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("admin_emails")
    @classmethod
    def _lower_emails(cls, value: list[str]) -> list[str]:
        return [v.lower() for v in value]

    @field_validator("redis_url", "openai_api_key", "openai_base_url", "proxy_shared_secret", "smtp_host",
                     "smtp_username", "smtp_password", mode="before")  # fmt: skip
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)


def _weak_secret(key: str) -> bool:
    """The built-in default, the .env.example placeholder, or too short to be a random key."""
    return key.startswith("dev-insecure") or "change-me" in key.lower() or len(key) < 32


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and _weak_secret(settings.secret_key):
        raise RuntimeError("SECRET_KEY must be a random value of 32+ characters in production (e.g. openssl rand -hex 32)")
    if settings.email_backend == "smtp" and not settings.smtp_host:
        raise RuntimeError("EMAIL_BACKEND=smtp requires SMTP_HOST")
    return settings
