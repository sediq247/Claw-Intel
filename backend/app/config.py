from functools import lru_cache
from urllib.parse import urlsplit
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True)

    app_name: str = "Zecto"
    environment: str = "development"
    database_url: str = Field(default="postgresql+asyncpg://clawintel:clawintel@localhost:5432/clawintel")
    allowed_origins: str = "http://localhost:6548,http://127.0.0.1:6548"
    cookie_secure: bool = False
    auto_scan_enabled: bool = True
    auto_scan_interval_seconds: int = Field(default=300, ge=60, le=86400)
    price_alert_check_interval_seconds: int = Field(default=300, ge=60, le=3600)
    public_base_url: str = ""
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    metrics_bearer_token: str | None = None
    rate_limit_key_secret: str | None = None
    warroom_providers: str = "gemini,cerebras,openrouter"
    trading_providers: str = "gemini,openrouter,cerebras"
    gemini_models: str = ""
    llm_max_model_attempts: int = Field(default=7, ge=1, le=8)
    llm_global_daily_call_budget: int = Field(default=500, ge=1, le=100000)
    llm_provider_daily_call_budget: int = Field(default=250, ge=1, le=100000)
    llm_department_daily_call_budget: int = Field(default=300, ge=1, le=100000)
    llm_agent_daily_call_budget: int = Field(default=150, ge=1, le=100000)
    debate_max_challenges: int = Field(default=4, ge=0, le=5)
    debate_output_token_budget: int = Field(default=6000, ge=400, le=12000)
    debate_call_timeout_seconds: int = Field(default=60, ge=5, le=180)
    auto_scan_revisit_change_pct: float = Field(default=15.0, ge=0, le=1000)
    auto_scan_min_revisit_seconds: int = Field(default=900, ge=60, le=86400)
    coingecko_api_key: str | None = None
    exa_api_key: str | None = None
    exa_daily_call_budget: int = Field(default=20, ge=1, le=100000)
    alpha_vantage_api_key: str | None = None
    alpha_vantage_daily_call_budget: int = Field(default=20, ge=1, le=100000)
    alpha_vantage_license_status: str = Field(
        default="disabled", pattern="^(disabled|personal_noncommercial|commercial_authorized)$",
    )
    warroom_stock_symbols: str = "SPY,QQQ,AAPL,MSFT,NVDA"
    eth_rpc_url: str | None = None
    bsc_rpc_url: str | None = None
    base_rpc_url: str | None = None
    solana_rpc_url: str | None = None
    # Comma-separated operator-managed A2A Agent Card URLs. No user-supplied URLs.
    warroom_a2a_agent_cards: str = ""
    a2a_timeout_seconds: int = Field(default=12, ge=3, le=30)
    warroom_gemini_api_key: str | None = None
    warroom_gemini_model: str = ""
    warroom_openrouter_api_key: str | None = None
    warroom_openrouter_model: str = ""
    warroom_cerebras_api_key: str | None = None
    warroom_cerebras_model: str = ""
    trading_gemini_api_key: str | None = None
    trading_gemini_model: str = ""
    trading_openrouter_api_key: str | None = None
    trading_openrouter_model: str = ""
    trading_cerebras_api_key: str | None = None
    trading_cerebras_model: str = ""

    @model_validator(mode="after")
    def require_secure_cookie_in_production(self):
        production = self.environment.strip().lower() in {"prod", "production"}
        if production and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true when ENVIRONMENT is production")
        if production and len(self.rate_limit_key_secret or "") < 32:
            raise ValueError("RATE_LIMIT_KEY_SECRET must contain at least 32 characters in production")
        if production:
            database = urlsplit(self.database_url)
            if database.scheme not in {"postgresql", "postgresql+asyncpg"}:
                raise ValueError("Production DATABASE_URL must use PostgreSQL")
            if not database.hostname or database.hostname.lower() in {"localhost", "127.0.0.1", "db"}:
                raise ValueError("Production DATABASE_URL must point to a managed or remote PostgreSQL host")
            if not database.password or database.password in {"clawintel", "clawintel-local-only", "postgres"}:
                raise ValueError("Production DATABASE_URL must not use a local development password")
            origins = self.cors_origins
            if not origins or any(urlsplit(origin).scheme != "https" or not urlsplit(origin).hostname
                                  or urlsplit(origin).hostname.lower() in {"localhost", "127.0.0.1"}
                                  for origin in origins):
                raise ValueError("Production ALLOWED_ORIGINS must contain only explicit HTTPS site origins")
            if self.public_base_url and urlsplit(self.public_base_url).scheme != "https":
                raise ValueError("Production PUBLIC_BASE_URL must use HTTPS")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
