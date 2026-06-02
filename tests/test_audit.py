"""Tests for audit module — 30+ tests."""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.audit import AuditLogger, AuditEvent, get_audit_logger


# --- Event Tests ---

class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_create_event(self):
        """Should create event with required fields."""
        event = AuditEvent(
            timestamp=time.time(),
            event_type="login",
        )
        assert event.event_type == "login"
        assert event.result == "success"  # default

    def test_event_to_dict(self):
        """Should convert to dict."""
        event = AuditEvent(
            timestamp=12345.0,
            event_type="login",
            user_id="alice",
        )
        d = event.to_dict()
        assert d["event_type"] == "login"
        assert d["user_id"] == "alice"
        assert d["timestamp"] == 12345.0

    def test_event_metadata_default(self):
        """Should default metadata to empty dict."""
        event = AuditEvent(timestamp=1.0, event_type="x")
        assert event.metadata == {}


# --- AuditLogger Basic Tests ---

class TestAuditLoggerBasic:
    """Tests for basic AuditLogger operations."""

    def test_log_event(self):
        """Should log event."""
        logger = AuditLogger()
        event = logger.log("login", user_id="alice")
        assert event.event_type == "login"
        assert event.user_id == "alice"
        assert len(logger._events) == 1

    def test_log_multiple_events(self):
        """Should log multiple events."""
        logger = AuditLogger()
        for i in range(5):
            logger.log("test", user_id=f"user{i}")
        assert len(logger._events) == 5

    def test_log_with_all_fields(self):
        """Should log with all fields."""
        logger = AuditLogger()
        event = logger.log(
            event_type="agent_run",
            user_id="alice",
            tenant_id="acme",
            resource="coder",
            action="run",
            result="success",
            ip_address="127.0.0.1",
            metadata={"tokens": 100},
        )
        assert event.user_id == "alice"
        assert event.tenant_id == "acme"
        assert event.resource == "coder"
        assert event.metadata["tokens"] == 100


# --- Query Tests ---

class TestAuditQuery:
    """Tests for query operations."""

    def test_query_by_type(self):
        """Should filter by event type."""
        logger = AuditLogger()
        logger.log("login", user_id="alice")
        logger.log("logout", user_id="alice")
        logger.log("login", user_id="bob")
        result = logger.query(event_type="login")
        assert len(result) == 2

    def test_query_by_user(self):
        """Should filter by user."""
        logger = AuditLogger()
        logger.log("login", user_id="alice")
        logger.log("login", user_id="bob")
        result = logger.query(user_id="alice")
        assert len(result) == 1
        assert result[0].user_id == "alice"

    def test_query_with_limit(self):
        """Should respect limit."""
        logger = AuditLogger()
        for i in range(10):
            logger.log("test", user_id=f"u{i}")
        result = logger.query(limit=5)
        assert len(result) == 5

    def test_query_by_time(self):
        """Should filter by timestamp."""
        logger = AuditLogger()
        logger.log("old", user_id="alice")  # timestamp set at log time
        time.sleep(0.01)
        cutoff = time.time()
        time.sleep(0.01)
        logger.log("new", user_id="alice")
        result = logger.query(since_timestamp=cutoff)
        assert len(result) == 1
        assert result[0].event_type == "new"

    def test_query_combined_filters(self):
        """Should combine filters."""
        logger = AuditLogger()
        logger.log("login", user_id="alice")
        logger.log("login", user_id="bob")
        logger.log("logout", user_id="alice")
        result = logger.query(event_type="login", user_id="alice")
        assert len(result) == 1


# --- Stats Tests ---

class TestAuditStats:
    """Tests for stats."""

    def test_stats_empty(self):
        """Empty logger should have zero stats."""
        logger = AuditLogger()
        stats = logger.get_stats()
        assert stats["total"] == 0

    def test_stats_counts(self):
        """Should count events by type and result."""
        logger = AuditLogger()
        logger.log("login", user_id="alice", result="success")
        logger.log("login", user_id="bob", result="failure")
        logger.log("logout", user_id="alice")
        stats = logger.get_stats()
        assert stats["total"] == 3
        assert stats["by_type"]["login"] == 2
        assert stats["by_type"]["logout"] == 1
        assert stats["by_result"]["success"] == 2
        assert stats["by_result"]["failure"] == 1


# --- Memory Limit Tests ---

class TestMemoryLimit:
    """Tests for memory limit."""

    def test_max_memory_enforced(self):
        """Should enforce max memory limit."""
        logger = AuditLogger(max_memory=5)
        for i in range(10):
            logger.log("test", user_id=f"u{i}")
        assert len(logger._events) == 5
        # Most recent 5 events should remain
        assert logger._events[-1].user_id == "u9"

    def test_clear(self):
        """Should clear events."""
        logger = AuditLogger()
        logger.log("test", user_id="alice")
        logger.clear()
        assert len(logger._events) == 0


# --- Singleton Tests ---

class TestSingleton:
    """Tests for singleton."""

    def test_get_audit_logger_singleton(self):
        """Should return same instance."""
        l1 = get_audit_logger()
        l2 = get_audit_logger()
        assert l1 is l2


# --- Common Event Types Tests ---

class TestCommonEvents:
    """Tests for common audit event patterns."""

    def test_login_logout(self):
        """Should handle login/logout pattern."""
        logger = AuditLogger()
        logger.log("login", user_id="alice", ip_address="1.2.3.4")
        logger.log("logout", user_id="alice")

        logins = logger.query(event_type="login")
        logouts = logger.query(event_type="logout")
        assert len(logins) == 1
        assert len(logouts) == 1

    def test_security_event(self):
        """Should handle security events."""
        logger = AuditLogger()
        logger.log(
            "secret_detected",
            user_id="alice",
            resource="agent_run",
            result="blocked",
            metadata={"secret_type": "openai_key"},
        )
        event = logger._events[0]
        assert event.result == "blocked"
        assert event.metadata["secret_type"] == "openai_key"

    def test_cost_event(self):
        """Should handle cost events."""
        logger = AuditLogger()
        logger.log(
            "cost_alert",
            user_id="alice",
            resource="agent_run",
            metadata={"cost_usd": 1.50, "threshold": 1.00},
        )
        event = logger._events[0]
        assert event.metadata["cost_usd"] == 1.50

    def test_rate_limit_event(self):
        """Should handle rate limit events."""
        logger = AuditLogger()
        logger.log(
            "rate_limited",
            user_id="alice",
            resource="/api/agent",
            result="blocked",
        )
        event = logger._events[0]
        assert event.result == "blocked"

    def test_access_denied(self):
        """Should handle access denied."""
        logger = AuditLogger()
        logger.log(
            "access_denied",
            user_id="bob",
            tenant_id="acme",
            resource="/admin",
            result="blocked",
        )
        event = logger._events[0]
        assert event.event_type == "access_denied"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
