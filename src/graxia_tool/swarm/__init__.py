"""Graxia Tool — Multi-Agent Swarm + Federation (Track T2).

This package ports the core coordination patterns from ruflo/claude-flow
to Graxia's Python codebase:

- Swarm topologies: hierarchical, mesh, adaptive
- Federation: lightweight HTTP+token agent-to-agent communication
- 80+ additional agent definitions (combined with the original 18 = 100+)
- SONA-lite: (intent, agent) → success_rate learning
- MCP integration: all features exposed as tools

Public API:
    from graxia_tool.swarm import (
        Swarm, SwarmManager, MANAGER,
        HierarchicalTopology, MeshTopology, AdaptiveTopology, build_topology,
        TopologyNode,
        FederationServer, FederationClient, FederationRegistry,
        SONA,
        EXTENDED_AGENT_REGISTRY, register_extended_agents,
    )
"""
from __future__ import annotations

from .topology import (
    AdaptiveTopology,
    HierarchicalTopology,
    MeshTopology,
    SwarmTopology,
    TopologyNode,
    build_topology,
)
from .federation import (
    FederationClient,
    FederationMessage,
    FederationRegistry,
    FederationServer,
    Peer,
    MSG_AGENT_RUN,
    MSG_HEARTBEAT,
    MSG_PING,
    MSG_PONG,
    MSG_REGISTER,
    MSG_SWARM_QUERY,
)
from .sona import SONA, AgentStats, DEFAULT_DATA_FILE
from .agents_extended import (
    ALL_EXTENDED,
    EXTENDED_AGENT_REGISTRY,
    register_extended_agents,
)
from .coordinator import (
    MANAGER,
    Swarm,
    SwarmConfig,
    SwarmManager,
    SwarmResult,
    classify_intent,
)


__all__ = [
    # Topologies
    "TopologyNode",
    "SwarmTopology",
    "HierarchicalTopology",
    "MeshTopology",
    "AdaptiveTopology",
    "build_topology",
    # Federation
    "FederationServer",
    "FederationClient",
    "FederationRegistry",
    "FederationMessage",
    "Peer",
    "MSG_PING", "MSG_PONG", "MSG_REGISTER",
    "MSG_AGENT_RUN", "MSG_SWARM_QUERY", "MSG_HEARTBEAT",
    # SONA
    "SONA", "AgentStats", "DEFAULT_DATA_FILE",
    # Extended agents
    "EXTENDED_AGENT_REGISTRY",
    "ALL_EXTENDED",
    "register_extended_agents",
    # Coordinator
    "Swarm", "SwarmManager", "MANAGER",
    "SwarmConfig", "SwarmResult",
    "classify_intent",
]


__version__ = "0.3.0-swarm"
