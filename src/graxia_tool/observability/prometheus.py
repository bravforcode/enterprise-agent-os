"""Prometheus metrics exporter for Agent OS.

Exposes /metrics endpoint in Prometheus format.
Uses our existing MetricsCollector + adds custom Agent OS metrics.
"""
from __future__ import annotations

from prometheus_client import (
    Counter, Gauge, Histogram, Info, Summary,
    CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
)
from typing import Any

# ============================================================
# Core Agent OS Metrics
# ============================================================

# Run metrics
RUNS_TOTAL = Counter(
    "agentos_runs_total",
    "Total agent runs",
    ["intent", "domain", "status"],
)

RUN_DURATION = Histogram(
    "agentos_run_duration_seconds",
    "Agent run duration",
    ["intent", "domain"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

RUN_TOKENS = Histogram(
    "agentos_run_tokens",
    "Tokens used per run",
    ["model"],
    buckets=(100, 500, 1000, 2000, 5000, 10000, 50000, 100000),
)

RUN_COST = Counter(
    "agentos_run_cost_usd_total",
    "Total cost in USD",
    ["model", "user_id"],
)

# Agent metrics
AGENT_INVOCATIONS = Counter(
    "agentos_agent_invocations_total",
    "Sub-agent invocations",
    ["agent_name", "pattern"],
)

AGENT_DURATION = Histogram(
    "agentos_agent_duration_seconds",
    "Sub-agent execution duration",
    ["agent_name"],
)

AGENT_ERRORS = Counter(
    "agentos_agent_errors_total",
    "Sub-agent errors",
    ["agent_name", "error_type"],
)

# Multi-agent pattern metrics
PATTERN_RUNS = Counter(
    "agentos_pattern_runs_total",
    "Multi-agent pattern runs",
    ["pattern", "status"],
)

PATTERN_AGENTS_USED = Histogram(
    "agentos_pattern_agents_used",
    "Number of agents in pattern",
    ["pattern"],
    buckets=(1, 2, 3, 5, 10, 20, 50),
)

# Token optimization metrics
CACHE_HITS = Counter(
    "agentos_cache_hits_total",
    "Prompt cache hits",
    ["cache_type"],
)

CACHE_MISSES = Counter(
    "agentos_cache_misses_total",
    "Prompt cache misses",
    ["cache_type"],
)

COMPRESSIONS = Counter(
    "agentos_compressions_total",
    "Context compressions",
    ["strategy"],  # lossless, lossy
)

COMPRESSION_RATIO = Histogram(
    "agentos_compression_ratio",
    "Compression ratio (input/output)",
    buckets=(1.0, 1.5, 2.0, 3.0, 5.0, 10.0),
)

# Memory metrics
MEMORY_OPERATIONS = Counter(
    "agentos_memory_operations_total",
    "Memory operations",
    ["layer", "operation"],  # layer: working/short_term/long_term/etc, op: store/recall/forget
)

MEMORY_HITS = Counter(
    "agentos_memory_hits_total",
    "Successful memory recalls",
    ["layer"],
)

# RAG metrics
RAG_QUERIES = Counter(
    "agentos_rag_queries_total",
    "RAG queries",
    ["strategy"],  # bm25/dense/hybrid
)

RAG_RETRIEVAL_LATENCY = Histogram(
    "agentos_rag_retrieval_seconds",
    "RAG retrieval latency",
    ["strategy"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0),
)

RAG_CHUNKS_RETURNED = Histogram(
    "agentos_rag_chunks_returned",
    "Chunks returned per query",
    buckets=(1, 5, 10, 20, 50, 100),
)

# Governance metrics
POLICY_DECISIONS = Counter(
    "agentos_policy_decisions_total",
    "Policy decisions",
    ["decision"],  # allow/deny/require_approval
)

POLICY_VIOLATIONS = Counter(
    "agentos_policy_violations_total",
    "Policy violations",
    ["policy_name", "severity"],
)

# Eval metrics
EVAL_RUNS = Counter(
    "agentos_eval_runs_total",
    "Evaluation runs",
    ["result"],  # pass/fail
)

EVAL_PASS_RATE = Gauge(
    "agentos_eval_pass_rate",
    "Current eval pass rate",
)

# Guardrail metrics
GUARDRAIL_BLOCKS = Counter(
    "agentos_guardrail_blocks_total",
    "Guardrail blocks",
    ["type"],  # injection/pii/harmful
)

GUARDRAIL_WARNINGS = Counter(
    "agentos_guardrail_warnings_total",
    "Guardrail warnings",
    ["type"],
)

# API metrics
API_REQUESTS = Counter(
    "agentos_api_requests_total",
    "API requests",
    ["method", "path", "status"],
)

API_LATENCY = Histogram(
    "agentos_api_latency_seconds",
    "API request latency",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)

# Active sessions
ACTIVE_SESSIONS = Gauge(
    "agentos_active_sessions",
    "Number of active sessions",
)

ACTIVE_RUNS = Gauge(
    "agentos_active_runs",
    "Number of currently running agents",
)

# System info
SYSTEM_INFO = Info(
    "agentos_system",
    "Agent OS system information",
)


# ============================================================
# Helper functions
# ============================================================

def record_run(intent: str, domain: str, status: str, duration: float) -> None:
    """Record a completed run."""
    RUNS_TOTAL.labels(intent=intent, domain=domain, status=status).inc()
    RUN_DURATION.labels(intent=intent, domain=domain).observe(duration)


def record_tokens(model: str, tokens: int) -> None:
    """Record tokens used."""
    RUN_TOKENS.labels(model=model).observe(tokens)


def record_cost(model: str, user_id: str, cost: float) -> None:
    """Record cost incurred."""
    RUN_COST.labels(model=model, user_id=user_id).inc(cost)


def record_agent(agent_name: str, pattern: str, duration: float, success: bool) -> None:
    """Record sub-agent invocation."""
    AGENT_INVOCATIONS.labels(agent_name=agent_name, pattern=pattern).inc()
    AGENT_DURATION.labels(agent_name=agent_name).observe(duration)
    if not success:
        AGENT_ERRORS.labels(agent_name=agent_name, error_type="execution").inc()


def record_pattern(pattern: str, success: bool, agents_used: int) -> None:
    """Record multi-agent pattern run."""
    status = "success" if success else "failure"
    PATTERN_RUNS.labels(pattern=pattern, status=status).inc()
    PATTERN_AGENTS_USED.labels(pattern=pattern).observe(agents_used)


def record_cache(cache_type: str, hit: bool) -> None:
    """Record cache hit/miss."""
    if hit:
        CACHE_HITS.labels(cache_type=cache_type).inc()
    else:
        CACHE_MISSES.labels(cache_type=cache_type).inc()


def record_compression(strategy: str, ratio: float) -> None:
    """Record a compression operation."""
    COMPRESSIONS.labels(strategy=strategy).inc()
    COMPRESSION_RATIO.observe(ratio)


def record_memory(layer: str, operation: str, hit: bool = False) -> None:
    """Record memory operation."""
    MEMORY_OPERATIONS.labels(layer=layer, operation=operation).inc()
    if hit:
        MEMORY_HITS.labels(layer=layer).inc()


def record_rag(strategy: str, latency: float, chunks: int) -> None:
    """Record RAG query."""
    RAG_QUERIES.labels(strategy=strategy).inc()
    RAG_RETRIEVAL_LATENCY.labels(strategy=strategy).observe(latency)
    RAG_CHUNKS_RETURNED.observe(chunks)


def record_policy(decision: str) -> None:
    """Record policy decision."""
    POLICY_DECISIONS.labels(decision=decision).inc()


def record_violation(policy_name: str, severity: str) -> None:
    """Record policy violation."""
    POLICY_VIOLATIONS.labels(policy_name=policy_name, severity=severity).inc()


def record_eval(passed: int, total: int) -> None:
    """Record eval results."""
    rate = passed / total if total > 0 else 0
    EVAL_PASS_RATE.set(rate)
    for _ in range(passed):
        EVAL_RUNS.labels(result="pass").inc()
    for _ in range(total - passed):
        EVAL_RUNS.labels(result="fail").inc()


def record_guardrail(block_type: str, blocked: bool) -> None:
    """Record guardrail action."""
    if blocked:
        GUARDRAIL_BLOCKS.labels(type=block_type).inc()
    else:
        GUARDRAIL_WARNINGS.labels(type=block_type).inc()


def record_api(method: str, path: str, status: int, latency: float) -> None:
    """Record API request."""
    API_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    API_LATENCY.labels(method=method, path=path).observe(latency)


def init_system_info(version: str = "0.1.0") -> None:
    """Initialize system info metric."""
    SYSTEM_INFO.info({
        "version": version,
        "name": "agent-os",
        "phase": "8",
    })


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest()


def get_metrics_content_type() -> str:
    """Get the content type for Prometheus metrics."""
    return CONTENT_TYPE_LATEST
