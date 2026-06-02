"""Enterprise Agent OS — Multi-Agent API Routes.

Endpoints for running multi-agent patterns (Phase 8).

- POST /api/v1/multi-agent/run — Execute a multi-agent pattern
- GET /api/v1/multi-agent/patterns — List available patterns
- GET /api/v1/multi-agent/agents — List registered sub-agents
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Any

from ..core.auth import get_current_user
from ..core.models import User
from ..multi_agent import PatternType, create_coordinator
from ..multi_agent.builder import build_coordinator, list_available_agents

router = APIRouter(prefix="/api/v1/multi-agent", tags=["multi-agent"])


class MultiAgentRunRequest(BaseModel):
    pattern: str = Field(..., description="Pattern type: pipeline, supervisor, parallel, hierarchical, debate, consensus, marketplace")
    task: str = Field(..., description="Task to execute")
    config: dict[str, Any] = Field(default_factory=dict, description="Pattern-specific config")
    agent_names: list[str] | None = Field(default=None, description="Specific agents to use")
    context: dict[str, Any] | None = Field(default=None, description="Optional context")


class MultiAgentRunResponse(BaseModel):
    pattern: str
    success: bool
    output: Any
    duration_ms: float
    agent_count: int
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/run", response_model=MultiAgentRunResponse)
async def run_multi_agent(
    request: MultiAgentRunRequest,
    user: User = Depends(get_current_user),
) -> MultiAgentRunResponse:
    """Run a multi-agent pattern.

    Examples:
        Pipeline:
            {"pattern": "pipeline", "task": "code review",
             "config": {"stages": ["coder", "reviewer", "tester"]}}

        Supervisor:
            {"pattern": "supervisor", "task": "research X",
             "config": {"workers": ["researcher", "analyst", "writer"]}}

        Parallel:
            {"pattern": "parallel", "task": "compare",
             "config": {"branches": ["coder", "reviewer"]}}

        Debate:
            {"pattern": "debate", "task": "is X good?",
             "config": {"debaters": ["alice", "bob"], "judge": "judge", "rounds": 2}}
    """
    try:
        coord = build_coordinator(
            pattern=request.pattern,
            config=request.config,
            agent_names=request.agent_names,
        )
        result = await coord.coordinate(request.task, context=request.context)
        return MultiAgentRunResponse(
            pattern=result.pattern.value,
            success=result.success,
            output=result.output,
            duration_ms=result.duration_ms,
            agent_count=len(result.agent_results),
            error=result.error,
            metadata=result.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Multi-agent run failed: {e}")


@router.get("/patterns")
async def list_patterns(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """List available multi-agent patterns with descriptions."""
    return {
        "patterns": [
            {
                "id": PatternType.PIPELINE.value,
                "name": "Pipeline",
                "complexity": 1,
                "control": "sequential",
                "use_case": "ETL, linear workflows, code review (plan→implement→test→review)",
                "config_example": {"stages": ["agent1", "agent2", "agent3"]},
            },
            {
                "id": PatternType.SUPERVISOR.value,
                "name": "Supervisor",
                "complexity": 2,
                "control": "centralized",
                "use_case": "Cross-domain tasks (coder + researcher + reviewer). 2026 production default.",
                "config_example": {"workers": ["coder", "researcher", "reviewer"]},
            },
            {
                "id": PatternType.PARALLEL.value,
                "name": "Parallel (Fan-out/Fan-in)",
                "complexity": 2,
                "control": "parallel",
                "use_case": "Independent research, multi-perspective analysis. 3-10x latency reduction.",
                "config_example": {"branches": ["agent1", "agent2"], "aggregator": "synthesizer"},
            },
            {
                "id": PatternType.HIERARCHICAL.value,
                "name": "Hierarchical",
                "complexity": 3,
                "control": "multi-level",
                "use_case": "Large projects with distinct domains (research, engineering, QA).",
                "config_example": {"root": "orchestrator", "tree": {"orchestrator": ["research_lead", "eng_lead"]}},
            },
            {
                "id": PatternType.DEBATE.value,
                "name": "Debate",
                "complexity": 2,
                "control": "adversarial",
                "use_case": "High-stakes decisions, complex reasoning. ~2.5x single-agent cost.",
                "config_example": {"debaters": ["alice", "bob"], "judge": "judge", "rounds": 2},
            },
            {
                "id": PatternType.CONSENSUS.value,
                "name": "Consensus",
                "complexity": 2,
                "control": "voting",
                "use_case": "High-stakes outputs where disagreement is unacceptable. Cheaper than debate.",
                "config_example": {"voters": ["a", "b", "c"], "threshold": 0.5},
            },
            {
                "id": PatternType.MARKETPLACE.value,
                "name": "Marketplace (Contract-Net)",
                "complexity": 3,
                "control": "auction",
                "use_case": "Dynamic task allocation, cost optimization.",
                "config_example": {"workers": ["a", "b", "c"], "strategy": "highest_confidence"},
            },
        ]
    }


@router.get("/agents")
async def list_agents(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """List all registered sub-agents available for multi-agent runs."""
    return {
        "agents": list_available_agents(),
        "count": len(list_available_agents()),
    }
