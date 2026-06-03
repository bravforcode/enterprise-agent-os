"""Graxia MCP Server — exposes Agent OS features as MCP tools (stdio/SSE)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("graxia_tool.mcp")

# Tool registry

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class Tool:
    """An MCP tool definition."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: ToolHandler
    category: str = "general"

    def to_mcp_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class ToolRegistry:
    """Registry of all MCP tools exposed by Agent OS."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_all(self) -> List[Tool]:
        return list(self._tools.values())

    def list_by_category(self, category: str) -> List[Tool]:
        return [t for t in self._tools.values() if t.category == category]


# JSON-RPC protocol helpers

def make_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    if data is not None:
        err["error"]["data"] = data
    return err


# Tool implementations

def _ok(content: Any) -> Dict[str, Any]:
    """Format a successful tool result as MCP content array."""
    text = content if isinstance(content, str) else json.dumps(content, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "isError": True}


async def _agent_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a sub-agent by name."""
    from ..agents import AGENT_REGISTRY, list_agents

    agent_name = args.get("agent_name") or args.get("agent", "")
    query = args.get("query", "")
    context = args.get("context", {}) or {}
    llm_func = args.get("llm_func")  # Optional callable name

    if not agent_name or not query:
        return _err("agent_name and query are required")

    if agent_name not in AGENT_REGISTRY:
        return _err(f"Unknown agent '{agent_name}'. Available: {list_agents()}")

    cls = AGENT_REGISTRY[agent_name]

    # Resolve LLM function if requested by name
    resolved_llm = None
    if llm_func:
        resolved_llm = _resolve_llm_func(llm_func)

    instance = cls(llm_func=resolved_llm)
    start = time.time()
    try:
        result = await instance.run(query, context=context)
        duration_ms = int((time.time() - start) * 1000)
        return _ok({
            "agent": agent_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "tokens_used": result.tokens_used,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms or duration_ms,
            "metadata": result.metadata,
        })
    except Exception as e:
        logger.exception("agent_run failed")
        return _err(f"{type(e).__name__}: {e}")


async def _agent_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all available sub-agents."""
    from ..agents import list_agents
    return _ok({"agents": list_agents(), "count": len(list_agents())})


async def _pipeline_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run the end-to-end pipeline."""
    from ..pipeline import EndToEndPipeline, PipelineRequest

    query = args.get("query", "")
    user_id = args.get("user_id", "default")
    pattern = args.get("pattern")  # Optional multi-agent pattern

    if not query:
        return _err("query is required")

    pipeline = EndToEndPipeline()
    request = PipelineRequest(query=query, user_id=user_id, pattern=pattern)
    try:
        result = await pipeline.run(request)
        return _ok({
            "success": result.success,
            "output": result.output,
            "intent": getattr(result, "intent", None),
            "stages": result.stages_log,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
        })
    except Exception as e:
        logger.exception("pipeline_run failed")
        return _err(f"{type(e).__name__}: {e}")


async def _guard_check(args: Dict[str, Any]) -> Dict[str, Any]:
    """Check input/output through guardrails."""
    from ..guards import InputGuard, OutputGuard

    text = args.get("text", "")
    direction = args.get("direction", "input")  # input | output

    if not text:
        return _err("text is required")

    try:
        if direction == "input":
            guard = InputGuard()
            result = await guard.check(text)
        else:
            guard = OutputGuard()
            result = await guard.check(text)

        return _ok({
            "allowed": getattr(result, "allowed", True),
            "risk_level": getattr(result, "risk_level", "low"),
            "issues": getattr(result, "issues", []),
            "sanitized": getattr(result, "sanitized_text", text),
        })
    except Exception as e:
        logger.exception("guard_check failed")
        return _err(f"{type(e).__name__}: {e}")


async def _memory_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search memory layers."""
    from ..memory import MemoryOS

    query = args.get("query", "")
    layers = args.get("layers", None)  # None = all
    limit = int(args.get("limit", 5))

    if not query:
        return _err("query is required")

    try:
        mem = MemoryOS()
        results = await mem.search(query, layers=layers, limit=limit)
        return _ok({"results": results, "count": len(results)})
    except Exception as e:
        logger.exception("memory_search failed")
        return _err(f"{type(e).__name__}: {e}")


async def _rag_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query the RAG system."""
    from ..rag import RAGOS

    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    collection = args.get("collection", "default")

    if not query:
        return _err("query is required")

    try:
        rag = RAGOS()
        results = await rag.query(query, top_k=top_k, collection=collection)
        return _ok({"results": results, "count": len(results) if isinstance(results, list) else 0})
    except Exception as e:
        logger.exception("rag_query failed")
        return _err(f"{type(e).__name__}: {e}")


