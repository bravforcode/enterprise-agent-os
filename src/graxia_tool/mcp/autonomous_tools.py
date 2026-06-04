"""MCP tool handlers for ANUS-style autonomous mode.

These wrap the Python API in :mod:`graxia_tool.autonomous` so they are
callable from any MCP client (Claude Desktop, Codex, etc.).

Tool list:
    context_load           — load ANUS.md for a project
    context_save           — write ANUS.md
    context_update         — append learnings to ANUS.md
    autonomous_plan        — build a GOAP plan (no execution)
    autonomous_run         — full plan -> execute -> learn loop
    autonomous_status      — inspect a run record
    autonomous_list_runs   — recent runs
"""
from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Dict, List, Optional

from ..llm import HybridLLMClient
from ..shared.helpers import _ok, _err
from ..autonomous import (
    ANUSContext,
    AutonomousExecutor,
    GOAPPlanner,
    SelfLearner,
    WorldState,
)
from ..autonomous.planner import specs_from_registry
from ..autonomous.store import RunRecord, RunStatus


# ---------------------------------------------------------------------------
# Lazy singletons (so we don't open a registry/LLM connection at import time)
# ---------------------------------------------------------------------------

_REGISTRY = None
_LLM = None
_STORE = None


def _get_registry():
    global _REGISTRY
    if _REGISTRY is None:
        from . import build_default_registry  # type: ignore
        _REGISTRY = build_default_registry()
    return _REGISTRY


def _get_llm() -> HybridLLMClient:
    global _LLM
    if _LLM is None:
        _LLM = HybridLLMClient()
    return _LLM


def _get_store():
    global _STORE
    if _STORE is None:
        from ..autonomous.store import RunStore
        _STORE = RunStore()
    return _STORE


# ---------------------------------------------------------------------------
# Context tools
# ---------------------------------------------------------------------------

