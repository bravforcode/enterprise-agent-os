"""Performance optimizations for graxia_tool — async, connection pooling, rate limiting.

This module provides:
1. Async connection pooling
2. Rate limiting
3. Caching
4. Circuit breaker
5. Load balancing
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import defaultdict


# --- Connection Pool ---

class ConnectionPool:
    """Async connection pool for managing connections."""
    
    def __init__(self, max_connections: int = 10, max_idle_time: float = 300.0):
        self.max_connections = max_connections
        self.max_idle_time = max_idle_time
        self._connections: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._usage: dict[str, int] = defaultdict(int)
    
    async def acquire(self, key: str) -> Any:
        """Acquire a connection from the pool."""
        async with self._lock:
            if key in self._connections:
                self._usage[key] += 1
                return self._connections[key]
            
            if len(self._connections) >= self.max_connections:
                # Remove least used connection
                least_used = min(self._usage, key=self._usage.get)
                del self._connections[least_used]
                del self._usage[least_used]
            
            # Create new connection
            connection = {"key": key, "created_at": time.time()}
            self._connections[key] = connection
            self._usage[key] = 1
            return connection
    
    async def release(self, key: str) -> None:
        """Release a connection back to the pool."""
        async with self._lock:
            if key in self._usage:
                self._usage[key] -= 1
                if self._usage[key] <= 0:
                    del self._connections[key]
                    del self._usage[key]
    
    async def cleanup(self) -> int:
        """Remove idle connections."""
        async with self._lock:
            now = time.time()
            to_remove = [
                key for key, conn in self._connections.items()
                if now - conn["created_at"] > self.max_idle_time
            ]
            for key in to_remove:
                del self._connections[key]
                del self._usage[key]
            return len(to_remove)
    
    def stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        return {
            "total_connections": len(self._connections),
            "max_connections": self.max_connections,
            "usage": dict(self._usage),
        }


# --- Advanced Rate Limiter ---

class AdvancedRateLimiter:
    """Token bucket rate limiter with burst support."""
    
    def __init__(
        self,
        rate: float = 10.0,  # requests per second
        burst: int = 20,  # max burst size
        window_seconds: float = 60.0,
    ):
        self.rate = rate
        self.burst = burst
        self.window_seconds = window_seconds
        self._buckets: dict[str, dict[str, Any]] = {}
    
    def _get_bucket(self, key: str) -> dict[str, Any]:
        """Get or create token bucket for key."""
        now = time.time()
        
        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": self.burst,
                "last_refill": now,
                "requests": [],
            }
        
        bucket = self._buckets[key]
        
        # Refill tokens
        elapsed = now - bucket["last_refill"]
        new_tokens = elapsed * self.rate
        bucket["tokens"] = min(self.burst, bucket["tokens"] + new_tokens)
        bucket["last_refill"] = now
        
        # Clean old requests
        cutoff = now - self.window_seconds
        bucket["requests"] = [t for t in bucket["requests"] if t > cutoff]
        
        return bucket
    
    def check(self, key: str) -> tuple[bool, dict[str, Any]]:
        """Check if request is allowed."""
        bucket = self._get_bucket(key)
        
        # Check token bucket
        if bucket["tokens"] < 1:
            return False, {
                "remaining": 0,
                "retry_after": 1.0 / self.rate,
                "limit": self.burst,
                "window": self.window_seconds,
            }
        
        # Consume token
        bucket["tokens"] -= 1
        bucket["requests"].append(time.time())
        
        return True, {
            "remaining": int(bucket["tokens"]),
            "retry_after": 0,
            "limit": self.burst,
            "window": self.window_seconds,
        }
    
    def get_status(self, key: str) -> dict[str, Any]:
        """Get rate limit status."""
        bucket = self._get_bucket(key)
        return {
            "remaining": int(bucket["tokens"]),
            "limit": self.burst,
            "window": self.window_seconds,
            "requests_in_window": len(bucket["requests"]),
        }


# --- Circuit Breaker ---

class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._state: dict[str, dict[str, Any]] = {}
    
    def _get_state(self, key: str) -> dict[str, Any]:
        """Get or create circuit state."""
        if key not in self._state:
            self._state[key] = {
                "state": "closed",  # closed, open, half_open
                "failures": 0,
                "successes": 0,
                "last_failure_time": 0,
                "half_open_count": 0,
            }
        return self._state[key]
    
    def can_execute(self, key: str) -> bool:
        """Check if execution is allowed."""
        state = self._get_state(key)
        
        if state["state"] == "closed":
            return True
        
        if state["state"] == "open":
            # Check if recovery timeout has passed
            if time.time() - state["last_failure_time"] > self.recovery_timeout:
                state["state"] = "half_open"
                state["half_open_count"] = 0
                return True
            return False
        
        if state["state"] == "half_open":
            return state["half_open_count"] < self.half_open_max
        
        return False
    
    def record_success(self, key: str) -> None:
        """Record successful execution."""
        state = self._get_state(key)
        
        if state["state"] == "half_open":
            state["successes"] += 1
            if state["successes"] >= self.half_open_max:
                # Reset circuit
                state["state"] = "closed"
                state["failures"] = 0
                state["successes"] = 0
        elif state["state"] == "closed":
            state["failures"] = 0
    
    def record_failure(self, key: str) -> None:
        """Record failed execution."""
        state = self._get_state(key)
        state["failures"] += 1
        state["last_failure_time"] = time.time()
        
        if state["state"] == "half_open":
            # Trip circuit again
            state["state"] = "open"
        elif state["failures"] >= self.failure_threshold:
            # Trip circuit
            state["state"] = "open"
    
    def get_state(self, key: str) -> str:
        """Get current circuit state."""
        return self._get_state(key)["state"]
    
    def reset(self, key: str) -> None:
        """Manually reset circuit."""
        if key in self._state:
            del self._state[key]


# --- Load Balancer ---

class LoadBalancer:
    """Simple round-robin load balancer."""
    
    def __init__(self, backends: list[str]):
        self.backends = backends
        self._current = 0
        self._health: dict[str, bool] = {b: True for b in backends}
    
    def next_backend(self) -> str:
        """Get next healthy backend."""
        attempts = 0
        while attempts < len(self.backends):
            backend = self.backends[self._current % len(self.backends)]
            self._current += 1
            if self._health.get(backend, False):
                return backend
            attempts += 1
        
        # Fallback to first backend
        return self.backends[0]
    
    def mark_healthy(self, backend: str) -> None:
        """Mark backend as healthy."""
        self._health[backend] = True
    
    def mark_unhealthy(self, backend: str) -> None:
        """Mark backend as unhealthy."""
        self._health[backend] = False
    
    def stats(self) -> dict[str, Any]:
        """Get load balancer stats."""
        return {
            "backends": self.backends,
            "healthy": [b for b in self.backends if self._health.get(b, False)],
            "unhealthy": [b for b in self.backends if not self._health.get(b, False)],
        }


# --- Cache with TTL ---

class TTLCache:
    """In-memory cache with TTL support."""
    
    def __init__(self, max_size: int = 1000, default_ttl: float = 3600.0):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            if time.time() > entry["expires_at"]:
                del self._cache[key]
                return None
            
            entry["hits"] += 1
            return entry["value"]
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ) -> None:
        """Set value in cache."""
        async with self._lock:
            # Evict if full
            if len(self._cache) >= self.max_size and key not in self._cache:
                # Remove least recently used
                lru_key = min(
                    self._cache,
                    key=lambda k: self._cache[k]["last_access"]
                )
                del self._cache[lru_key]
            
            self._cache[key] = {
                "value": value,
                "expires_at": time.time() + (ttl or self.default_ttl),
                "last_access": time.time(),
                "hits": 0,
            }
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def cleanup(self) -> int:
        """Remove expired entries."""
        async with self._lock:
            now = time.time()
            to_remove = [
                key for key, entry in self._cache.items()
                if now > entry["expires_at"]
            ]
            for key in to_remove:
                del self._cache[key]
            return len(to_remove)
    
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_hits = sum(e["hits"] for e in self._cache.values())
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "total_hits": total_hits,
        }