async def _cache_get(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get a value from the prompt cache."""
    from ..core import PromptCache

    key = args.get("key", "")
    if not key:
        return _err("key is required")

    try:
        cache = PromptCache()
        result = cache.get(key)
        if asyncio.iscoroutine(result):
            result = await result
        return _ok({"key": key, "value": result, "hit": result is not None})
    except Exception as e:
        logger.exception("cache_get failed")
        return _err(f"{type(e).__name__}: {e}")


async def _cache_set(args: Dict[str, Any]) -> Dict[str, Any]:
    """Set a value in the prompt cache."""
    from ..core import PromptCache

    key = args.get("key", "")
    value = args.get("value")
    ttl = int(args.get("ttl", 3600))

    if not key or value is None:
        return _err("key and value are required")

    try:
        cache = PromptCache()
        set_result = cache.set(key, value, ttl=ttl)
        if asyncio.iscoroutine(set_result):
            await set_result
        return _ok({"key": key, "stored": True, "ttl": ttl})
    except Exception as e:
        logger.exception("cache_set failed")
        return _err(f"{type(e).__name__}: {e}")


async def _cost_report(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get cost report from the cost engine."""
    from ..cost_engine.engine import CostEngine

    period = args.get("period", "all")  # hour, day, week, all
    try:
        engine = CostEngine()
        report = await engine.report(period=period)
        return _ok(report)
    except Exception as e:
        logger.exception("cost_report failed")
        return _err(f"{type(e).__name__}: {e}")


async def _skills_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List available skills."""
    from ..skills import list_skills
    return _ok({"skills": list_skills()})


async def _skills_load(args: Dict[str, Any]) -> Dict[str, Any]:
    """Load a specific skill by name."""
    from ..skills import load_skill

    skill_name = args.get("skill_name", "")
    if not skill_name:
        return _err("skill_name is required")

    try:
        skill = load_skill(skill_name)
        return _ok({"name": skill.name, "content": skill.content, "tokens": skill.tokens})
    except Exception as e:
        logger.exception("skills_load failed")
        return _err(f"{type(e).__name__}: {e}")


async def _multi_agent_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a multi-agent pattern."""
    from ..multi_agent import create_coordinator

    pattern = args.get("pattern", "pipeline")
    query = args.get("query", "")
    agents = args.get("agents", [])  # List of agent names

    if not query:
        return _err("query is required")

    try:
        # Resolve agents from registry
        from ..agents import AGENT_REGISTRY
        resolved_agents = {}
        for name in agents or []:
            if name in AGENT_REGISTRY:
                cls = AGENT_REGISTRY[name]
                resolved_agents[name] = cls()

        config = {}
        coordinator = create_coordinator(pattern, config, resolved_agents)
        result = await coordinator.run(query)
        return _ok({
            "pattern": pattern,
            "success": result.success,
            "output": result.output,
            "state": result.state if hasattr(result, "state") else {},
        })
    except Exception as e:
        logger.exception("multi_agent_run failed")
        return _err(f"{type(e).__name__}: {e}")


async def _governance_check(args: Dict[str, Any]) -> Dict[str, Any]:
    """Check governance policies for an action."""
    from ..governance import PolicyEngine

    action = args.get("action", "")
    context = args.get("context", {}) or {}

    if not action:
        return _err("action is required")

    try:
        engine = PolicyEngine()
        decision = await engine.evaluate(action, context)
        return _ok({
            "allowed": getattr(decision, "allowed", True),
            "policy": getattr(decision, "policy", "unknown"),
            "reason": getattr(decision, "reason", ""),
            "risk_level": getattr(decision, "risk_level", "low"),
        })
    except Exception as e:
        logger.exception("governance_check failed")
        return _err(f"{type(e).__name__}: {e}")


async def _eval_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run evaluation on an agent."""
    from ..eval import RegressionHarness

    dataset_name = args.get("dataset_name", "qa")
    agent_name = args.get("agent_name", "general")

    try:
        harness = RegressionHarness()
        result = await harness.run(agent_name, datasets=[dataset_name])
        return _ok({
            "dataset": dataset_name,
            "agent": agent_name,
            "passed": result.passed,
            "total": result.total,
            "score": result.score,
        })
    except Exception as e:
        logger.exception("eval_run failed")
        return _err(f"{type(e).__name__}: {e}")


async def _system_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get system status."""
    return _ok({
        "status": "operational",
        "version": "0.1.0",
        "components": {
            "agents": "ready",
            "pipeline": "ready",
            "rag": "ready",
            "memory": "ready",
            "guardrails": "ready",
            "governance": "ready",
            "cost_engine": "ready",
            "multi_agent": "ready",
            "eval": "ready",
        },
        "pid": os.getpid(),
        "uptime_s": int(time.time() - _START_TIME),
    })


async def _vault_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search the connected Obsidian vault (if configured)."""
    from ..integrations.obsidian import ObsidianBridge

    query = args.get("query", "")
    limit = int(args.get("limit", 10))
    if not query:
        return _err("query is required")

    try:
        bridge = ObsidianBridge()
        results = await bridge.search(query, limit=limit)
        return _ok({"results": results, "count": len(results)})
    except Exception as e:
        logger.exception("vault_search failed")
        return _err(f"{type(e).__name__}: {e}")


async def _vault_read(args: Dict[str, Any]) -> Dict[str, Any]:
    """Read a note from the Obsidian vault."""
    from ..integrations.obsidian import ObsidianBridge

    path = args.get("path", "")
    if not path:
        return _err("path is required")

    try:
        bridge = ObsidianBridge()
        content = await bridge.read_note(path)
        return _ok({"path": path, "content": content})
    except Exception as e:
        logger.exception("vault_read failed")
        return _err(f"{type(e).__name__}: {e}")


async def _vault_write(args: Dict[str, Any]) -> Dict[str, Any]:
    """Write a note to the Obsidian vault."""
    from ..integrations.obsidian import ObsidianBridge

    path = args.get("path", "")
    content = args.get("content", "")
    if not path or content is None:
        return _err("path and content are required")

    try:
        bridge = ObsidianBridge()
        await bridge.write_note(path, content)
        return _ok({"path": path, "written": True})
    except Exception as e:
        logger.exception("vault_write failed")
        return _err(f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------------------
# Auto-router, session memory, and context cache tools
# ----------------------------------------------------------------------------

async def _auto_route(args: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-route a prompt: returns skills, RAG technique, agent, model tier, MCP tools."""
    from ..auto_router import AutoRouter

    prompt = args.get("prompt", "")
    if not prompt:
        return _err("prompt is required")

    try:
        router = AutoRouter()
        decision = router.route(prompt)
        return _ok(decision.to_dict())
    except Exception as e:
        logger.exception("auto_route failed")
        return _err(f"{type(e).__name__}: {e}")


async def _memory_recall(args: Dict[str, Any]) -> Dict[str, Any]:
    """Recall relevant memories for a query using BM25 keyword matching."""
    from ..session_memory import SessionMemory

    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    memory_type = args.get("memory_type")  # Optional filter: task, codebase, preference

    if not query:
        return _err("query is required")

    try:
        mem = SessionMemory()
        results = mem.recall(query, limit=limit, memory_type=memory_type)
        return _ok({
            "results": [
                {
                    "id": r.memory_id,
                    "content": r.content,
                    "type": r.memory_type,
                    "score": round(r.score, 3),
                    "created_at": r.created_at,
                    "extra": r.extra,
                }
                for r in results
            ],
            "count": len(results),
        })
    except Exception as e:
        logger.exception("memory_recall failed")
        return _err(f"{type(e).__name__}: {e}")


async def _memory_store(args: Dict[str, Any]) -> Dict[str, Any]:
    """Store a memory (task, codebase knowledge, or preference)."""
    from ..session_memory import SessionMemory, TaskRecord, CodebaseKnowledge

    memory_type = args.get("memory_type", "preference")
    content = args.get("content", "")

    if not content:
        return _err("content is required")

    try:
        mem = SessionMemory()
        if memory_type == "task":
            record = TaskRecord(
                prompt=content,
                outcome=args.get("outcome", ""),
                success=args.get("success", True),
                duration_ms=args.get("duration_ms", 0),
                agent_type=args.get("agent_type", ""),
                intent=args.get("intent", ""),
            )
            task_id = mem.remember_task(record)
            return _ok({"stored": True, "id": task_id, "type": "task"})
        elif memory_type == "codebase":
            kb = CodebaseKnowledge(
                path=args.get("path", ""),
                summary=content,
                patterns=args.get("patterns", []),
                architecture_notes=args.get("architecture_notes", ""),
            )
            entry_id = mem.remember_codebase(kb)
            return _ok({"stored": True, "id": entry_id, "type": "codebase"})
        elif memory_type == "preference":
            key = args.get("key", "general")
            mem.remember_preference(key, content)
            return _ok({"stored": True, "key": key, "type": "preference"})
        else:
            return _err(f"Unknown memory_type: {memory_type}. Use: task, codebase, preference")
    except Exception as e:
        logger.exception("memory_store failed")
        return _err(f"{type(e).__name__}: {e}")


async def _context_cache_get(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get cached context for a prompt."""
    from ..context_cache import ContextCache

    prompt = args.get("prompt", "")
    if not prompt:
        return _err("prompt is required")

    try:
        cache = ContextCache()
        cached = cache.get(prompt)
        if cached is None:
            return _ok({"hit": False, "prompt": prompt})
        return _ok({
            "hit": True,
            "prompt": prompt,
            "decision": cached.decision,
            "result": cached.result,
            "hit_count": cached.hit_count,
            "created_at": cached.created_at,
        })
    except Exception as e:
        logger.exception("context_cache_get failed")
        return _err(f"{type(e).__name__}: {e}")


async def _context_cache_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get context cache statistics (hit rate, entry counts, etc.)."""
    from ..context_cache import ContextCache

    try:
        cache = ContextCache()
        stats = cache.get_stats()
        return _ok(stats)
    except Exception as e:
        logger.exception("context_cache_stats failed")
        return _err(f"{type(e).__name__}: {e}")


# LLM function resolver

_LLM_REGISTRY: Dict[str, Any] = {}


def register_llm(name: str, func: Any) -> None:
    """Register a callable LLM function for use via MCP."""
    _LLM_REGISTRY[name] = func


def _resolve_llm_func(name: str) -> Optional[Any]:
    return _LLM_REGISTRY.get(name)


# Build default tool registry

_START_TIME = time.time()


def build_default_registry() -> ToolRegistry:
    """Build the default MCP tool registry exposing Agent OS features."""
    reg = ToolRegistry()

    # Agent OS core
    reg.register(Tool(
        name="agent_run",
        description="Run a sub-agent on a query.",
        input_schema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Agent name"},
                "agent": {"type": "string", "description": "Alias for agent_name"},
                "query": {"type": "string", "description": "Task to run"},
                "context": {"type": "object", "description": "Optional context"},
                "llm_func": {"type": "string", "description": "Optional LLM function name"},
            },
            "required": ["query"],
        },
        handler=_agent_run,
        category="agents",
    ))

    reg.register(Tool(
        name="agent_list",
        description="List available sub-agents.",
        input_schema={"type": "object", "properties": {}},
        handler=_agent_list,
        category="agents",
    ))

    reg.register(Tool(
        name="pipeline_run",
        description="Run full pipeline: guard → route → execute → validate → log.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "user_id": {"type": "string", "default": "default"},
                "pattern": {"type": "string", "description": "Multi-agent pattern"},
            },
            "required": ["query"],
        },
        handler=_pipeline_run,
        category="pipeline",
    ))

    reg.register(Tool(
        name="multi_agent_run",
        description="Run a multi-agent coordination pattern.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "default": "pipeline"},
                "query": {"type": "string"},
                "agents": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["pattern", "query"],
        },
        handler=_multi_agent_run,
        category="multi_agent",
    ))

    reg.register(Tool(
        name="guard_check",
        description="Run input/output guardrail checks.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "direction": {"type": "string", "enum": ["input", "output"], "default": "input"},
            },
            "required": ["text"],
        },
        handler=_guard_check,
        category="guardrails",
    ))

    reg.register(Tool(
        name="memory_search",
        description="Search memory layers.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "layers": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        handler=_memory_search,
        category="memory",
    ))

    reg.register(Tool(
        name="rag_query",
        description="Query RAG for relevant documents.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
                "collection": {"type": "string", "default": "default"},
            },
            "required": ["query"],
        },
        handler=_rag_query,
        category="rag",
    ))

    # Cache + Cost
    reg.register(Tool(
        name="cache_get",
        description="Get a value from the prompt cache by key.",
        input_schema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        handler=_cache_get,
        category="cache",
    ))

    reg.register(Tool(
        name="cache_set",
        description="Store a value in the prompt cache with TTL.",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
                "ttl": {"type": "integer", "default": 3600},
            },
            "required": ["key", "value"],
        },
        handler=_cache_set,
        category="cache",
    ))

    reg.register(Tool(
        name="cost_report",
        description="Get cost report from the cost engine: total tokens, cost USD, savings %, cache hit rate.",
        input_schema={
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": ["hour", "day", "week", "all"], "default": "all"},
            },
        },
        handler=_cost_report,
        category="cost",
    ))

    # Skills
    reg.register(Tool(
        name="skills_list",
        description="List all available skills in the skill registry.",
        input_schema={"type": "object", "properties": {}},
        handler=_skills_list,
        category="skills",
    ))

    reg.register(Tool(
        name="skills_load",
        description="Load a skill's full content by name.",
        input_schema={
            "type": "object",
            "properties": {"skill_name": {"type": "string"}},
            "required": ["skill_name"],
        },
        handler=_skills_load,
        category="skills",
    ))

    # Governance
    reg.register(Tool(
        name="governance_check",
        description="Check if an action is allowed by governance policies (safety, cost, quality, compliance).",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["action"],
        },
        handler=_governance_check,
        category="governance",
    ))

    # Eval
    reg.register(Tool(
        name="eval_run",
        description="Run regression eval on an agent against a golden dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "dataset_name": {"type": "string", "default": "qa"},
                "agent_name": {"type": "string", "default": "general"},
            },
        },
        handler=_eval_run,
        category="eval",
    ))

    # System
    reg.register(Tool(
        name="system_status",
        description="Get Agent OS system status, version, and component health.",
        input_schema={"type": "object", "properties": {}},
        handler=_system_status,
        category="system",
    ))

    # Obsidian vault
    reg.register(Tool(
        name="vault_search",
        description="Search the connected Obsidian vault (Second Brain) for notes matching a query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        handler=_vault_search,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_read",
        description="Read a specific note from the Obsidian vault by path.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_vault_read,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_write",
        description="Write a note to the Obsidian vault (creates directories as needed).",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=_vault_write,
        category="vault",
    ))

    # Vault tools (from vault_tools module)
    from .vault_tools import (
        vault_link, vault_tag, vault_moc, vault_tasks,
        vault_graph, vault_analytics,
    )

    # Vault auto-system tools (from auto_tools module)
    from .auto_tools import (
        vault_run_auto_link, vault_run_auto_tag, vault_auto_classify,
        vault_auto_find_duplicates, vault_auto_check_consistency,
        vault_auto_extract_tasks,
    )

    reg.register(Tool(
        name="vault_link",
        description="Create a wiki-link between two notes in the vault. Adds [[target]] to the source note.",
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source note path (relative to vault)"},
                "target": {"type": "string", "description": "Target note path or title"},
                "link_text": {"type": "string", "description": "Optional display text for the link"},
            },
            "required": ["source", "target"],
        },
        handler=vault_link,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_tag",
        description="Add or remove tags from a note's frontmatter.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Note path (relative to vault)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags to add or remove"},
                "action": {"type": "string", "enum": ["add", "remove"], "default": "add"},
            },
            "required": ["path", "tags"],
        },
        handler=vault_tag,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_moc",
        description="Generate a Map of Content (MOC) note for a topic by scanning the vault for related notes.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic name for the MOC"},
                "folder": {"type": "string", "default": "MOC", "description": "Folder to save the MOC in"},
            },
            "required": ["topic"],
        },
        handler=vault_moc,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_tasks",
        description="Extract all TODO/task items from vault notes (checks - [ ], TODO:, ACTION: patterns).",
        input_schema={
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Optional folder to scan (default: whole vault)"},
            },
        },
        handler=vault_tasks,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_graph",
        description="Get a note's relationship graph: outgoing links, backlinks, and related notes by shared tags.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Note path (relative to vault)"},
            },
            "required": ["path"],
        },
        handler=vault_graph,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_analytics",
        description="Get vault-wide statistics: note count, links, orphans, tags, folder distribution.",
        input_schema={"type": "object", "properties": {}},
        handler=vault_analytics,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_auto_link",
        description="Auto-link orphaned notes by title-word overlap.",
        input_schema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
                "max_files": {"type": "integer", "default": 50},
            },
        },
        handler=vault_run_auto_link,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_auto_tag",
        description="Auto-tag notes by content analysis.",
        input_schema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
                "max_files": {"type": "integer", "default": 200},
            },
        },
        handler=vault_run_auto_tag,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_auto_classify",
        description="Classify notes into PARA structure.",
        input_schema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
                "max_files": {"type": "integer", "default": 100},
            },
        },
        handler=vault_auto_classify,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_auto_find_duplicates",
        description="Find duplicate files and similar notes.",
        input_schema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
            },
        },
        handler=vault_auto_find_duplicates,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_auto_check_consistency",
        description="Check vault integrity: broken links, empty files.",
        input_schema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
            },
        },
        handler=vault_auto_check_consistency,
        category="vault",
    ))

    reg.register(Tool(
        name="vault_auto_extract_tasks",
        description="Extract TODOs, FIXMEs, and action items.",
        input_schema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
            },
        },
        handler=vault_auto_extract_tasks,
        category="vault",
    ))

    # Token optimization tools
    from .token_tools import (
        token_optimize, token_report, token_thai,
    )

    reg.register(Tool(
        name="token_optimize",
        description="Optimize text for token savings (RTK/lean-ctx/TTO).",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Command or text to optimize"},
                "context": {
                    "type": "string",
                    "enum": ["command", "file_read", "thai", "general"],
                    "default": "general",
                    "description": "Optimization context: command (RTK prefix), file_read (lean-ctx), thai (TTO), general (auto-detect)",
                },
            },
            "required": ["text"],
        },
        handler=token_optimize,
        category="optimization",
    ))

    reg.register(Tool(
        name="token_report",
        description="Get token savings statistics.",
        input_schema={"type": "object", "properties": {}},
        handler=token_report,
        category="optimization",
    ))

    reg.register(Tool(
        name="token_thai",
        description="Optimize Thai text for token savings.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Thai text to optimize"},
            },
            "required": ["text"],
        },
        handler=token_thai,
        category="optimization",
    ))

    # Vault-memory sync tools
    from .memory_tools import MEMORY_VAULT_TOOLS, memory_vault_sync_task

    for tool_def in MEMORY_VAULT_TOOLS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "memory"),
        ))

    # Self-learning tools
    from .learning_tools import LEARNING_TOOLS

    for tool_def in LEARNING_TOOLS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "learning"),
        ))

    # Auto-router, memory, cache tools
    reg.register(Tool(
        name="auto_route",
        description="Route a prompt to optimal skills/RAG/agent/model/tools.",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The user prompt to route"},
            },
            "required": ["prompt"],
        },
        handler=_auto_route,
        category="routing",
    ))

    reg.register(Tool(
        name="memory_recall",
        description="Recall memories by BM25 keyword matching.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 5},
                "memory_type": {"type": "string", "enum": ["task", "codebase", "preference"],
                                "description": "Optional filter by memory type"},
            },
            "required": ["query"],
        },
        handler=_memory_recall,
        category="memory",
    ))

    reg.register(Tool(
        name="memory_store",
        description="Store a memory: task outcome, codebase knowledge, or user preference.",
        input_schema={
            "type": "object",
            "properties": {
                "memory_type": {"type": "string", "enum": ["task", "codebase", "preference"], "default": "preference"},
                "content": {"type": "string", "description": "Memory content"},
                "key": {"type": "string", "description": "Preference key (for preference type)"},
                "outcome": {"type": "string", "description": "Task outcome (for task type)"},
                "success": {"type": "boolean", "default": True},
                "path": {"type": "string", "description": "File path (for codebase type)"},
                "patterns": {"type": "array", "items": {"type": "string"}},
                "architecture_notes": {"type": "string"},
                "agent_type": {"type": "string"},
                "intent": {"type": "string"},
                "duration_ms": {"type": "number"},
            },
            "required": ["content"],
        },
        handler=_memory_store,
        category="memory",
    ))

    reg.register(Tool(
        name="context_cache_get",
        description="Get cached routing decision for a prompt.",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The prompt to look up"},
            },
            "required": ["prompt"],
        },
        handler=_context_cache_get,
        category="cache",
    ))

    reg.register(Tool(
        name="context_cache_stats",
        description="Context cache hit rate and entry counts.",
        input_schema={"type": "object", "properties": {}},
        handler=_context_cache_stats,
        category="cache",
    ))

    return reg


