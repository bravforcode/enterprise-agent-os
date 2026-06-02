"""Multi-agent integration helpers.

Utilities to build a coordinator from a pattern spec + sub-agent registry.
"""
from __future__ import annotations

from typing import Any

from ..agents.base import BaseSubAgent
from ..agents.implementations import AGENT_REGISTRY
from . import (
    MultiAgentCoordinator,
    PatternType,
    create_coordinator,
)


def build_coordinator(
    pattern: str,
    config: dict[str, Any],
    agent_names: list[str] | None = None,
    llm_call: Any = None,
) -> MultiAgentCoordinator:
    """Build a coordinator using agents from the global registry.

    Args:
        pattern: Pattern type
        config: Pattern config (see create_coordinator)
        agent_names: Specific agents to use. If None, uses all from config.
        llm_call: LLM function for patterns that need it (supervisor, debate)
    """
    # Collect agents
    agents: dict[str, BaseSubAgent] = {}
    if agent_names:
        for name in agent_names:
            if name in AGENT_REGISTRY:
                agents[name] = AGENT_REGISTRY[name]
    else:
        # Auto-collect from config
        names = _extract_agent_names(pattern, config)
        for name in names:
            if name in AGENT_REGISTRY:
                agents[name] = AGENT_REGISTRY[name]
            else:
                # Try to find by partial match (e.g., "coder" → "coder" agent)
                for reg_name, agent in AGENT_REGISTRY.items():
                    if name in reg_name or reg_name in name:
                        agents[name] = agent
                        break
    return create_coordinator(
        pattern=pattern, config=config, agents=agents, llm_call=llm_call
    )


def _extract_agent_names(pattern: str, config: dict[str, Any]) -> list[str]:
    """Extract agent names from pattern config."""
    if pattern == PatternType.PIPELINE.value or pattern == "pipeline":
        return config.get("stages", [])
    if pattern == PatternType.SUPERVISOR.value or pattern == "supervisor":
        return config.get("workers", [])
    if pattern == PatternType.PARALLEL.value or pattern == "parallel":
        branches = config.get("branches", [])
        if isinstance(branches, list):
            return branches
        return list(branches.keys())
    if pattern == PatternType.HIERARCHICAL.value or pattern == "hierarchical":
        tree = config.get("tree", {})
        root = config.get("root", "")
        names = [root]
        for children in tree.values():
            names.extend(children)
        return names
    if pattern == PatternType.DEBATE.value or pattern == "debate":
        return config.get("debaters", []) + [config.get("judge", "")]
    if pattern == PatternType.CONSENSUS.value or pattern == "consensus":
        return config.get("voters", [])
    if pattern == PatternType.MARKETPLACE.value or pattern == "marketplace":
        return config.get("workers", [])
    return []


def list_available_agents() -> list[str]:
    """List all registered agent names."""
    return list(AGENT_REGISTRY.keys())
