"""Agent activity tracker — records agent lifecycle events (start, end, status, cost)."""
from __future__ import annotations

import time
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AgentStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    FAILED = "failed"
    COMPLETED = "completed"
    WAITING = "waiting"


@dataclass
class AgentEvent:
    event_id: str
    agent_name: str
    event_type: str  # "start", "end", "error", "tool_start", "tool_done"
    timestamp: float
    status: str = "active"
    run_id: str = ""
    query: str = ""
    output_summary: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "agent_name": self.agent_name,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "status": self.status,
            "run_id": self.run_id,
            "query": self.query[:120],
            "output_summary": self.output_summary[:200],
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


@dataclass
class _AgentState:
    agent_name: str
    status: AgentStatus = AgentStatus.IDLE
    current_run_id: str = ""
    total_runs: int = 0
    total_success: int = 0
    total_failures: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    last_active: float = 0.0
    active_tools: list[str] = field(default_factory=list)


class AgentTracker:
    """Thread-safe in-memory agent activity tracker.

    Stores recent events in a bounded deque and maintains per-agent aggregate state.
    """

    def __init__(self, max_events: int = 500, max_agents: int = 50):
        self._events: deque[AgentEvent] = deque(maxlen=max_events)
        self._agents: dict[str, _AgentState] = {}
        self._lock = threading.Lock()
        self._max_agents = max_agents

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _get_agent(self, name: str) -> _AgentState:
        if name not in self._agents:
            if len(self._agents) >= self._max_agents:
                self._agents.pop(next(iter(self._agents)))
            self._agents[name] = _AgentState(agent_name=name)
        return self._agents[name]

    def start(
        self,
        agent_name: str,
        run_id: str = "",
        query: str = "",
        metadata: Optional[dict] = None,
    ) -> AgentEvent:
        event = AgentEvent(
            event_id=self._new_id(),
            agent_name=agent_name,
            event_type="start",
            timestamp=time.time(),
            status=AgentStatus.ACTIVE.value,
            run_id=run_id or self._new_id(),
            query=query,
            metadata=metadata or {},
        )
        with self._lock:
            state = self._get_agent(agent_name)
            state.status = AgentStatus.ACTIVE
            state.current_run_id = event.run_id
            state.total_runs += 1
            state.last_active = event.timestamp
            self._events.append(event)
        return event

    def end(
        self,
        agent_name: str,
        run_id: str = "",
        success: bool = True,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
        output_summary: str = "",
        metadata: Optional[dict] = None,
    ) -> AgentEvent:
        status = AgentStatus.COMPLETED.value if success else AgentStatus.FAILED.value
        event = AgentEvent(
            event_id=self._new_id(),
            agent_name=agent_name,
            event_type="end",
            timestamp=time.time(),
            status=status,
            run_id=run_id,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            output_summary=output_summary,
            metadata=metadata or {},
        )
        with self._lock:
            state = self._get_agent(agent_name)
            state.status = AgentStatus.COMPLETED if success else AgentStatus.FAILED
            state.total_success += 1 if success else 0
            state.total_failures += 0 if success else 1
            state.total_tokens += tokens_used
            state.total_cost_usd += cost_usd
            state.total_duration_ms += duration_ms
            state.last_active = event.timestamp
            self._events.append(event)
        return event

    def tool_start(
        self,
        agent_name: str,
        tool_name: str,
        run_id: str = "",
    ) -> AgentEvent:
        event = AgentEvent(
            event_id=self._new_id(),
            agent_name=agent_name,
            event_type="tool_start",
            timestamp=time.time(),
            status=AgentStatus.ACTIVE.value,
            run_id=run_id,
            metadata={"tool_name": tool_name},
        )
        with self._lock:
            state = self._get_agent(agent_name)
            state.status = AgentStatus.ACTIVE
            state.last_active = event.timestamp
            if tool_name not in state.active_tools:
                state.active_tools.append(tool_name)
            self._events.append(event)
        return event

    def tool_done(
        self,
        agent_name: str,
        tool_name: str,
        run_id: str = "",
    ) -> AgentEvent:
        event = AgentEvent(
            event_id=self._new_id(),
            agent_name=agent_name,
            event_type="tool_done",
            timestamp=time.time(),
            status=AgentStatus.ACTIVE.value,
            run_id=run_id,
            metadata={"tool_name": tool_name},
        )
        with self._lock:
            state = self._get_agent(agent_name)
            state.last_active = event.timestamp
            if tool_name in state.active_tools:
                state.active_tools.remove(tool_name)
            self._events.append(event)
        return event

    def get_events(
        self,
        limit: int = 100,
        agent_filter: Optional[str] = None,
        since: Optional[float] = None,
    ) -> list[dict]:
        with self._lock:
            events = list(self._events)
        if agent_filter:
            events = [e for e in events if e.agent_name == agent_filter]
        if since:
            events = [e for e in events if e.timestamp >= since]
        return [e.to_dict() for e in events[-limit:]]

    def get_agent_states(self) -> list[dict]:
        with self._lock:
            result = []
            for state in self._agents.values():
                avg_duration = (
                    state.total_duration_ms / state.total_runs
                    if state.total_runs > 0
                    else 0
                )
                success_rate = (
                    state.total_success / max(state.total_runs, 1)
                )
                result.append({
                    "agent_name": state.agent_name,
                    "status": state.status.value,
                    "total_runs": state.total_runs,
                    "total_success": state.total_success,
                    "total_failures": state.total_failures,
                    "success_rate": round(success_rate, 3),
                    "total_tokens": state.total_tokens,
                    "total_cost_usd": round(state.total_cost_usd, 6),
                    "total_duration_ms": state.total_duration_ms,
                    "avg_duration_ms": round(avg_duration, 1),
                    "last_active": state.last_active,
                    "active_tools": list(state.active_tools),
                })
            result.sort(key=lambda x: x["last_active"], reverse=True)
            return result

    def get_summary(self) -> dict:
        with self._lock:
            total_runs = sum(s.total_runs for s in self._agents.values())
            total_tokens = sum(s.total_tokens for s in self._agents.values())
            total_cost = sum(s.total_cost_usd for s in self._agents.values())
            total_success = sum(s.total_success for s in self._agents.values())
            total_failures = sum(s.total_failures for s in self._agents.values())
            active = sum(
                1 for s in self._agents.values()
                if s.status in (AgentStatus.ACTIVE, AgentStatus.WAITING)
            )
        return {
            "total_runs": total_runs,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "total_success": total_success,
            "total_failures": total_failures,
            "success_rate": round(total_success / max(total_runs, 1), 3),
            "active_agents": active,
            "tracked_agents": len(self._agents),
        }


_tracker: Optional[AgentTracker] = None


def get_tracker() -> AgentTracker:
    global _tracker
    if _tracker is None:
        _tracker = AgentTracker()
    return _tracker