# JSON-RPC dispatcher

class MCPServer:
    """Minimal MCP server implementation using stdio or SSE."""

    SERVER_NAME = "graxia_tool"
    SERVER_VERSION = "0.2.0"
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or build_default_registry()
        self._initialized = False

    async def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Route an incoming JSON-RPC request. Returns None for notifications."""
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {}) or {}

        # Notifications have no id; only respond to requests
        is_notification = "id" not in req or req_id is None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
                    "capabilities": {"tools": {"listChanged": False}},
                }
                self._initialized = True
                return make_result(req_id, result) if not is_notification else None

            if method == "notifications/initialized":
                # Client signals init complete
                self._initialized = True
                return None

            if method == "tools/list":
                tools = [t.to_mcp_dict() for t in self.registry.list_all()]
                return make_result(req_id, {"tools": tools}) if not is_notification else None

            if method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {}) or {}
                tool = self.registry.get(tool_name)
                if not tool:
                    return make_error(req_id, -32602, f"Unknown tool: {tool_name}")
                try:
                    content = await tool.handler(arguments)
                    return make_result(req_id, content) if not is_notification else None
                except Exception as e:
                    logger.exception("Tool %s raised", tool_name)
                    return make_error(req_id, -32603, f"Tool error: {e}")

            if method == "ping":
                return make_result(req_id, {}) if not is_notification else None

            return make_error(req_id, -32601, f"Method not found: {method}")

        except Exception as e:
            logger.exception("handle_request failed")
            return make_error(req_id, -32603, f"Internal error: {e}")

    # ------------------------------------------------------------------------
    # stdio transport
    # ------------------------------------------------------------------------

    async def run_stdio(self) -> None:
        """Run the server over stdio (JSON-RPC newline-delimited)."""
        logger.info("MCP server starting on stdio")
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
        )
        try:
            while True:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as e:
                    sys.stdout.write(json.dumps(make_error(None, -32700, f"Parse error: {e}")) + "\n")
                    sys.stdout.flush()
                    continue
                response = await self.handle_request(req)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
        except asyncio.CancelledError:
            pass
        finally:
            transport.close()

    # ------------------------------------------------------------------------
    # SSE / HTTP transport (optional)
    # ------------------------------------------------------------------------

    async def run_sse(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run the server over HTTP/SSE. Requires `aiohttp`."""
        try:
            from aiohttp import web  # type: ignore
        except ImportError:
            raise RuntimeError("aiohttp is required for SSE transport. Install with: pip install aiohttp")

        async def handle_http(request: Any) -> Any:
            try:
                body = await request.json()
            except Exception:
                return web.json_response(make_error(None, -32700, "Invalid JSON"), status=400)
            response = await self.handle_request(body)
            return web.json_response(response or {})

        async def handle_sse(request: Any) -> Any:
            response = web.StreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
            )
            await response.prepare(request)
            return response

        app = web.Application()
        app.router.add_post("/mcp", handle_http)
        app.router.add_get("/sse", handle_sse)
        app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))

        logger.info("MCP server starting on http://%s:%d/mcp", host, port)
        web.run_app(app, host=host, port=port)


# ----------------------------------------------------------------------------
# CLI entry
# ----------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Agent OS MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    server = MCPServer()
    if args.transport == "stdio":
        asyncio.run(server.run_stdio())
    else:
        asyncio.run(server.run_sse(args.host, args.port))


if __name__ == "__main__":
    main()
