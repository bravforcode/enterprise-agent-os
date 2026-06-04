"""Unified Super-Tools — 5 tools, 30+ actions, 0 capability loss.

Merges 19 individual tools into 5 purpose-driven super-tools.
Each tool has clear purpose + action parameter for specific operations.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict

# Action handlers (lazy imports)
_handlers: Dict[str, Callable] = {}
_loaded = False


def _ensure_loaded():
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Handlers are loaded on first call via lazy imports


async def _brain_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Brain: All knowledge, memory, and retrieval operations."""
    action = args.get("action", "recall")

    if action == "recall":
        from . import _memory_recall
        return await _memory_recall(args)

    elif action == "store":
        from . import _memory_store
        return await _memory_store(args)

    elif action == "search":
        from . import _rag_query
        return await _rag_query(args)

    elif action == "hybrid_search":
        from .hybrid_rag import hybrid_search_handler
        return await hybrid_search_handler(args)

    elif action == "skill_search":
        from .fast_path import get_skill_cache
        cache = get_skill_cache()
        results = cache.search(args.get("query", ""), args.get("top_k", 5))
        return {
            "content": [{"type": "text", "text": json.dumps({
                "results": [{"name": s.get("name", ""), "description": s.get("description", "")[:200],
                             "category": s.get("category", ""), "trust": s.get("trust_level", "")}
                            for s in results],
                "total": len(results),
            }, indent=2)}]
        }

    elif action == "skill_load":
        from .skill_loader import get_skill_index
        index = await get_skill_index()
        skill_name = args.get("skill_name", "")
        content = await index.load_full(skill_name)
        if content:
            return {"content": [{"type": "text", "text": json.dumps({
                "name": content.metadata.name,
                "content": content.content,
                "tokens": content.tokens_estimate,
            }, indent=2)}]}
        return {"content": [{"type": "text", "text": f"Skill '{skill_name}' not found"}], "isError": True}

    elif action == "skill_list":
        from .fast_path import get_skill_cache
        cache = get_skill_cache()
        skills = cache.load()
        return {"content": [{"type": "text", "text": json.dumps({
            "total": len(skills),
            "skills": [{"name": s.get("name", ""), "category": s.get("category", "")} for s in skills[:50]],
        }, indent=2)}]}

    elif action == "vault_search":
        from . import _vault_search
        return await _vault_search(args)

    elif action == "vault_read":
        from . import _vault_read
        return await _vault_read(args)

    elif action == "vault_write":
        from . import _vault_write
        return await _vault_write(args)

    elif action == "vault_analytics":
        from . import _vault_analytics
        return await _vault_analytics(args)

    elif action == "sync":
        from .incremental_sync import incremental_sync_status
        return await incremental_sync_status(args)

    elif action == "sync_task":
        from .incremental_sync import incremental_sync_task
        return await incremental_sync_task(args)

    elif action == "sync_all":
        from .incremental_sync import incremental_sync_all
        return await incremental_sync_all(args)

    elif action == "learn":
        from . import _memory_ext_learn
        return await _memory_ext_learn(args)

    elif action == "memory_stats":
        from . import _memory_ext_stats
        return await _memory_ext_stats(args)

    elif action == "auto_route":
        from . import _auto_route
        return await _auto_route(args)

    return {"content": [{"type": "text", "text": f"Unknown brain action: {action}. Use: recall|store|search|hybrid_search|skill_search|skill_load|skill_list|vault_search|vault_read|vault_write|vault_analytics|sync|sync_task|sync_all|learn|memory_stats|auto_route"}], "isError": True}


async def _run_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run: Execute tasks and workflows."""
    action = args.get("action", "agent")

    if action == "agent":
        from . import _agent_run
        return await _agent_run(args)

    elif action == "chain":
        from .workflows import workflow_chain_handler
        args["pattern"] = "chain"
        return await workflow_chain_handler(args)

    elif action == "parallel":
        from .workflows import workflow_parallel_handler
        args["pattern"] = "parallel"
        return await workflow_parallel_handler(args)

    elif action == "router":
        from .workflows import workflow_router_handler
        args["pattern"] = "router"
        return await workflow_router_handler(args)

    elif action == "orchestrator":
        from .workflows import workflow_orchestrator_handler
        args["pattern"] = "orchestrator"
        return await workflow_orchestrator_handler(args)

    elif action == "evaluator":
        from .workflows import workflow_evaluator_optimizer_handler
        args["pattern"] = "evaluator"
        return await workflow_evaluator_optimizer_handler(args)

    elif action == "pipeline":
        from . import _pipeline_run
        return await _pipeline_run(args)

    elif action == "agents":
        from . import _agent_list
        return await _agent_list(args)

    return {"content": [{"type": "text", "text": f"Unknown run action: {action}. Use: agent|chain|parallel|router|orchestrator|evaluator|pipeline|agents"}], "isError": True}


async def _guard_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Guard: Safety, governance, and quality."""
    action = args.get("action", "check")

    if action == "check":
        from . import _guard_check
        return await _guard_check(args)

    elif action == "filter":
        from .governance import governance_content_filter
        return await governance_content_filter(args)

    elif action == "audit":
        from .governance import governance_audit_query
        return await governance_audit_query(args)

    elif action == "audit_stats":
        from .governance import governance_audit_stats
        return await governance_audit_stats(args)

    elif action == "optimize":
        from . import _graxia_optimize
        return await _graxia_optimize(args)

    elif action == "cost":
        from . import _cost_report
        return await _cost_report(args)

    return {"content": [{"type": "text", "text": f"Unknown guard action: {action}. Use: check|filter|audit|audit_stats|optimize|cost"}], "isError": True}


