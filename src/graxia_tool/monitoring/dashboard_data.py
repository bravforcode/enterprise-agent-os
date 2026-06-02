"""Dashboard data — API response formatters for monitoring endpoints."""
from __future__ import annotations

from typing import Optional

from .agent_tracker import get_tracker
from .metrics_collector import get_monitoring_metrics


def get_activity_feed(
    limit: int = 100,
    agent: Optional[str] = None,
) -> dict:
    """Get recent agent activity events for the live feed."""
    tracker = get_tracker()
    events = tracker.get_events(limit=limit, agent_filter=agent)
    return {
        "events": events,
        "count": len(events),
    }


def get_metrics_summary() -> dict:
    """Get aggregated metrics for dashboard charts."""
    tracker = get_tracker()
    metrics = get_monitoring_metrics()
    return {
        "summary": tracker.get_summary(),
        "cost_by_agent": metrics.get_cost_by_agent(),
        "tokens_by_agent": metrics.get_tokens_by_agent(),
        "success_rate": metrics.get_success_rate(),
        "tokens_over_time": metrics.get_tokens_over_time(limit=120),
        "cost_over_time": metrics.get_cost_over_time(limit=120),
        "latency_over_time": metrics.get_latency_over_time(limit=120),
        "runs_per_minute": metrics.get_runs_per_minute(minutes=30),
    }


def get_agent_statuses() -> dict:
    """Get current status of all tracked agents."""
    tracker = get_tracker()
    return {
        "agents": tracker.get_agent_states(),
        "count": len(tracker.get_agent_states()),
    }
