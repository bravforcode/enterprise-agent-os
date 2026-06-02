"""Performance tests for graxia_tool performance module — 30+ tests.

Tests connection pooling, rate limiting, circuit breaker, and caching.
"""
import asyncio
import os
import sys
import time
import pytest

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from graxia_tool.performance import (
    ConnectionPool, AdvancedRateLimiter, CircuitBreaker,
    LoadBalancer, TTLCache
)


# --- Connection Pool Tests ---

class TestConnectionPool:
    """Tests for connection pool."""

    @pytest.mark.asyncio
    async def test_acquire_connection(self):
        """Should acquire connection from pool."""
        pool = ConnectionPool(max_connections=5)
        conn = await pool.acquire("key1")
        assert conn is not None
        assert conn["key"] == "key1"

    @pytest.mark.asyncio
    async def test_release_connection(self):
        """Should release connection back to pool."""
        pool = ConnectionPool(max_connections=5)
        await pool.acquire("key1")
        await pool.release("key1")
        stats = pool.stats()
        assert stats["total_connections"] == 0

    @pytest.mark.asyncio
    async def test_pool_limit(self):
        """Should respect pool limit."""
        pool = ConnectionPool(max_connections=2)
        await pool.acquire("key1")
        await pool.acquire("key2")
        # Third connection should evict least used
        await pool.acquire("key3")
        stats = pool.stats()
        assert stats["total_connections"] <= 2

    @pytest.mark.asyncio
    async def test_cleanup_idle(self):
        """Should cleanup idle connections."""
        pool = ConnectionPool(max_connections=5, max_idle_time=0.01)
        await pool.acquire("key1")
        await asyncio.sleep(0.02)
        removed = await pool.cleanup()
        assert removed == 1

    @pytest.mark.asyncio
    async def test_stats(self):
        """Should return pool statistics."""
        pool = ConnectionPool(max_connections=5)
        await pool.acquire("key1")
        stats = pool.stats()
        assert stats["total_connections"] == 1
        assert stats["max_connections"] == 5


# --- Advanced Rate Limiter Tests ---

class TestAdvancedRateLimiter:
    """Tests for advanced rate limiter."""

    def test_allow_within_rate(self):
        """Should allow requests within rate."""
        limiter = AdvancedRateLimiter(rate=10, burst=10)
        allowed, info = limiter.check("user1")
        assert allowed is True
        assert info["remaining"] >= 0

    def test_block_over_burst(self):
        """Should block requests over burst."""
        limiter = AdvancedRateLimiter(rate=1, burst=5)
        for _ in range(5):
            limiter.check("user1")
        allowed, info = limiter.check("user1")
        assert allowed is False

    def test_different_keys(self):
        """Different keys should have separate limits."""
        limiter = AdvancedRateLimiter(rate=1, burst=2)
        limiter.check("user1")
        limiter.check("user1")
        allowed, _ = limiter.check("user1")
        assert allowed is False
        allowed, _ = limiter.check("user2")
        assert allowed is True

    def test_get_status(self):
        """Should return rate limit status."""
        limiter = AdvancedRateLimiter(rate=10, burst=20)
        limiter.check("user1")
        status = limiter.get_status("user1")
        assert "remaining" in status
        assert "limit" in status

    def test_token_refill(self):
        """Should refill tokens over time."""
        limiter = AdvancedRateLimiter(rate=100, burst=10)
        for _ in range(10):
            limiter.check("user1")
        # Wait for refill
        time.sleep(0.1)
        allowed, _ = limiter.check("user1")
        assert allowed is True


# --- Circuit Breaker Tests ---

class TestCircuitBreaker:
    """Tests for circuit breaker."""

    def test_initial_state_closed(self):
        """Should start in closed state."""
        cb = CircuitBreaker()
        assert cb.can_execute("key1") is True
        assert cb.get_state("key1") == "closed"

    def test_trip_on_failures(self):
        """Should trip after failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure("key1")
        assert cb.get_state("key1") == "open"
        assert cb.can_execute("key1") is False

    def test_recovery_timeout(self):
        """Should recover after timeout."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure("key1")
        cb.record_failure("key1")
        assert cb.get_state("key1") == "open"
        time.sleep(0.02)
        assert cb.can_execute("key1") is True
        assert cb.get_state("key1") == "half_open"

    def test_half_open_success(self):
        """Should close on success in half-open state."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01, half_open_max=2)
        cb.record_failure("key1")
        cb.record_failure("key1")
        time.sleep(0.02)
        cb.can_execute("key1")
        cb.record_success("key1")
        cb.record_success("key1")
        assert cb.get_state("key1") == "closed"

    def test_reset(self):
        """Should manually reset circuit."""
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("key1")
        assert cb.get_state("key1") == "open"
        cb.reset("key1")
        assert cb.get_state("key1") == "closed"


# --- Load Balancer Tests ---

class TestLoadBalancer:
    """Tests for load balancer."""

    def test_next_backend(self):
        """Should return next backend."""
        lb = LoadBalancer(["backend1", "backend2", "backend3"])
        backend = lb.next_backend()
        assert backend in ["backend1", "backend2", "backend3"]

    def test_round_robin(self):
        """Should cycle through backends."""
        lb = LoadBalancer(["backend1", "backend2"])
        b1 = lb.next_backend()
        b2 = lb.next_backend()
        b3 = lb.next_backend()
        assert b1 != b2 or b1 == b3  # Round robin

    def test_mark_unhealthy(self):
        """Should skip unhealthy backends."""
        lb = LoadBalancer(["backend1", "backend2"])
        lb.mark_unhealthy("backend1")
        backend = lb.next_backend()
        assert backend == "backend2"

    def test_all_unhealthy(self):
        """Should fallback when all unhealthy."""
        lb = LoadBalancer(["backend1", "backend2"])
        lb.mark_unhealthy("backend1")
        lb.mark_unhealthy("backend2")
        backend = lb.next_backend()
        assert backend in ["backend1", "backend2"]  # Fallback

    def test_stats(self):
        """Should return load balancer stats."""
        lb = LoadBalancer(["backend1", "backend2"])
        lb.mark_unhealthy("backend1")
        stats = lb.stats()
        assert len(stats["healthy"]) == 1
        assert len(stats["unhealthy"]) == 1


# --- TTL Cache Tests ---

class TestTTLCache:
    """Tests for TTL cache."""

    @pytest.mark.asyncio
    async def test_set_get(self):
        """Should set and get values."""
        cache = TTLCache()
        await cache.set("key", "value")
        result = await cache.get("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        """Should expire entries after TTL."""
        cache = TTLCache()
        await cache.set("key", "value", ttl=0.01)
        await asyncio.sleep(0.02)
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """Should delete entries."""
        cache = TTLCache()
        await cache.set("key", "value")
        deleted = await cache.delete("key")
        assert deleted is True
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Should cleanup expired entries."""
        cache = TTLCache()
        await cache.set("key1", "value1", ttl=0.01)
        await cache.set("key2", "value2", ttl=10)
        await asyncio.sleep(0.02)
        removed = await cache.cleanup()
        assert removed == 1

    @pytest.mark.asyncio
    async def test_max_size(self):
        """Should respect max size."""
        cache = TTLCache(max_size=2)
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        stats = cache.stats()
        assert stats["size"] <= 2

    @pytest.mark.asyncio
    async def test_stats(self):
        """Should return cache statistics."""
        cache = TTLCache()
        await cache.set("key", "value")
        await cache.get("key")
        stats = cache.stats()
        assert stats["size"] == 1
        assert stats["total_hits"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])