async def _data_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Data: Generate synthetic data."""
    from . import _graxia_data
    return await _graxia_data(args)


async def _sys_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """System: Status, agents, cache."""
    action = args.get("action", "status")

    if action == "status":
        from . import _system_status
        return await _system_status(args)

    elif action == "agents":
        from . import _agent_list
        return await _agent_list(args)

    elif action == "cache_get":
        from . import _cache_get
        return await _cache_get(args)

    elif action == "cache_set":
        from . import _cache_set
        return await _cache_set(args)

    elif action == "cache_stats":
        from .context_cache import ContextCache
        cache = ContextCache()
        stats = cache.stats()
        return {"content": [{"type": "text", "text": json.dumps(stats, indent=2)}]}

    return {"content": [{"type": "text", "text": f"Unknown sys action: {action}. Use: status|agents|cache_get|cache_set|cache_stats"}], "isError": True}


# ── Tool Definitions ───────────────────────────────────────────────────

UNIFIED_TOOLS = [
    {
        "name": "brain",
        "description": "ALL knowledge operations: memory recall/store, code search (RAG), skill search/load, vault ops, sync, learning, auto-routing. Use for ANY retrieval, storage, or knowledge task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["recall", "store", "search", "hybrid_search", "skill_search", "skill_load",
                             "skill_list", "vault_search", "vault_read", "vault_write", "vault_analytics",
                             "sync", "sync_task", "sync_all", "learn", "memory_stats", "auto_route"],
                    "description": "Operation to perform",
                },
                "query": {"type": "string", "description": "Search/recall query"},
                "content": {"type": "string", "description": "Content to store"},
                "memory_type": {"type": "string", "enum": ["task", "codebase", "preference"]},
                "path": {"type": "string", "description": "File/vault path"},
                "skill_name": {"type": "string", "description": "Skill to load"},
                "top_k": {"type": "integer", "default": 5},
                "mode": {"type": "string", "enum": ["semantic", "graph", "balanced"], "default": "balanced"},
            },
            "required": ["action"],
        },
        "handler": _brain_handler,
        "category": "brain",
    },
    {
        "name": "run",
        "description": "Execute tasks: single agent, multi-agent chains, parallel, routing, orchestration, evaluation loops, pipelines. Use for ANY execution or workflow task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["agent", "chain", "parallel", "router", "orchestrator", "evaluator", "pipeline", "agents"],
                    "description": "Execution pattern",
                },
                "query": {"type": "string", "description": "Task to execute"},
                "goal": {"type": "string", "description": "Goal for orchestrator"},
                "agents": {"type": "array", "items": {"type": "string"}, "description": "Agent names"},
                "agent_name": {"type": "string", "description": "Single agent name"},
                "pattern": {"type": "string"},
            },
            "required": ["action"],
        },
        "handler": _run_handler,
        "category": "run",
    },
    {
        "name": "guard",
        "description": "Safety and quality: input/output guard, content filter (injection/exfiltration), audit trail, token optimization, cost tracking. Use for ANY safety, governance, or quality task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["check", "filter", "audit", "audit_stats", "optimize", "cost"],
                    "description": "Safety operation",
                },
                "text": {"type": "string", "description": "Text to check/filter"},
                "direction": {"type": "string", "enum": ["input", "output"], "default": "input"},
                "tool_name": {"type": "string"},
                "period": {"type": "string", "enum": ["hour", "day", "week", "all"], "default": "all"},
            },
            "required": ["action"],
        },
        "handler": _guard_handler,
        "category": "guard",
    },
    {
        "name": "data",
        "description": "Generate synthetic data: persons, locations, phones, finance, dates, text, commerce, internet. Supports 50+ locales including Thai.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["generate", "locales", "schema"], "default": "generate"},
                "category": {"type": "string", "description": "Data category (person, location, phone, finance, etc.)"},
                "field": {"type": "string", "description": "Specific field (first_name, phone_number, etc.)"},
                "locale": {"type": "string", "default": "en"},
                "count": {"type": "integer", "default": 1},
                "schema": {"type": "object", "description": "Custom schema for generation"},
            },
        },
        "handler": _data_handler,
        "category": "data",
    },
    {
        "name": "sys",
        "description": "System operations: status, list agents, cache get/set/stats. Use for system health, agent discovery, and caching.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "agents", "cache_get", "cache_set", "cache_stats"],
                    "description": "System operation",
                },
                "key": {"type": "string", "description": "Cache key"},
                "value": {"type": "string", "description": "Cache value"},
                "ttl": {"type": "integer", "default": 3600},
            },
            "required": ["action"],
        },
        "handler": _sys_handler,
        "category": "sys",
    },
]
