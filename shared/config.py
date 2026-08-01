# shared/config.py
"""
Central configuration using pydantic-settings.
Automatically reads from .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────
    google_api_key: str = Field(..., env="GOOGLE_API_KEY")
    
    # ── Search ─────────────────────────────────────
    google_search_engine_id: str | None = Field(
        None, env="GOOGLE_SEARCH_ENGINE_ID"
    )
    
    # ── Infrastructure ──────────────────────────────
    postgres_url: str = Field(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/a2a_marketplace",
        env="POSTGRES_URL"
    )
    redis_url: str = Field("redis://localhost:6379", env="REDIS_URL")
    
    # ── Service URLs ────────────────────────────────
    registry_port: int = Field(9000, env="REGISTRY_PORT")
    orchestrator_port: int = Field(8000, env="ORCHESTRATOR_PORT")
    web_search_agent_port: int = Field(8001, env="WEB_SEARCH_AGENT_PORT")
    data_analysis_agent_port: int = Field(8002, env="DATA_ANALYSIS_AGENT_PORT")
    document_agent_port: int = Field(8003, env="DOCUMENT_AGENT_PORT")
    code_agent_port: int = Field(8004, env="CODE_AGENT_PORT")
    
    # ── Security ────────────────────────────────────
    jwt_secret_key: str = Field(..., env="JWT_SECRET_KEY")
    a2a_bearer_token: str = Field(..., env="A2A_BEARER_TOKEN")
    
    # ── App ─────────────────────────────────────────
    environment: str = Field("development", env="ENVIRONMENT")
    log_level: str = Field("DEBUG", env="LOG_LEVEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Singleton instance
settings = Settings()