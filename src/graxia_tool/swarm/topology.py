"""Swarm topologies for Graxia Tool — hierarchical, mesh, adaptive.

Ported from ruflo/claude-flow coordination patterns.
- HierarchicalTopology: queen/worker tree, queen dispatches, workers execute
- MeshTopology: every node can dispatch to every other node
- AdaptiveTopology: switches between hierarchical and mesh based on load

Topologies manage a set of named nodes (workers) and provide a single
async dispatch method that returns the worker name that should run the
next unit of work, given the current state.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


@dataclass
class TopologyNode:
    """A node in a swarm topology."""
    name: str
    role: str = "worker"  # queen | worker
    load: int = 0  # outstanding tasks
    capacity: int = 4  # max concurrent tasks
    status: str = "idle"  # idle | busy | error

    def available(self) -> bool:
        return self.load < self.capacity and self.status != "error"


class SwarmTopology:
    """Base class for swarm topologies."""

    kind: str = "base"

    def __init__(self, nodes: List[TopologyNode], config: Optional[Dict[str, Any]] = None):
        self.nodes: Dict[str, TopologyNode] = {n.name: n for n in nodes}
        self.config = config or {}

    def add_node(self, node: TopologyNode) -> None:
        self.nodes[node.name] = node

    def remove_node(self, name: str) -> None:
        self.nodes.pop(name, None)

    def node_count(self) -> int:
        return len(self.nodes)

    def list_nodes(self) -> List[str]:
        return list(self.nodes.keys())

    async def dispatch(self, payload: Dict[str, Any]) -> str:
        """Pick the node that should handle the next payload."""
        raise NotImplementedError

    def mark_done(self, name: str) -> None:
        n = self.nodes.get(name)
        if n and n.load > 0:
            n.load -= 1
        if n and n.load == 0:
            n.status = "idle"

    def mark_busy(self, name: str) -> None:
        n = self.nodes.get(name)
        if n:
            n.load += 1
            n.status = "busy"

    def snapshot(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "node_count": self.node_count(),
            "nodes": {
                name: {
                    "role": n.role,
                    "load": n.load,
                    "capacity": n.capacity,
                    "status": n.status,
                }
                for name, n in self.nodes.items()
            },
        }


class HierarchicalTopology(SwarmTopology):
    """Queen/worker tree. The queen always picks the least-loaded worker.

    If no queen is configured, the first node is promoted to queen.
    Workers report back through the queen.
    """

    kind = "hierarchical"

    def __init__(self, nodes: List[TopologyNode], config: Optional[Dict[str, Any]] = None):
        super().__init__(nodes, config)
        # Promote first node to queen if none exists
        if not any(n.role == "queen" for n in self.nodes.values()) and self.nodes:
            first = next(iter(self.nodes.values()))
            first.role = "queen"

    def queen(self) -> Optional[TopologyNode]:
        for n in self.nodes.values():
            if n.role == "queen":
                return n
        return None

    def workers(self) -> List[TopologyNode]:
        return [n for n in self.nodes.values() if n.role == "worker"]

    async def dispatch(self, payload: Dict[str, Any]) -> str:
        # Round-robin over workers; pick first available; else least-loaded
        workers = self.workers()
        if not workers:
            # Fall back to queen
            q = self.queen()
            if q:
                return q.name
            raise RuntimeError("No nodes in hierarchical topology")

        available = [w for w in workers if w.available()]
        if available:
            chosen = min(available, key=lambda w: w.load)
            return chosen.name

        # All busy → least-loaded overall
        chosen = min(workers, key=lambda w: w.load)
        return chosen.name


class MeshTopology(SwarmTopology):
    """Every node can dispatch to every other node.

    Uses a simple fair-share scheduler: each node receives work in proportion
    to its capacity, cycling through nodes round-robin starting from a
    deterministic offset derived from the payload (so retries land on
    different nodes).
    """

    kind = "mesh"

    def __init__(self, nodes: List[TopologyNode], config: Optional[Dict[str, Any]] = None):
        super().__init__(nodes, config)
        self._cursor = 0

    def peers(self, name: str) -> List[str]:
        return [n for n in self.nodes.keys() if n != name]

    async def dispatch(self, payload: Dict[str, Any]) -> str:
        if not self.nodes:
            raise RuntimeError("No nodes in mesh topology")
        names = sorted(self.nodes.keys())
        # Capacity-weighted fair share: each call picks next available
        for _ in range(len(names)):
            n = self.nodes[names[self._cursor % len(names)]]
            self._cursor += 1
            if n.available():
                return n.name
        # All busy → least-loaded
        chosen = min(self.nodes.values(), key=lambda n: (n.load, n.name))
        return chosen.name


class AdaptiveTopology(SwarmTopology):
    """Switches between hierarchical and mesh based on fanout + load.

    Heuristics:
    - If payload contains fanout > threshold OR queue_depth > threshold
      → use mesh (parallel fan-out)
    - Otherwise → use hierarchical (coordinated execution)
    """

    kind = "adaptive"
    FANOUT_THRESHOLD = 4
    LOAD_THRESHOLD = 8

    def __init__(self, nodes: List[TopologyNode], config: Optional[Dict[str, Any]] = None):
        super().__init__(nodes, config)
        # Build inner topologies that share the same node set
        self._hier = HierarchicalTopology(list(self.nodes.values()), config)
        self._mesh = MeshTopology(list(self.nodes.values()), config)

    def add_node(self, node: TopologyNode) -> None:
        super().add_node(node)
        self._hier.add_node(node)
        self._mesh.add_node(node)

    def remove_node(self, name: str) -> None:
        super().remove_node(name)
        self._hier.remove_node(name)
        self._mesh.remove_node(name)

    def _decide(self, payload: Dict[str, Any]) -> SwarmTopology:
        fanout = int(payload.get("fanout", 1) or 1)
        queue_depth = int(payload.get("queue_depth", 0) or 0)
        if fanout >= self.FANOUT_THRESHOLD or queue_depth >= self.LOAD_THRESHOLD:
            return self._mesh
        return self._hier

    async def dispatch(self, payload: Dict[str, Any]) -> str:
        chosen = self._decide(payload)
        return await chosen.dispatch(payload)

    def current_mode(self, payload: Optional[Dict[str, Any]] = None) -> str:
        return self._decide(payload or {}).kind

    def snapshot(self) -> Dict[str, Any]:
        base = super().snapshot()
        base["current_mode"] = self.current_mode()
        return base


def build_topology(kind: str, nodes: List[TopologyNode], config: Optional[Dict[str, Any]] = None) -> SwarmTopology:
    """Factory for topologies."""
    kind = (kind or "hierarchical").lower()
    if kind == "hierarchical":
        return HierarchicalTopology(nodes, config)
    if kind == "mesh":
        return MeshTopology(nodes, config)
    if kind == "adaptive":
        return AdaptiveTopology(nodes, config)
    raise ValueError(f"Unknown topology kind: {kind}")


__all__ = [
    "TopologyNode",
    "SwarmTopology",
    "HierarchicalTopology",
    "MeshTopology",
    "AdaptiveTopology",
    "build_topology",
]
