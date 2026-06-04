"""Swarm coordinator (queen/worker pattern).

A Swarm owns:
- A topology (hierarchical, mesh, adaptive)
- A set of registered agents (named slots; not the same as topology nodes)
- A SONA instance for learning (intent, agent) success rates
- An optional FederationClient for offloading to peer swarms

The coordinator runs queries by:
1. Classifying the intent (cheap heuristic — keyword/explicit)
2. Asking SONA for the best agent; falling back to user-provided agents
3. Picking a topology node (dispatch) and running the agent on it
4. Recording the outcome back to SONA
5. Returning a SwarmResult with the worker name, agent name, and output
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..agents.base import BaseSubAgent, SubAgentResult
from .sona import SONA
from .topology import (
    AdaptiveTopology,
    HierarchicalTopology,
    MeshTopology,
    SwarmTopology,
    TopologyNode,
    build_topology,
)


def _get_global_agent_registry() -> dict:
    """Late import to avoid circular import between swarm and agents package."""
    from ..agents.implementations import AGENT_REGISTRY
    return AGENT_REGISTRY


# ---------------------------------------------------------------------------
# Intent classification (cheap heuristic; can be replaced by AutoRouter)
# ---------------------------------------------------------------------------

INTENT_KEYWORDS: Dict[str, List[str]] = {
    "code_review": ["review", "lint", "smell", "code quality"],
    "code_format": ["format", "prettier", "black", "fmt"],
    "code_test": ["test", "pytest", "spec", "unit test"],
    "refactor": ["refactor", "cleanup", "simplify"],
    "documentation": ["document", "readme", "docstring", "tutorial", "changelog"],
    "deployment": ["deploy", "release", "rollout", "ship", "ci/cd"],
    "monitoring": ["monitor", "metric", "alert", "observability", "trace"],
    "incident": ["incident", "outage", "sev", "downtime", "postmortem"],
    "security": ["security", "cve", "vuln", "owasp", "secret", "threat"],
    "architecture": ["architect", "design", "schema", "topology", "ddd"],
    "data": ["sql", "etl", "data", "schema", "query", "index", "partition"],
    "frontend": ["ui", "react", "css", "a11y", "accessibility", "seo", "pwa"],
    "research": ["research", "investigate", "find", "explore"],
    "debug": ["debug", "bug", "error", "stack trace"],
    "plan": ["plan", "estimate", "scope", "decompose"],
}


def classify_intent(query: str) -> str:
    """Cheap keyword-based intent classifier."""
    q = (query or "").lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return intent
    return "general"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SwarmConfig:
    topology: str = "hierarchical"
    agents: List[str] = field(default_factory=list)
    fanout: int = 1
    auto_register_extended: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SwarmResult:
    swarm_id: str
    query: str
    intent: str
    chosen_agent: str
    worker: str
    topology: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    agent_result: Optional[SubAgentResult] = None
    suggestion_reason: str = ""


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class Swarm:
    """A single swarm instance: topology + agents + SONA + run method."""

    def __init__(
        self,
        swarm_id: Optional[str] = None,
        config: Optional[SwarmConfig] = None,
        sona: Optional[SONA] = None,
        topology: Optional[SwarmTopology] = None,
        agents_registry: Optional[Dict[str, type]] = None,
    ):
        self.swarm_id = swarm_id or f"swarm-{uuid.uuid4().hex[:8]}"
        self.config = config or SwarmConfig()
        self.sona = sona or SONA()
        # Combined agent registry (defaults to the global one, plus extended)
        from .agents_extended import EXTENDED_AGENT_REGISTRY
        registry: Dict[str, type] = dict(_get_global_agent_registry())
        if self.config.auto_register_extended:
            for name, cls in EXTENDED_AGENT_REGISTRY.items():
                registry.setdefault(name, cls)
        if agents_registry:
            registry.update(agents_registry)
        self.agents_registry = registry

        # Resolve topology
        if topology is not None:
            self.topology = topology
        else:
            nodes = self._build_nodes(self.config.agents or list(self.agents_registry.keys()))
            self.topology = build_topology(self.config.topology, nodes, self.config.config)

        # State
        self.message_queue_depth = 0
        self.agent_status: Dict[str, str] = {
            name: "idle" for name in self.agents_registry
        }
        self.runs_total = 0
        self.runs_succeeded = 0
        self._lock = asyncio.Lock()

    # --- Helpers ------------------------------------------------------------

    def _build_nodes(self, agent_names: List[str]) -> List[TopologyNode]:
        # First node is queen, rest are workers
        nodes: List[TopologyNode] = []
        for i, name in enumerate(agent_names):
            nodes.append(
                TopologyNode(
                    name=name,
                    role=("queen" if i == 0 else "worker"),
                    load=0,
                    capacity=self.config.config.get("capacity", 4),
                )
            )
        return nodes

    def _agent_classes(self, names: List[str]) -> Dict[str, type]:
        out: Dict[str, type] = {}
        for n in names:
            cls = self.agents_registry.get(n)
            if cls is not None:
                out[n] = cls
        return out

    def _agent_name_for_query(
        self,
        intent: str,
        preferred: Optional[List[str]] = None,
    ) -> str:
        """Pick an agent for the intent using SONA + registry fallbacks."""
        candidates = preferred or list(self.agents_registry.keys())
        suggestion = self.sona.suggest(intent, candidates=candidates)
        if suggestion:
            return suggestion["agent"]
        # Fall back: prefer any agent whose name or category contains the intent
        for n in candidates:
            if intent in n or n in intent:
                return n
        # Fall back: a sensible default
        if "general" in candidates:
            return "general"
        return candidates[0]

    # --- Public API ----------------------------------------------------------

    async def run(
        self,
        query: str,
        topology_override: Optional[str] = None,
        preferred_agents: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SwarmResult:
        """Run a query through the swarm. Picks agent, dispatches, executes."""
        intent = classify_intent(query)
        agent_name = self._agent_name_for_query(intent, preferred_agents)
        cls = self.agents_registry.get(agent_name)
        if cls is None:
            return SwarmResult(
                swarm_id=self.swarm_id, query=query, intent=intent,
                chosen_agent=agent_name, worker="<none>", topology=self.topology.kind,
                success=False, error=f"agent '{agent_name}' not in registry",
            )

        # Optional topology swap
        original_kind = self.topology.kind
        if topology_override and topology_override != original_kind:
            nodes = list(self.topology.nodes.values())
            self.topology = build_topology(topology_override, nodes, self.config.config)

        # Dispatch
        worker = await self.topology.dispatch({"intent": intent, "query": query})
        self.topology.mark_busy(worker)
        self.message_queue_depth += 1

        # Execute the agent
        t0 = time.time()
        success = False
        output: Any = None
        error: Optional[str] = None
        agent_result: Optional[SubAgentResult] = None
        suggestion_reason = "fallback"
        suggestion = self.sona.suggest(intent, [agent_name])
        if suggestion:
            suggestion_reason = suggestion["reason"]

        try:
            instance = cls()
            agent_result = await instance.run(query, context=context)
            success = agent_result.success
            output = agent_result.output
            error = agent_result.error
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            self.topology.mark_done(worker)
            self.message_queue_depth = max(0, self.message_queue_depth - 1)
            async with self._lock:
                self.runs_total += 1
                if success:
                    self.runs_succeeded += 1
                self.agent_status[agent_name] = "idle" if success else "error"

        duration_ms = int((time.time() - t0) * 1000)
        # Record into SONA
        self.sona.record(intent, agent_name, success, duration_ms)

        # Restore topology if we swapped
        if topology_override and topology_override != original_kind:
            nodes = list(self.topology.nodes.values())
            self.topology = build_topology(original_kind, nodes, self.config.config)

        return SwarmResult(
            swarm_id=self.swarm_id, query=query, intent=intent,
            chosen_agent=agent_name, worker=worker, topology=self.topology.kind,
            success=success, output=output, error=error,
            duration_ms=duration_ms, agent_result=agent_result,
            suggestion_reason=suggestion_reason,
        )

    async def fan_out(
        self,
        queries: List[str],
        agent_name: Optional[str] = None,
    ) -> List[SwarmResult]:
        """Run multiple queries in parallel; each on its own topology node."""
        if not queries:
            return []
        if self.topology.kind != "mesh" and not isinstance(self.topology, MeshTopology):
            # Switch to mesh for fan-out
            nodes = list(self.topology.nodes.values())
            original_kind = self.topology.kind
            self.topology = MeshTopology(nodes, self.config.config)
            try:
                tasks = [self.run(q, preferred_agents=[agent_name] if agent_name else None)
                         for q in queries]
                return await asyncio.gather(*tasks)
            finally:
                self.topology = build_topology(original_kind, nodes, self.config.config)
        tasks = [self.run(q, preferred_agents=[agent_name] if agent_name else None)
                 for q in queries]
        return await asyncio.gather(*tasks)

    def status(self) -> Dict[str, Any]:
        return {
            "swarm_id": self.swarm_id,
            "topology": self.topology.kind,
            "topology_snapshot": self.topology.snapshot(),
            "agent_count": len(self.agents_registry),
            "agents_sample": sorted(list(self.agents_registry.keys()))[:20],
            "message_queue_depth": self.message_queue_depth,
            "agent_status": dict(self.agent_status),
            "runs_total": self.runs_total,
            "runs_succeeded": self.runs_succeeded,
            "sona_intents": self.sona.list_intents(),
        }


# ---------------------------------------------------------------------------
# Swarm manager (singleton registry of swarms by id)
# ---------------------------------------------------------------------------


class SwarmManager:
    """Process-wide registry of swarms."""

    def __init__(self):
        self.swarms: Dict[str, Swarm] = {}

    def init_swarm(
        self,
        topology: str = "hierarchical",
        agents: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_register_extended: bool = True,
    ) -> Swarm:
        cfg = SwarmConfig(
            topology=topology,
            agents=agents or [],
            config=config or {},
            auto_register_extended=auto_register_extended,
        )
        swarm = Swarm(config=cfg)
        self.swarms[swarm.swarm_id] = swarm
        return swarm

    def get(self, swarm_id: str) -> Optional[Swarm]:
        return self.swarms.get(swarm_id)

    def drop(self, swarm_id: str) -> bool:
        return self.swarms.pop(swarm_id, None) is not None

    def list_swarms(self) -> List[str]:
        return list(self.swarms.keys())


# Module-level singleton
MANAGER = SwarmManager()


__all__ = [
    "Swarm",
    "SwarmManager",
    "MANAGER",
    "SwarmConfig",
    "SwarmResult",
    "classify_intent",
    "INTENT_KEYWORDS",
]
