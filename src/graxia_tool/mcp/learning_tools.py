"""MCP tools for the self-learning system.

Exposes SelfLearner as MCP tools:
- learning_stats: get learning statistics
- learning_suggest: get agent/skill suggestions for a task
- learning_record: manually record a task outcome
- learning_reset: clear all learning data
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from ..learning.self_learner import SelfLearner


def _ok(content: Any) -> Dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "isError": True}


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
        "description": "Get self-learning statistics: total tasks recorded, success rate, patterns learned, top agents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {
                    "type": "string",
                    "description": "Optional custom data directory path",
                },
            },
        },
        "handler": learning_stats,
        "category": "learning",
    },
    {
        "name": "learning_suggest",
        "description": "Get agent and skill suggestions for a task based on learned patterns from past outcomes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "Task intent (code, debug, test, etc.)"},
                "domain": {"type": "string", "description": "Task domain (backend, frontend, etc.)"},
                "data_dir": {"type": "string", "description": "Optional custom data directory"},
            },
            "required": ["intent"],
        },
        "handler": learning_suggest,
        "category": "learning",
    },
    {
        "name": "learning_record",
        "description": "Manually record a task outcome for the self-learning system.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "Task intent"},
                "domain": {"type": "string", "description": "Task domain"},
                "success": {"type": "boolean", "default": True},
                "agent_used": {"type": "string", "description": "Agent that handled the task"},
                "duration_ms": {"type": "number", "description": "Execution time in ms"},
                "skills_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skills that were loaded",
                },
                "data_dir": {"type": "string", "description": "Optional custom data directory"},
            },
            "required": ["intent", "agent_used"],
        },
        "handler": learning_record,
        "category": "learning",
    },
    {
        "name": "learning_reset",
        "description": "Clear all self-learning data (outcomes, patterns).",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string", "description": "Optional custom data directory"},
            },
        },
        "handler": learning_reset,
        "category": "learning",
    },
]
