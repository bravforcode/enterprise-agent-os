"""Monitoring metrics — aggregated time-series data for charts."""
from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _DataPoint:
    timestamp: float
    value: float
    label: str = ""


@dataclass
class _AgentMetric:
    tokens_over_time: deque = field(default_factory=lambda: deque(maxlen=200))
    cost_over_time: deque = field(default_factory=lambda: deque(maxlen=200))
    latency_over_time: deque = field(default_factory=lambda: deque(maxlen=200))
    runs_by_minute: deque = field(default_factory=lambda: deque(maxlen=120))
    cost_by_agent: dict = field(default_factory=dict)
    tokens_by_agent: dict = field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0


class MonitoringMetrics:
    """Thread-safe metric storage for dashboard charts."""

    def __init__(self, window_minutes: int = 60):
        self._lock = threading.Lock()
        self._window = window_minutes * 60
        self._data = _AgentMetric()
        self._minute_buckets: dict[int, dict] = {}
        self._last_minute: int = 0

    def _now(self) -> float:
        return time.time()

    def _minute_key(self, ts: float) -> int:
        return int(ts // 60)

    def _ensure_minute(self, mk: int) -> None:
        if mk not in self._minute_buckets:
            self._minute_buckets[mk] = {
                "runs": 0,
                "tokens": 0,
                "cost": 0.0,
                "success": 0,
                "failure": 0,
            }

    def record_run(
        self,
        agent_name: str,
        tokens: int,
        cost: float,
        duration_ms: int,
        success: bool,
    ) -> None:
        now = self._now()
        mk = self._minute_key(now)
        with self._lock:
            d = self._data
            d.tokens_over_time.append(_DataPoint(now, tokens, agent_name))
            d.cost_over_time.append(_DataPoint(now, cost, agent_name))
            d.latency_over_time.append(_DataPoint(now, duration_ms, agent_name))
            d.cost_by_agent[agent_name] = d.cost_by_agent.get(agent_name, 0.0) + cost
            d.tokens_by_agent[agent_name] = d.tokens_by_agent.get(agent_name, 0) + tokens
            if success:
                d.success_count += 1
            else:
                d.failure_count += 1
            self._ensure_minute(mk)
            self._minute_buckets[mk]["runs"] += 1
            self._minute_buckets[mk]["tokens"] += tokens
            self._minute_buckets[mk]["cost"] += cost
            if success:
                self._minute_buckets[mk]["success"] += 1
            else:
                self._minute_buckets[mk]["failure"] += 1

    def get_tokens_over_time(self, limit: int = 120) -> list[dict]:
        with self._lock:
            pts = list(self._data.tokens_over_time)[-limit:]
        return [{"timestamp": p.timestamp, "value": p.value, "label": p.label} for p in pts]

    def get_cost_over_time(self, limit: int = 120) -> list[dict]:
        with self._lock:
            pts = list(self._data.cost_over_time)[-limit:]
        return [{"timestamp": p.timestamp, "value": p.value, "label": p.label} for p in pts]

    def get_latency_over_time(self, limit: int = 120) -> list[dict]:
        with self._lock:
            pts = list(self._data.latency_over_time)[-limit:]
        return [{"timestamp": p.timestamp, "value": p.value, "label": p.label} for p in pts]

    def get_cost_by_agent(self) -> dict:
        with self._lock:
            return dict(self._data.cost_by_agent)

    def get_tokens_by_agent(self) -> dict:
        with self._lock:
            return dict(self._data.tokens_by_agent)

    def get_runs_per_minute(self, minutes: int = 30) -> list[dict]:
        now_mk = self._minute_key(self._now())
        with self._lock:
            result = []
            for mk in range(now_mk - minutes + 1, now_mk + 1):
                self._ensure_minute(mk)
                bucket = self._minute_buckets[mk]
                result.append({
                    "minute": mk,
                    "runs": bucket["runs"],
                    "tokens": bucket["tokens"],
                    "cost": bucket["cost"],
                    "success": bucket["success"],
                    "failure": bucket["failure"],
                })
            old_keys = [k for k in self._minute_buckets if k < now_mk - 300]
            for k in old_keys:
                del self._minute_buckets[k]
        return result

    def get_success_rate(self) -> dict:
        with self._lock:
            total = self._data.success_count + self._data.failure_count
        return {
            "success": self._data.success_count,
            "failure": self._data.failure_count,
            "rate": round(self._data.success_count / max(total, 1), 3),
        }


_metrics: Optional[MonitoringMetrics] = None


def get_monitoring_metrics() -> MonitoringMetrics:
    global _metrics
    if _metrics is None:
        _metrics = MonitoringMetrics()
    return _metrics
