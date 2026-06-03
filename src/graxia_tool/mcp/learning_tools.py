"""MCP tools for the self-learning system."""
from __future__ import annotations
import asyncio
from typing import Any, Dict
from ..shared.helpers import _ok, _err
from ..learning.self_learner import SelfLearner


async def learning_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get learning statistics: total tasks, success rate, patterns learned."""
    data_dir = args.get("data_dir")

    def _do():
        learner = SelfLearner(data_dir=data_dir) if data_dir else SelfLearner()
        return learner.get_stats()

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def learning_suggest(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get agent and skill suggestions for a task based on learned patterns."""
    intent = args.get("intent", "")
    domain = args.get("domain", "")
    data_dir = args.get("data_dir")

    if not intent:
        return _err("intent is required")

    def _do():
        learner = SelfLearner(data_dir=data_dir) if data_dir else SelfLearner()
        return learner.get_suggestion({"intent": intent, "domain": domain})

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def learning_record(args: Dict[str, Any]) -> Dict[str, Any]:
    """Manually record a task outcome for learning."""
    intent = args.get("intent", "")
    domain = args.get("domain", "")
    success = args.get("success", True)
    agent_used = args.get("agent_used", "")
    duration_ms = args.get("duration_ms", 0.0)
    skills_used = args.get("skills_used", [])
    data_dir = args.get("data_dir")

    if not intent:
        return _err("intent is required")
    if not agent_used:
        return _err("agent_used is required")

    def _do():
        learner = SelfLearner(data_dir=data_dir) if data_dir else SelfLearner()
        learner.record_outcome(
            task={"intent": intent, "domain": domain},
            success=success,
            agent_used=agent_used,
            duration_ms=float(duration_ms),
            skills_used=skills_used,
        )
        return learner.get_stats()

    try:
        result = await asyncio.to_thread(_do)
        return _ok({"recorded": True, "stats": result})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def learning_reset(args: Dict[str, Any]) -> Dict[str, Any]:
    """Clear all learning data."""
    data_dir = args.get("data_dir")

    def _do():
        learner = SelfLearner(data_dir=data_dir) if data_dir else SelfLearner()
        learner.reset()
        return {"cleared": True}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# MCP tool definitions (for registration)
# ---------------------------------------------------------------------------

LEARNING_TOOLS = [
    {
        "name": "learning_stats",
        "description": "Get learning statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string"},
            },
        },
        "handler": learning_stats,
        "category": "learning",
    },
    {
        "name": "learning_suggest",
        "description": "Get agent/skill suggestions for a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "domain": {"type": "string"},
                "data_dir": {"type": "string"},
            },
            "required": ["intent"],
        },
        "handler": learning_suggest,
        "category": "learning",
    },
    {
        "name": "learning_record",
        "description": "Record a task outcome for learning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "domain": {"type": "string"},
                "success": {"type": "boolean", "default": True},
                "agent_used": {"type": "string"},
                "duration_ms": {"type": "number"},
                "skills_used": {"type": "array", "items": {"type": "string"}},
                "data_dir": {"type": "string"},
            },
            "required": ["intent", "agent_used"],
        },
        "handler": learning_record,
        "category": "learning",
    },
    {
        "name": "learning_reset",
        "description": "Clear all learning data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string"},
            },
        },
        "handler": learning_reset,
        "category": "learning",
    },
]
