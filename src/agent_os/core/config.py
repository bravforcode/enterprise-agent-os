"""Enterprise Agent OS — Core Configuration."""
from __future__ import annotations
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables + .env file."""

    # App
    app_name: str = "enterprise-agent-os"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"  # development, staging, production

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    cors_origins: list[str] = ["http://localhost:3000"]

    # Database (PostgreSQL)
    database_url: str = Field(
        default="postgresql+asyncpg://agent:agent@localhost:5432/agent_os",
        description="Async PostgreSQL connection string",
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_seconds: int = 3600

    # Auth
    jwt_secret: str = Field(default="CHANGE-ME-IN-PRODUCTION", description="JWT signing secret")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    api_key_prefix: str = "aos_"

    # LLM
    openai_api_key: Optional[str] = None
    openai_model_router: str = "gpt-4o-mini"  # Intent classification
    openai_model_main: str = "gpt-4o"  # Main agent
    openai_model_haiku: str = "claude-3-haiku-20240307"  # Fast/cheap
    openai_max_tokens: int = 4096

    # Qdrant (vector DB for memory)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "agent_memory"

    # Skill Router
    skill_router_port: int = 19876
    skill_router_host: str = "127.0.0.1"

    # Token Budget
    token_budget_per_turn: int = 50_000
    token_budget_per_day: int = 1_000_000
    token_cost_per_1k_input: float = 0.005  # GPT-4o-mini
    token_cost_per_1k_output: float = 0.015

    # Observability
    log_level: str = "INFO"
    sentry_dsn: Optional[str] = None
    metrics_port: int = 9090

    # Governance
    approval_required_tools: list[str] = ["database", "production", "deploy"]
    max_concurrent_agents: int = 15
    max_agent_depth: int = 3

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_prefix": "AOS_",
        "case_sensitive": False,
        "extra": "ignore",  # Ignore unknown env vars
    }


# Singleton
settings = Settings()
