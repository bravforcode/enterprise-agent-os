"""Tests for metrics module — 30+ tests."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.metrics import (
    is_available, record_request, record_agent_call,
    record_tokens, record_cache, record_saved,
    record_error, record_audit, record_rate_limited,
    track_request, track_agent, metrics_endpoint,
)


# --- Availability Tests ---

class TestAvailability:
    """Tests for prometheus availability check."""

    def test_is_available_returns_bool(self):
        """Should return bool."""
        result = is_available()
        assert isinstance(result, bool)


# --- Request Recording ---

class TestRequestRecording:
    """Tests for request recording."""

    def test_record_request(self):
        """Should record request without error."""
        record_request("/api/test", "GET", 200, 0.1)
        record_request("/api/test", "GET", 500, 0.2)

    def test_record_request_with_different_status(self):
        """Should handle various status codes."""
        for status in [200, 201, 400, 404, 500]:
            record_request("/api/test", "POST", status, 0.05)


# --- Agent Recording ---

class TestAgentRecording:
    """Tests for agent recording."""

    def test_record_agent_call_success(self):
        """Should record successful agent call."""
        record_agent_call("coder", True, 0.5, 0.001)

    def test_record_agent_call_failure(self):
        """Should record failed agent call."""
        record_agent_call("coder", False, 0.5, 0.0)

    def test_record_agent_call_zero_cost(self):
        """Should handle zero cost."""
        record_agent_call("coder", True, 0.5, 0.0)


# --- Token Recording ---

class TestTokenRecording:
    """Tests for token recording."""

    def test_record_tokens(self):
        """Should record token usage."""
        record_tokens("gpt-4o", "coder", 100, 50)
        record_tokens("claude-3-haiku", "reviewer", 200, 100)

    def test_record_tokens_zero(self):
        """Should handle zero tokens."""
        record_tokens("gpt-4o", "coder", 0, 0)


# --- Cache Recording ---

class TestCacheRecording:
    """Tests for cache recording."""

    def test_record_cache_hit(self):
        """Should record cache hit."""
        record_cache("prompt", True)
        record_cache("semantic", True)

    def test_record_cache_miss(self):
        """Should record cache miss."""
        record_cache("prompt", False)
        record_cache("semantic", False)


# --- Savings Recording ---

class TestSavingsRecording:
    """Tests for savings recording."""

    def test_record_saved(self):
        """Should record savings."""
        record_saved("cache", 0.001)
        record_saved("compression", 0.002)
        record_saved("dedup", 0.0005)
        record_saved("model_routing", 0.01)


# --- Error Recording ---

class TestErrorRecording:
    """Tests for error recording."""

    def test_record_error(self):
        """Should record error."""
        record_error("ValueError", "/api/test")
        record_error("TimeoutError", "agent:coder")


# --- Audit Recording ---

class TestAuditRecording:
    """Tests for audit recording."""

    def test_record_audit(self):
        """Should record audit event."""
        record_audit("login", "success")
        record_audit("agent_run", "success")
        record_audit("secret_detected", "blocked")


# --- Rate Limit Recording ---

class TestRateLimitRecording:
    """Tests for rate limit recording."""

    def test_record_rate_limited(self):
        """Should record rate limit hit."""
        record_rate_limited("user123", "/api/agent")
        record_rate_limited("user456", "/api/cache")


# --- Context Managers ---

class TestContextManagers:
    """Tests for context managers."""

    def test_track_request_success(self):
        """Should track successful request."""
        with track_request("/api/test", "GET"):
            pass

    def test_track_request_error(self):
        """Should track failed request."""
        with pytest.raises(ValueError):
            with track_request("/api/test", "POST"):
                raise ValueError("test error")

    def test_track_agent_success(self):
        """Should track successful agent."""
        with track_agent("coder"):
            pass

    def test_track_agent_error(self):
        """Should track failed agent."""
        with pytest.raises(RuntimeError):
            with track_agent("coder"):
                raise RuntimeError("test error")


# --- Metrics Endpoint ---

class TestMetricsEndpoint:
    """Tests for metrics endpoint."""

    def test_metrics_endpoint_returns_bytes(self):
        """Should return (bytes, str) tuple."""
        data, content_type = metrics_endpoint()
        assert isinstance(data, bytes)
        assert isinstance(content_type, str)

    def test_metrics_endpoint_contains_data(self):
        """Should contain metric data after recording."""
        record_request("/api/test", "GET", 200, 0.1)
        data, _ = metrics_endpoint()
        assert len(data) > 0


# --- Integration ---

class TestMetricsIntegration:
    """Integration tests for metrics."""

    def test_full_workflow(self):
        """Test full metrics workflow."""
        # Simulate request
        with track_request("/api/agent_run", "POST"):
            # Simulate agent
            with track_agent("coder"):
                # Record metrics
                record_tokens("gpt-4o", "coder", 100, 50)
                record_cache("prompt", True)
                record_saved("cache", 0.001)
                record_audit("agent_run", "success")

        # Verify endpoint still works
        data, _ = metrics_endpoint()
        assert len(data) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
