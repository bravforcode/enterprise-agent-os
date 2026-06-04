"""SONA-lite: self-organizing learning via (intent, agent) → success_rate table.

Tracks per-intent, per-agent rolling success rate and a fast/slow EMA pair.
Persistence: JSON file at ~/.graxia/sona/data.json

API:
- SONA().record(intent, agent, success, duration_ms)
- SONA().suggest(intent, candidates) -> best agent
- SONA().stats() -> aggregate stats
- SONA().reset()

The Smoothing-Inc (fast) / Smoothing-Out (slow) EMA pair is a SONA-lite
approximation — enough to bias agent selection without a full reinforcement
loop.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DATA_DIR = Path.home() / ".graxia" / "sona"
DEFAULT_DATA_FILE = DEFAULT_DATA_DIR / "data.json"

# EMA smoothing
ALPHA_FAST = 0.4
ALPHA_SLOW = 0.05
# Minimum samples before we trust the score
MIN_SAMPLES = 3
# Weight for time-based tie-breaking (lower duration = better)
DURATION_WEIGHT = 0.1


@dataclass
class AgentStats:
    agent: str
    samples: int = 0
    successes: int = 0
    failures: int = 0
    ema_fast: float = 0.5  # exponential moving average (fast)
    ema_slow: float = 0.5  # exponential moving average (slow)
    avg_duration_ms: float = 0.0

    def update(self, success: bool, duration_ms: float) -> None:
        target = 1.0 if success else 0.0
        self.ema_fast = ALPHA_FAST * target + (1 - ALPHA_FAST) * self.ema_fast
        self.ema_slow = ALPHA_SLOW * target + (1 - ALPHA_SLOW) * self.ema_slow
        self.samples += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1
        # Running mean of duration
        if self.samples == 1:
            self.avg_duration_ms = float(duration_ms)
        else:
            self.avg_duration_ms = (
                self.avg_duration_ms * (self.samples - 1) + duration_ms
            ) / self.samples

    def score(self) -> float:
        """Combined score: favor fast-EMA, blend with duration, floor for new."""
        if self.samples < MIN_SAMPLES:
            return 0.5  # neutral prior
        duration_penalty = DURATION_WEIGHT * min(self.avg_duration_ms / 1000.0, 1.0)
        return max(0.0, min(1.0, self.ema_fast - duration_penalty))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "samples": self.samples,
            "successes": self.successes,
            "failures": self.failures,
            "ema_fast": round(self.ema_fast, 4),
            "ema_slow": round(self.ema_slow, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "score": round(self.score(), 4),
        }


class SONA:
    """In-memory + JSON-persisted (intent, agent) outcome tracker."""

    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = Path(data_path) if data_path else DEFAULT_DATA_FILE
        self._lock = threading.RLock()
        # data: {intent: {agent: AgentStats}}
        self._data: Dict[str, Dict[str, AgentStats]] = {}
        self._load()

    # --- Persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self.data_path.exists():
            return
        try:
            with self.data_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            for intent, by_agent in raw.items():
                self._data[intent] = {}
                for agent, stats in by_agent.items():
                    self._data[intent][agent] = AgentStats(
                        agent=agent,
                        samples=int(stats.get("samples", 0)),
                        successes=int(stats.get("successes", 0)),
                        failures=int(stats.get("failures", 0)),
                        ema_fast=float(stats.get("ema_fast", 0.5)),
                        ema_slow=float(stats.get("ema_slow", 0.5)),
                        avg_duration_ms=float(stats.get("avg_duration_ms", 0.0)),
                    )
        except (json.JSONDecodeError, OSError):
            # Corrupt file — start fresh, don't crash
            self._data = {}

    def _save(self) -> None:
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                intent: {agent: stats.to_dict() for agent, stats in by_agent.items()}
                for intent, by_agent in self._data.items()
            }
            tmp = self.data_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self.data_path)
        except OSError:
            # Persistence is best-effort
            pass

    # --- API -----------------------------------------------------------------

    def record(
        self,
        intent: str,
        agent: str,
        success: bool,
        duration_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Record an outcome. Persists to disk."""
        if not intent or not agent:
            raise ValueError("intent and agent are required")
        with self._lock:
            bucket = self._data.setdefault(intent, {})
            stats = bucket.get(agent)
            if stats is None:
                stats = AgentStats(agent=agent)
                bucket[agent] = stats
            stats.update(bool(success), float(duration_ms))
            snapshot = stats.to_dict()
            self._save()
        return snapshot

    def suggest(
        self,
        intent: str,
        candidates: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Suggest the best agent for the given intent.

        Args:
            intent: the intent string (e.g. "code_review", "deployment")
            candidates: optional whitelist of agents to choose from
        Returns:
            {"agent": str, "score": float, "samples": int, "reason": str}
            or None if no candidates / no data
        """
        with self._lock:
            bucket = self._data.get(intent, {})
            if candidates:
                pool = {a: bucket[a] for a in candidates if a in bucket}
            else:
                pool = dict(bucket)
            if not pool:
                return None
            best_agent, best_stats = max(
                pool.items(),
                key=lambda kv: (kv[1].score(), kv[1].samples),
            )
            return {
                "agent": best_agent,
                "score": round(best_stats.score(), 4),
                "samples": best_stats.samples,
                "reason": (
                    "ema_fast"
                    if best_stats.samples >= MIN_SAMPLES
                    else "low_samples_prior"
                ),
            }

    def suggest_top_k(
        self,
        intent: str,
        k: int = 3,
        candidates: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return top-k agents for the intent, sorted by score."""
        with self._lock:
            bucket = self._data.get(intent, {})
            pool = (
                {a: bucket[a] for a in candidates if a in bucket}
                if candidates
                else dict(bucket)
            )
            ranked = sorted(
                pool.items(),
                key=lambda kv: (kv[1].score(), kv[1].samples),
                reverse=True,
            )
            return [
                {
                    "agent": a,
                    "score": round(s.score(), 4),
                    "samples": s.samples,
                }
                for a, s in ranked[:k]
            ]

    def stats(self) -> Dict[str, Any]:
        """Aggregate stats across all intents."""
        with self._lock:
            total_samples = 0
            total_successes = 0
            intents = {}
            for intent, by_agent in self._data.items():
                samples = sum(s.samples for s in by_agent.values())
                successes = sum(s.successes for s in by_agent.values())
                total_samples += samples
                total_successes += successes
                intents[intent] = {
                    "samples": samples,
                    "successes": successes,
                    "success_rate": round(successes / samples, 4) if samples else 0.0,
                    "agents": len(by_agent),
                }
            return {
                "intents": intents,
                "intent_count": len(self._data),
                "total_samples": total_samples,
                "total_successes": total_successes,
                "overall_success_rate": (
                    round(total_successes / total_samples, 4) if total_samples else 0.0
                ),
                "data_path": str(self.data_path),
            }

    def intent_stats(self, intent: str) -> Dict[str, Any]:
        with self._lock:
            by_agent = self._data.get(intent, {})
            return {
                "intent": intent,
                "agents": {a: s.to_dict() for a, s in by_agent.items()},
            }

    def reset(self) -> None:
        with self._lock:
            self._data = {}
            self._save()

    def list_intents(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())


__all__ = ["SONA", "AgentStats", "DEFAULT_DATA_FILE"]
