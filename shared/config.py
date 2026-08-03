# shared/config.py  ← COMPLETE FILE
"""
Central configuration using pydantic-settings.
Pydantic v2 syntax — no deprecation warnings.
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ─────────────────────────────────────────────────
    google_api_key: str = Field(default="")

    # ── Gemini Model Names ───────────────────────────────────
    # Change here to update all agents at once
    agent_model: str = Field(
        default="gemini-flash-lite-latest",
        description="Model for specialist agents"
    )
    orchestrator_model: str = Field(
        default="gemini-flash-latest",
        description="Model for orchestrator agent"
    )

    # ── Search APIs ──────────────────────────────────────────
    google_search_api_key: str | None = Field(default=None)
    google_search_engine_id: str | None = Field(default=None)
    serpapi_key: str | None = Field(default=None)

    # ── Infrastructure ───────────────────────────────────────
    postgres_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres"
                "@localhost:5432/a2a_marketplace"
    )
    redis_url: str = Field(default="redis://localhost:6379")

    # ── Service Ports ────────────────────────────────────────
    registry_port: int = Field(default=9000)
    orchestrator_port: int = Field(default=8000)
    web_search_agent_port: int = Field(default=8001)
    data_analysis_agent_port: int = Field(default=8002)
    document_agent_port: int = Field(default=8003)
    code_agent_port: int = Field(default=8004)

    # ── Security ─────────────────────────────────────────────
    jwt_secret_key: str = Field(
        default="dev-secret-change-in-production"
    )
    a2a_bearer_token: str = Field(
        default="dev-bearer-token"
    )

    # ── App ──────────────────────────────────────────────────
    environment: str = Field(default="development")
    log_level: str = Field(default="DEBUG")
    agent_name: str = Field(default="unknown-agent")


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()