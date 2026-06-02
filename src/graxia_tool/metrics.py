"""Prometheus metrics for graxia_tool.

Tracks:
- Request counts per endpoint/agent
- Request duration
- Cost (USD) per call
- Cache hit rate
- Active agents
- Error counts
- Token counts (in/out)
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional

# Try to import prometheus_client, fallback to no-op if not available
try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Summary, generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    class _MetricStub:
        def __init__(self, *args, **kwargs):
            pass
        def inc(self, *args, **kwargs):
            pass
        def dec(self, *args, **kwargs):
            pass
        def set(self, *args, **kwargs):
            pass
        def observe(self, *args, **kwargs):
            pass
        def labels(self, *args, **kwargs):
            return self
        def time(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    Counter = Histogram = Gauge = Summary = _MetricStub
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest():
        return b"# prometheus_client not installed\n"


# --- Metric Definitions ---

# Request counts
REQUEST_COUNT = Counter(
    "graxia_request_total",
    "Total number of requests",
    ["endpoint", "method", "status"],
)

# Request duration
REQUEST_DURATION = Histogram(
    "graxia_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Agent invocations
AGENT_CALLS = Counter(
    "graxia_agent_calls_total",
    "Total agent calls",
    ["agent", "status"],
)

AGENT_DURATION = Histogram(
    "graxia_agent_duration_seconds",
    "Agent execution duration",
    ["agent"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# Cost tracking
COST_USD = Counter(
    "graxia_cost_usd_total",
    "Total cost in USD",
    ["model", "agent"],
)

SAVED_USD = Counter(
    "graxia_saved_usd_total",
    "Total saved via cache/compression",
    ["strategy"],
)

# Token tracking
TOKENS_IN = Counter(
    "graxia_tokens_in_total",
    "Total input tokens",
    ["model", "agent"],
)

TOKENS_OUT = Counter(
    "graxia_tokens_out_total",
    "Total output tokens",
    ["model", "agent"],
)

# Cache metrics
CACHE_HITS = Counter(
    "graxia_cache_hits_total",
    "Cache hits",
    ["cache_type"],  # prompt, semantic, redis
)

CACHE_MISSES = Counter(
    "graxia_cache_misses_total",
    "Cache misses",
    ["cache_type"],
)

# Rate limiting
RATE_LIMITED = Counter(
    "graxia_rate_limited_total",
    "Requests rejected by rate limiter",
    ["user_id", "endpoint"],
)

# Errors
ERRORS = Counter(
    "graxia_errors_total",
    "Total errors",
    ["type", "endpoint"],
)

# Active agents (gauge)
ACTIVE_AGENTS = Gauge(
    "graxia_active_agents",
    "Number of currently active agents",
)

# Audit log entries
AUDIT_EVENTS = Counter(
    "graxia_audit_events_total",
    "Total audit events logged",
    ["event_type", "result"],
)

# Token reduction
TOKEN_REDUCTION_RATIO = Summary(
    "graxia_token_reduction_ratio",
    "Token reduction ratio (saved / original)",
)


# --- Helper Functions ---

def record_request(endpoint: str, method: str, status: int, duration: float):
    """Record HTTP request metrics."""
    REQUEST_COUNT.labels(endpoint=endpoint, method=method, status=str(status)).inc()
    REQUEST_DURATION.labels(endpoint=endpoint, method=method).observe(duration)


def record_agent_call(agent: str, success: bool, duration: float, cost: float = 0.0):
    """Record agent invocation."""
    status = "success" if success else "failure"
    AGENT_CALLS.labels(agent=agent, status=status).inc()
    AGENT_DURATION.labels(agent=agent).observe(duration)
    if cost > 0:
        COST_USD.labels(model="unknown", agent=agent).inc(cost)


def record_tokens(model: str, agent: str, tokens_in: int, tokens_out: int):
    """Record token usage."""
    TOKENS_IN.labels(model=model, agent=agent).inc(tokens_in)
    TOKENS_OUT.labels(model=model, agent=agent).inc(tokens_out)


def record_cache(cache_type: str, hit: bool):
    """Record cache hit/miss."""
    if hit:
        CACHE_HITS.labels(cache_type=cache_type).inc()
    else:
        CACHE_MISSES.labels(cache_type=cache_type).inc()


def record_saved(strategy: str, amount: float):
    """Record savings via optimization strategy."""
    SAVED_USD.labels(strategy=strategy).inc(amount)


def record_error(error_type: str, endpoint: str = "unknown"):
    """Record error."""
    ERRORS.labels(type=error_type, endpoint=endpoint).inc()


def record_audit(event_type: str, result: str = "success"):
    """Record audit event."""
    AUDIT_EVENTS.labels(event_type=event_type, result=result).inc()


def record_rate_limited(user_id: str, endpoint: str):
    """Record rate limit hit."""
    RATE_LIMITED.labels(user_id=user_id, endpoint=endpoint).inc()


# --- Context Manager ---

@contextmanager
def track_request(endpoint: str, method: str = "POST"):
    """Context manager to track request duration and status."""
    start = time.time()
    status = 500
    try:
        yield
        status = 200
    except Exception as e:
        record_error(type(e).__name__, endpoint)
        raise
    finally:
        duration = time.time() - start
        record_request(endpoint, method, status, duration)


@contextmanager
def track_agent(agent: str):
    """Context manager to track agent execution."""
    start = time.time()
    success = False
    ACTIVE_AGENTS.inc()
    try:
        yield
        success = True
    except Exception as e:
        record_error(type(e).__name__, f"agent:{agent}")
        raise
    finally:
        duration = time.time() - start
        record_agent_call(agent, success, duration)
        ACTIVE_AGENTS.dec()


# --- Export ---

def metrics_endpoint() -> tuple[bytes, str]:
    """Return Prometheus metrics in expected format."""
    return generate_latest(), CONTENT_TYPE_LATEST


def is_available() -> bool:
    """Check if Prometheus client is available."""
    return PROMETHEUS_AVAILABLE