async def context_load(args: Dict[str, Any]) -> Dict[str, Any]:
    """Load ANUS.md for a project (or fallback global)."""
    project_path = args.get("project_path")
    try:
        ctx = ANUSContext()
        path = ctx.path_for(project_path)
        project = ctx.load(project_path)
        return _ok({
            "path": str(path),
            "exists": path.exists(),
            "project": project.to_dict(),
            "notes": project.notes,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def context_save(args: Dict[str, Any]) -> Dict[str, Any]:
    """Save ANUS.md. Pass either a `content` string (raw) or a `project` dict."""
    project_path = args.get("project_path")
    content = args.get("content")
    project_dict = args.get("project")
    try:
        ctx = ANUSContext()
        path = ctx.path_for(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if content is not None and project_dict is None:
            # raw mode: write the bytes as-is (used by humans/editors)
            path.write_text(str(content), encoding="utf-8")
            return _ok({"path": str(path), "written": True, "mode": "raw"})

        from .context import ANUSProject, Learning, HistoryEntry
        if project_dict is None:
            return _err("either 'content' or 'project' must be provided")

        p = ANUSProject()
        p.project = str(project_dict.get("project", "default"))
        p.goals = [str(g) for g in (project_dict.get("goals") or [])]
        p.constraints = [str(c) for c in (project_dict.get("constraints") or [])]
        p.preferences = dict(project_dict.get("preferences") or {})
        for l in (project_dict.get("learnings") or []):
            p.learnings.append(Learning(
                date=str(l.get("date", "")),
                lesson=str(l.get("lesson", "")),
                applied=bool(l.get("applied", False)),
                source=str(l.get("source", "autonomous")),
            ))
        for h in (project_dict.get("history") or []):
            p.history.append(HistoryEntry(
                run_id=str(h.get("run_id", "")),
                query=str(h.get("query", "")),
                plan_steps=int(h.get("plan_steps", 0)),
                success=bool(h.get("success", True)),
                duration_s=float(h.get("duration_s", 0.0)),
                timestamp=str(h.get("timestamp", "")),
            ))
        p.notes = str(project_dict.get("notes", ""))
        ctx.save(p, project_path=project_path)
        return _ok({"path": str(path), "written": True, "mode": "structured"})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def context_update(args: Dict[str, Any]) -> Dict[str, Any]:
    """Append new learnings to ANUS.md and save."""
    project_path = args.get("project_path")
    learnings = args.get("learnings") or []
    if not isinstance(learnings, list) or not learnings:
        return _err("learnings must be a non-empty list of strings or {text,applied} dicts")

    try:
        ctx = ANUSContext()
        project = ctx.load(project_path)
        added = 0
        for entry in learnings:
            if isinstance(entry, str):
                ctx.append_learning(project, entry)
                added += 1
            elif isinstance(entry, dict):
                ctx.append_learning(
                    project,
                    lesson=str(entry.get("text") or entry.get("lesson") or ""),
                    applied=bool(entry.get("applied", True)),
                    source=str(entry.get("source", "mcp")),
                )
                added += 1
        ctx.save(project, project_path=project_path)
        return _ok({
            "path": str(ctx.path_for(project_path)),
            "added": added,
            "total_learnings": len(project.learnings),
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Planner / executor
# ---------------------------------------------------------------------------

async def autonomous_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build a GOAP A* plan for a goal. Does not execute it."""
    goal = args.get("goal", "")
    if not goal:
        return _err("goal is required")

    available_tools = args.get("available_tools")
    constraints = args.get("constraints") or []

    try:
        registry = _get_registry()
        llm = _get_llm()
        specs = specs_from_registry(registry)
        if available_tools:
            keep = set(available_tools)
            specs = [s for s in specs if s.name in keep]
        planner = GOAPPlanner(specs, llm_client=llm)
        plan = await planner.plan(goal, constraints=constraints)
        return _ok(plan.to_dict())
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def autonomous_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """Full autonomous loop: plan -> execute -> learn -> save ANUS.md."""
    goal = args.get("goal", "")
    if not goal:
        return _err("goal is required")
    project_path = args.get("project_path")
    max_steps = int(args.get("max_steps", 20))
    max_replans = int(args.get("max_replans", 2))
    learn = bool(args.get("learn", True))
    update_context = bool(args.get("update_context", True))

    try:
        registry = _get_registry()
        llm = _get_llm()
        store = _get_store()

        executor = AutonomousExecutor(
            registry=registry,
            llm_client=llm,
            store=store,
            max_steps=max_steps,
            max_replans=max_replans,
        )
        result = await executor.run(goal)

        learned_lessons: List[str] = []
        if learn and result.record is not None:
            learner = SelfLearner(llm_client=llm)
            ctx = ANUSContext()
            project = ctx.load(project_path)
            lessons = await learner.apply(
                result.record, project, ctx, project_path=project_path,
            )
            learned_lessons = [l.text for l in lessons]
            if update_context:
                # ANUS.md is already saved by learner.apply
                pass

        out = result.to_dict()
        if result.plan is not None:
            out["plan"] = result.plan.to_dict()
        if learned_lessons:
            out["lessons"] = learned_lessons
        out["anus_path"] = str(ANUSContext().path_for(project_path))
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}")


async def autonomous_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get the state of a single run."""
    run_id = args.get("run_id", "")
    if not run_id:
        return _err("run_id is required")
    try:
        store = _get_store()
        rec = store.get(run_id)
        if rec is None:
            return _err(f"unknown run_id: {run_id}")
        return _ok(rec.to_dict())
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def autonomous_list_runs(args: Dict[str, Any]) -> Dict[str, Any]:
    """List recent autonomous runs."""
    limit = int(args.get("limit", 10))
    try:
        store = _get_store()
        recs = store.list(limit=limit)
        return _ok({
            "runs": [r.to_dict() for r in recs],
            "count": len(recs),
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Tool registry (consumed by mcp/__init__.py)
# ---------------------------------------------------------------------------

AUTONOMOUS_TOOLS = [
    {
        "name": "context_load",
        "description": "Load ANUS.md for a project (project context the agent reads at session start).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string",
                                  "description": "Project root. Falls back to ~/.graxia/autonomous/ANUS.md if absent."},
            },
        },
        "handler": context_load,
        "category": "autonomous",
    },
    {
        "name": "context_save",
        "description": "Save ANUS.md. Pass either `content` (raw markdown) or `project` (structured dict).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "content": {"type": "string", "description": "Raw markdown (overwrites file)."},
                "project": {"type": "object", "description": "Structured project: {project, goals, constraints, preferences, learnings, history, notes}."},
            },
        },
        "handler": context_save,
        "category": "autonomous",
    },
    {
        "name": "context_update",
        "description": "Append new learnings to ANUS.md and save the file. Each learning is a string or {text, applied, source} dict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "learnings": {"type": "array", "items": {"oneOf": [
                    {"type": "string"},
                    {"type": "object", "properties": {
                        "text": {"type": "string"},
                        "applied": {"type": "boolean"},
                        "source": {"type": "string"},
                    }},
                ]}},
            },
            "required": ["learnings"],
        },
        "handler": context_update,
        "category": "autonomous",
    },
    {
        "name": "autonomous_plan",
        "description": "Build a GOAP A* plan for a goal over the MCP tool registry. Returns the plan only; no execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "available_tools": {"type": "array", "items": {"type": "string"},
                                     "description": "Optional whitelist of tool names."},
                "constraints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["goal"],
        },
        "handler": autonomous_plan,
        "category": "autonomous",
    },
    {
        "name": "autonomous_run",
        "description": "Full autonomous loop: GOAP-plan -> execute tools -> learn -> save ANUS.md. Fully autonomous; no user prompts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "project_path": {"type": "string"},
                "max_steps": {"type": "integer", "default": 20},
                "max_replans": {"type": "integer", "default": 2},
                "learn": {"type": "boolean", "default": True},
                "update_context": {"type": "boolean", "default": True},
            },
            "required": ["goal"],
        },
        "handler": autonomous_run,
        "category": "autonomous",
    },
    {
        "name": "autonomous_status",
        "description": "Get the current/last state of an autonomous run by run_id.",
        "input_schema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
        "handler": autonomous_status,
        "category": "autonomous",
    },
    {
        "name": "autonomous_list_runs",
        "description": "List recent autonomous runs (most recent first).",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
        "handler": autonomous_list_runs,
        "category": "autonomous",
    },
]
