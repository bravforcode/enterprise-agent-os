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
    from ..guards import check_input, check_output

    text = args.get("text", "")
    direction = args.get("direction", "input")  # input | output

    if not text:
        return _err("text is required")

    try:
        if direction == "input":
            result = check_input(text)
        else:
            result = check_output(text)

        return _ok({
            "allowed": result.passed,
            "risk_level": result.severity,
            "issues": [result.reason] if not result.passed else [],
            "sanitized": text,
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
        mem = SessionMemory(db_path=_get_session_db_path())
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

    if not query:
        return _err("query is required")

    try:
        rag = RAGOS()
        result = rag.query(query, top_k=top_k)
        # RAGOS.query() returns a RAGResult dataclass — serialise it
        return _ok({
            "query": result.query,
            "results": [
                {"content": r.chunk.content, "score": r.score, "citation": r.citation}
                for r in result.chunks
            ],
            "context": result.context,
            "citations": result.citations,
            "estimated_tokens": result.estimated_tokens,
        })
    except Exception as e:
        logger.exception("rag_query failed")
        return _err(f"{type(e).__name__}: {e}")


# In-memory fallback cache (used when Redis is unavailable)
_FALLBACK_CACHE: Dict[str, Any] = {}


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
    except Exception:
        # Redis unavailable — fall back to in-memory cache
        value = _FALLBACK_CACHE.get(key)
        return _ok({"key": key, "value": value, "hit": value is not None, "backend": "memory"})


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
    except Exception:
        # Redis unavailable — fall back to in-memory cache
        _FALLBACK_CACHE[key] = value
        return _ok({"key": key, "stored": True, "ttl": ttl, "backend": "memory"})


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


def _get_session_db_path() -> str:
    """Return persistent path for session memory DB."""
    db_dir = Path.home() / ".graxia"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "session_memory.db")


async def _memory_recall(args: Dict[str, Any]) -> Dict[str, Any]:
    """Recall relevant memories for a query using BM25 keyword matching."""
    from ..session_memory import SessionMemory

    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    memory_type = args.get("memory_type")  # Optional filter: task, codebase, preference

    if not query:
        return _err("query is required")

    try:
        mem = SessionMemory(db_path=_get_session_db_path())
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
        mem = SessionMemory(db_path=_get_session_db_path())
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
    """Build the default MCP tool registry — 26 tools (15 standalone + 8 super-tools + 3 kept)."""
    reg = ToolRegistry()

    # =========================================================================
    # 15 high-frequency standalone tools
    # =========================================================================

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
        name="system_status",
        description="Get Agent OS system status, version, and component health.",
        input_schema={"type": "object", "properties": {}},
        handler=_system_status,
        category="system",
    ))

    reg.register(Tool(
        name="auto_route",
        description="MANDATORY FIRST STEP: Route user prompt to optimal skills, RAG, agents, models, and tools. Call this BEFORE any other action. Auto-triggers on: every user message, coding tasks, debugging, research, file operations, search, multi-step work.",
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
        name="memory_recall",
        description="MANDATORY SECOND STEP: Recall past memories by BM25 keyword matching. Call this AFTER auto_route. Auto-triggers on: every task, coding, debugging, research, file operations.",
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
        name="rag_query",
        description="MANDATORY FOR CODING: Query RAG for relevant documents. Auto-triggers on: coding tasks, debugging, code search, documentation lookup, implementation questions.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        handler=_rag_query,
        category="rag",
    ))

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

    # =========================================================================
    # 8 merged super-tools (replace 46 individual tools)
    # =========================================================================

    from .super_tools import SUPER_TOOLS

    for tool_def in SUPER_TOOLS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "general"),
        ))

    # =========================================================================
    # 2 additional kept tools (governance_check moved to governance module)
    # =========================================================================

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

    reg.register(Tool(
        name="context_cache_stats",
        description="Context cache hit rate and entry counts.",
        input_schema={"type": "object", "properties": {}},
        handler=_context_cache_stats,
        category="cache",
    ))

    # =========================================================================
    # Governance tools (content filters + audit trail)
    # =========================================================================

    from .governance import GOVERNANCE_TOOL_SPECS

    for tool_def in GOVERNANCE_TOOL_SPECS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "governance"),
        ))

    # =========================================================================
    # Declarative workflow tools
    # =========================================================================

    from .workflows import WORKFLOW_TOOL_SPECS

    for tool_def in WORKFLOW_TOOL_SPECS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "workflow"),
        ))

    # =========================================================================
    # Hybrid RAG tools
    # =========================================================================

    from .hybrid_rag import HYBRID_RAG_TOOLS

    for tool_def in HYBRID_RAG_TOOLS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "rag"),
        ))

    # =========================================================================
    # Progressive Skill Loader tools (metadata-first)
    # =========================================================================

    from .skill_loader import SKILL_LOADER_TOOLS

    for tool_def in SKILL_LOADER_TOOLS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "skills"),
        ))

    # =========================================================================
    # Incremental Sync tools (Merkle tree-based)
    # =========================================================================

    from .incremental_sync import INCREMENTAL_SYNC_TOOLS

    for tool_def in INCREMENTAL_SYNC_TOOLS:
        reg.register(Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
            category=tool_def.get("category", "sync"),
        ))

    return reg


# JSON-RPC dispatcher

class MCPServer:
    """Minimal MCP server implementation using stdio or SSE."""

    SERVER_NAME = "graxia_tool"
    SERVER_VERSION = "0.5.0"
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
        """Run the server over stdio (JSON-RPC newline-delimited).

        Uses a thread-based stdin reader to avoid the Windows asyncio
        ProactorEventLoop + connect_read_pipe(sys.stdin) bug.
        """
        import threading

        logger.info("MCP server starting on stdio")
        loop = asyncio.get_event_loop()
        write_lock = threading.Lock()

        def _write_response(response: Dict[str, Any]) -> None:
            """Thread-safe write to stdout."""
            data = json.dumps(response) + "\n"
            with write_lock:
                sys.stdout.write(data)
                sys.stdout.flush()

        def blocking_reader() -> None:
            """Read line-by-line from stdin, dispatch async, write to stdout."""
            try:
                for line in sys.stdin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line)
                    except json.JSONDecodeError as e:
                        _write_response(make_error(None, -32700, f"Parse error: {e}"))
                        continue
                    future = asyncio.run_coroutine_threadsafe(
                        self.handle_request(req), loop
                    )
                    try:
                        response = future.result(timeout=60)
                    except TimeoutError:
                        logger.warning("Request timed out: %s", req.get("method"))
                        response = make_error(req.get("id"), -32603, "Request timed out")
                    except Exception as e:
                        logger.exception("handle_request failed in stdio thread")
                        response = make_error(req.get("id"), -32603, f"Internal error: {e}")
                    if response is not None:
                        _write_response(response)
            except (EOFError, KeyboardInterrupt):
                pass
            except Exception:
                logger.exception("stdin reader crashed")

        await loop.run_in_executor(None, blocking_reader)

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

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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
