"""MCP tools for vault-memory sync integration."""
from __future__ import annotations
import asyncio
from typing import Any, Dict
from ..shared.helpers import _ok, _err
from ..memory.vault_sync import VaultMemorySync


# ---------------------------------------------------------------------------
# memory_vault_sync_task
# ---------------------------------------------------------------------------

async def memory_vault_sync_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """Sync a single task outcome to the Obsidian vault."""
    task_id = args.get("task_id", "")
    prompt = args.get("prompt", "")
    success = args.get("success", True)
    agent_type = args.get("agent_type", "")
    outcome = args.get("outcome", "")
    intent = args.get("intent", "")
    domain = args.get("domain", "")
    duration_ms = args.get("duration_ms", 0)
    tokens_used = args.get("tokens_used", 0)

    if not task_id:
        return _err("task_id is required")
    if not prompt:
        return _err("prompt is required")

    def _do():
        sync = VaultMemorySync()
        return sync.sync_task(
            task_id=task_id,
            prompt=prompt,
            success=success,
            agent_type=agent_type,
            outcome=outcome,
            intent=intent,
            domain=domain,
            duration_ms=float(duration_ms),
            tokens_used=int(tokens_used),
        )

    try:
        result = await asyncio.to_thread(_do)
        return _ok({
            "success": result.success,
            "vault_path": result.vault_path,
            "task_id": result.task_id,
            "action": result.action,
            "message": result.message,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# memory_vault_sync_all
# ---------------------------------------------------------------------------

async def memory_vault_sync_all(args: Dict[str, Any]) -> Dict[str, Any]:
    """Sync all unsynced tasks from SessionMemory to the vault."""
    limit = int(args.get("limit", 50))

    def _do():
        sync = VaultMemorySync()
        return sync.full_sync(limit=limit)

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# memory_vault_search
# ---------------------------------------------------------------------------

async def memory_vault_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search vault task notes for relevant knowledge."""
    query = args.get("query", "")
    limit = int(args.get("limit", 10))

    if not query:
        return _err("query is required")

    def _do():
        sync = VaultMemorySync()
        return sync.search_vault(query=query, limit=limit)

    try:
        results = await asyncio.to_thread(_do)
        return _ok({"results": results, "count": len(results)})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# memory_vault_pull
# ---------------------------------------------------------------------------

async def memory_vault_pull(args: Dict[str, Any]) -> Dict[str, Any]:
    """Pull a task note from vault and return parsed data."""
    vault_path = args.get("vault_path", "")
    if not vault_path:
        return _err("vault_path is required")

    def _do():
        sync = VaultMemorySync()
        return sync.pull_task_from_vault(vault_path)

    try:
        result = await asyncio.to_thread(_do)
        if result is None:
            return _ok({"found": False, "vault_path": vault_path})
        return _ok({"found": True, **result})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# memory_vault_list
# ---------------------------------------------------------------------------

async def memory_vault_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List recently synced task notes."""
    days = int(args.get("days", 30))

    def _do():
        sync = VaultMemorySync()
        return sync.list_synced_tasks(days=days)

    try:
        tasks = await asyncio.to_thread(_do)
        return _ok({"tasks": tasks, "count": len(tasks)})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# memory_vault_moc
# ---------------------------------------------------------------------------

async def memory_vault_moc(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Map of Content for all synced tasks."""
    def _do():
        sync = VaultMemorySync()
        return sync.generate_tasks_moc()

    try:
        result = await asyncio.to_thread(_do)
        return _ok({
            "success": result.success,
            "vault_path": result.vault_path,
            "note_count": result.note_count,
            "message": result.message,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# MCP tool definitions (for registration)
# ---------------------------------------------------------------------------

MEMORY_VAULT_TOOLS = [
    {
        "name": "memory_vault_sync_task",
        "description": "Sync a task to vault as markdown note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "prompt": {"type": "string"},
                "success": {"type": "boolean", "default": True},
                "agent_type": {"type": "string"},
                "outcome": {"type": "string"},
                "intent": {"type": "string"},
                "domain": {"type": "string"},
                "duration_ms": {"type": "number"},
                "tokens_used": {"type": "integer"},
            },
            "required": ["task_id", "prompt"],
        },
        "handler": memory_vault_sync_task,
        "category": "memory",
    },
    {
        "name": "memory_vault_sync_all",
        "description": "Sync all unsynced tasks to vault.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
            },
        },
        "handler": memory_vault_sync_all,
        "category": "memory",
    },
    {
        "name": "memory_vault_search",
        "description": "Search vault task notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        "handler": memory_vault_search,
        "category": "memory",
    },
    {
        "name": "memory_vault_pull",
        "description": "Pull and parse a task note from vault.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vault_path": {"type": "string"},
            },
            "required": ["vault_path"],
        },
        "handler": memory_vault_pull,
        "category": "memory",
    },
    {
        "name": "memory_vault_list",
        "description": "List synced task notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
            },
        },
        "handler": memory_vault_list,
        "category": "memory",
    },
    {
        "name": "memory_vault_moc",
        "description": "Generate MOC for synced tasks.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": memory_vault_moc,
        "category": "memory",
    },
]
