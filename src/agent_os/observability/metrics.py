"""Enterprise Agent OS — Observability Module.

Metrics collection, alerting, tracing.
"""
from __future__ import annotations
import time
import json
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional
from ..core.logging import get_logger

logger = get_logger("observability")


@dataclass
class Metric:
    """A single metric value."""
    name: str
    value: float
    timestamp: datetime
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class Alert:
    """An alert triggered by a metric threshold."""
    name: str
    severity: str  # "info", "warning", "critical"
    message: str
    timestamp: datetime
    metric_name: str
    metric_value: float
    threshold: float


class MetricsCollector:
    """
    Collects and aggregates metrics.
    In-memory storage with optional backend (Prometheus, etc.).
    """

    def __init__(self):
        self.metrics: list[Metric] = []
        self.counters: dict[str, float] = defaultdict(float)
        self.gauges: dict[str, float] = {}
        self.histograms: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: float = 1.0, tags: Optional[dict] = None) -> None:
        """Increment a counter."""
        self.counters[name] += value
        self.metrics.append(Metric(
            name=name,
            value=value,
            timestamp=datetime.utcnow(),
            tags=tags or {},
        ))

    def gauge(self, name: str, value: float, tags: Optional[dict] = None) -> None:
        """Set a gauge value."""
        self.gauges[name] = value
        self.metrics.append(Metric(
            name=name,
            value=value,
            timestamp=datetime.utcnow(),
            tags=tags or {},
        ))

    def histogram(self, name: str, value: float, tags: Optional[dict] = None) -> None:
        """Record a histogram value."""
        self.histograms[name].append(value)
        self.metrics.append(Metric(
            name=name,
            value=value,
            timestamp=datetime.utcnow(),
            tags=tags or {},
        ))

    def get_counter(self, name: str) -> float:
        """Get counter value."""
        return self.counters.get(name, 0.0)

    def get_gauge(self, name: str) -> Optional[float]:
        """Get gauge value."""
        return self.gauges.get(name)

    def get_histogram_stats(self, name: str) -> dict[str, float]:
        """Get histogram stats."""
        values = self.histograms.get(name, [])
        if not values:
            return {}
        sorted_v = sorted(values)
        n = len(sorted_v)
        return {
            "count": n,
            "min": min(sorted_v),
            "max": max(sorted_v),
            "mean": sum(sorted_v) / n,
            "p50": sorted_v[min(n // 2, n - 1)],
            "p95": sorted_v[min(int(n * 0.95), n - 1)],
            "p99": sorted_v[min(int(n * 0.99), n - 1)],
        }

    def time_ms(self, name: str, duration_ms: float, tags: Optional[dict] = None) -> None:
        """Record a duration metric."""
        self.histogram(f"{name}.duration_ms", duration_ms, tags)


class AlertManager:
    """
    Manages alert rules and triggers.
    """

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics
        self.alerts: list[Alert] = []
        self.rules: list[dict] = []

    def add_rule(
        self,
        name: str,
        metric_name: str,
        threshold: float,
        comparison: str = "above",  # "above", "below", "equals"
        severity: str = "warning",
        message: Optional[str] = None,
    ) -> None:
        """Add an alert rule."""
        self.rules.append({
            "name": name,
            "metric_name": metric_name,
            "threshold": threshold,
            "comparison": comparison,
            "severity": severity,
            "message": message or f"{name}: {metric_name} {comparison} {threshold}",
        })

    def check(self) -> list[Alert]:
        """Check all rules and trigger alerts."""
        new_alerts = []
        for rule in self.rules:
            value = self.metrics.get_gauge(rule["metric_name"])
            if value is None:
                value = self.metrics.get_counter(rule["metric_name"])
            if value is None:
                continue
            triggered = False
            if rule["comparison"] == "above" and value > rule["threshold"]:
                triggered = True
            elif rule["comparison"] == "below" and value < rule["threshold"]:
                triggered = True
            elif rule["comparison"] == "equals" and value == rule["threshold"]:
                triggered = True
            if triggered:
                alert = Alert(
                    name=rule["name"],
                    severity=rule["severity"],
                    message=rule["message"],
                    timestamp=datetime.utcnow(),
                    metric_name=rule["metric_name"],
                    metric_value=value,
                    threshold=rule["threshold"],
                )
                self.alerts.append(alert)
                new_alerts.append(alert)
                logger.warning(
                    "alert_triggered",
                    name=alert.name,
                    severity=alert.severity,
                    value=value,
                    threshold=rule["threshold"],
                )
        return new_alerts

    def get_recent_alerts(self, limit: int = 50) -> list[Alert]:
        """Get recent alerts."""
        return self.alerts[-limit:]


class Tracer:
    """
    Simple span tracer for request tracing.
    """

    def __init__(self):
        self.spans: list[dict] = []
        self._stack: list[dict] = []

    def start_span(self, name: str, tags: Optional[dict] = None) -> dict:
        """Start a new span."""
        span = {
            "id": len(self.spans),
            "name": name,
            "start": time.time(),
            "tags": tags or {},
        }
        self._stack.append(span)
        return span

    def end_span(self, span: dict, tags: Optional[dict] = None) -> None:
        """End a span and record it."""
        span["end"] = time.time()
        span["duration_ms"] = int((span["end"] - span["start"]) * 1000)
        if tags:
            span["tags"].update(tags)
        self.spans.append(span)
        if self._stack and self._stack[-1] is span:
            self._stack.pop()

    def get_trace(self) -> list[dict]:
        """Get all recorded spans."""
        return self.spans
