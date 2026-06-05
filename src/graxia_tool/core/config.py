"""Enterprise Agent OS — Core Configuration (stdlib only, no pydantic)."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    # App
    app_name: str = field(default_factory=lambda: _env("AOS_APP_NAME", "enterprise-agent-os"))
    app_version: str = field(default_factory=lambda: _env("AOS_APP_VERSION", "0.1.0"))
    debug: bool = field(default_factory=lambda: _env_bool("AOS_DEBUG", False))
    environment: str = field(default_factory=lambda: _env("AOS_ENVIRONMENT", "development"))

    # API
    api_host: str = field(default_factory=lambda: _env("AOS_API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: _env_int("AOS_API_PORT", 8000))
    api_workers: int = field(default_factory=lambda: _env_int("AOS_API_WORKERS", 1))

    # Database
    database_url: str = field(default_factory=lambda: _env("AOS_DATABASE_URL", "sqlite+aiosqlite:///graxia.db"))
    database_pool_size: int = field(default_factory=lambda: _env_int("AOS_DATABASE_POOL_SIZE", 5))
    database_max_overflow: int = field(default_factory=lambda: _env_int("AOS_DATABASE_MAX_OVERFLOW", 10))

    # Redis
    redis_url: str = field(default_factory=lambda: _env("AOS_REDIS_URL", "redis://localhost:6379/0"))
    redis_ttl_seconds: int = field(default_factory=lambda: _env_int("AOS_REDIS_TTL_SECONDS", 3600))

    # Auth
    jwt_secret: str = field(default_factory=lambda: _env("AOS_JWT_SECRET", "CHANGE-ME-IN-PRODUCTION"))
    jwt_algorithm: str = field(default_factory=lambda: _env("AOS_JWT_ALGORITHM", "HS256"))
    jwt_expire_minutes: int = field(default_factory=lambda: _env_int("AOS_JWT_EXPIRE_MINUTES", 60))

    # LLM
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_model_router: str = field(default_factory=lambda: _env("AOS_OPENAI_MODEL_ROUTER", "gpt-4o-mini"))
    openai_model_main: str = field(default_factory=lambda: _env("AOS_OPENAI_MODEL_MAIN", "gpt-4o"))
    openai_max_tokens: int = field(default_factory=lambda: _env_int("AOS_OPENAI_MAX_TOKENS", 4096))

    # Logging
    log_level: str = field(default_factory=lambda: _env("AOS_LOG_LEVEL", "INFO"))

    # Governance
    max_concurrent_agents: int = field(default_factory=lambda: _env_int("AOS_MAX_CONCURRENT_AGENTS", 15))


settings = Settings()


# Singleton
settings = Settings()
