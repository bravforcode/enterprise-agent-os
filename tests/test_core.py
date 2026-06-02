"""Enterprise Agent OS — Basic tests."""
import pytest
from agent_os.core.config import Settings


def test_settings_defaults():
    """Settings load with defaults."""
    s = Settings()
    assert s.app_name == "enterprise-agent-os"
    assert s.app_version == "0.1.0"
    assert s.api_port == 8000
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url.startswith("redis://")
    assert s.jwt_algorithm == "HS256"


def test_settings_env_prefix():
    """Settings respect AOS_ env prefix."""
    import os
    os.environ["AOS_DEBUG"] = "true"
    os.environ["AOS_LOG_LEVEL"] = "DEBUG"
    s = Settings()
    assert s.debug is True
    assert s.log_level == "DEBUG"
    del os.environ["AOS_DEBUG"]
    del os.environ["AOS_LOG_LEVEL"]


def test_risk_levels():
    """Risk levels are defined."""
    from agent_os.core.models import RiskLevel
    assert RiskLevel.LOW == "low"
    assert RiskLevel.HIGH == "high"
    assert RiskLevel.CRITICAL == "critical"


def test_run_statuses():
    """Run statuses are defined."""
    from agent_os.core.models import RunStatus
    assert RunStatus.PENDING == "pending"
    assert RunStatus.RUNNING == "running"
    assert RunStatus.SUCCESS == "success"
    assert RunStatus.AWAITING_APPROVAL == "awaiting_approval"
