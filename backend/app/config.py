from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "ClawIntel"
    environment: str = "development"
    database_url: str = Field(default="postgresql+asyncpg://clawintel:clawintel@localhost:5432/clawintel")
    allowed_origins: str = "http://localhost:6548,http://127.0.0.1:6548"
    cookie_secure: bool = False
    auto_scan_enabled: bool = True
    auto_scan_interval_seconds: int = Field(default=900, ge=300, le=86400)
    warroom_providers: str = "gemini,cerebras,openrouter"
    trading_providers: str = "gemini,openrouter,cerebras"
    gemini_models: str = ""
    llm_max_model_attempts: int = Field(default=3, ge=1, le=8)
    debate_max_challenges: int = Field(default=2, ge=0, le=5)
    debate_output_token_budget: int = Field(default=3200, ge=400, le=12000)
    debate_call_timeout_seconds: int = Field(default=60, ge=5, le=180)
    auto_scan_revisit_change_pct: float = Field(default=15.0, ge=0, le=1000)
    auto_scan_min_revisit_seconds: int = Field(default=900, ge=60, le=86400)
    coingecko_api_key: str | None = None
    eth_rpc_url: str | None = None
    bsc_rpc_url: str | None = None
    base_rpc_url: str | None = None
    solana_rpc_url: str | None = None
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

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
