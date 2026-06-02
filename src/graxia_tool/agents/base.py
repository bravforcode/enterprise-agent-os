"""Enterprise Agent OS — Sub-Agent Base Class.

All sub-agents inherit from BaseSubAgent and implement:
- name: agent type
- description: what it does
- required_skills: skills this agent needs
- required_tools: tools this agent can use
- execute(): the main agent logic
"""
from __future__ import annotations
import uuid
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from ..core.logging import get_logger

logger = get_logger("subagent")


@dataclass
class SubAgentResult:
    """Result from a sub-agent execution."""
    success: bool
    output: Any
    error: Optional[str] = None
    agent_name: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseSubAgent(ABC):
    """
    Base class for all sub-agents.
    """

    __test__ = False  # Prevent pytest from collecting this

    name: str = "base"
    description: str = "Base sub-agent"
    required_skills: list[str] = []
    required_tools: list[str] = []
    max_tokens: int = 4096
    timeout_seconds: int = 60

    def __init__(self, llm_func=None, tool_registry=None, skill_registry=None):
        self.llm_func = llm_func
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.run_id: Optional[uuid.UUID] = None

    @abstractmethod
    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        """Execute the agent's main logic."""
        pass

    async def run(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        """Run the agent with logging and timing."""
        t0 = time.time()
        self.run_id = uuid.uuid4()
        logger.info(
            "subagent_started",
            agent=self.name,
            run_id=str(self.run_id),
            query=query[:50],
        )
        try:
            result = await self.execute(query, context)
            result.duration_ms = int((time.time() - t0) * 1000)
            logger.info(
                "subagent_completed",
                agent=self.name,
                run_id=str(self.run_id),
                success=result.success,
                duration_ms=result.duration_ms,
            )
            return result
        except Exception as e:
            logger.error(
                "subagent_failed",
                agent=self.name,
                run_id=str(self.run_id),
                error=str(e),
            )
            return SubAgentResult(
                success=False,
                output=None,
                error=str(e),
                duration_ms=int((time.time() - t0) * 1000),
            )
