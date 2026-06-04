"""ANUS-style autonomous mode for Graxia Tool.

Track T3 — Phase 1 (Foundational Agent) + early Phase 2 (Meta-Cognition).

Public surface:
    ANUSContext       — load/save/update the ANUS.md project file
    GOAPPlanner       — A* planner over available tools
    AutonomousExecutor — plan -> execute -> observe -> replan loop
    SelfLearner       — distill lessons from a run and update ANUS.md
    RunStore          — in-memory + on-disk record of past runs
    AutonomousEngine  — convenience facade that ties everything together
"""
from __future__ import annotations

from .context import ANUSContext, ANUSProject, DEFAULT_ANUS_FILENAME, default_context_path
from .planner import GOAPPlanner, Plan, PlanStep, WorldState
from .executor import AutonomousExecutor, ExecutionResult
from .learner import SelfLearner
from .store import RunStore, RunRecord, RunStatus

__all__ = [
    "ANUSContext",
    "ANUSProject",
    "DEFAULT_ANUS_FILENAME",
    "default_context_path",
    "GOAPPlanner",
    "Plan",
    "PlanStep",
    "WorldState",
    "AutonomousExecutor",
    "ExecutionResult",
    "SelfLearner",
    "RunStore",
    "RunRecord",
    "RunStatus",
]
