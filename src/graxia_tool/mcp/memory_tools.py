"""MCP tools for vault-memory sync integration.

Exposes VaultMemorySync as MCP tools:
- memory_vault_sync_task: sync a task to vault
- memory_vault_sync_all: sync all unsynced tasks
- memory_vault_search: search vault for task knowledge
- memory_vault_pull: pull a task note from vault
- memory_vault_list: list synced tasks
- memory_vault_moc: generate tasks Map of Content
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from ..memory.vault_sync import VaultMemorySync


def _ok(content: Any) -> Dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "isError": True}


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
        "description": "Sync a task outcome from SessionMemory to the Obsidian vault as a structured markdown note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Unique task identifier"},
                "prompt": {"type": "string", "description": "The original task prompt"},
                "success": {"type": "boolean", "default": True},
                "agent_type": {"type": "string", "description": "Agent that executed the task"},
                "outcome": {"type": "string", "description": "Task outcome / result text"},
                "intent": {"type": "string", "description": "Classified intent"},
                "domain": {"type": "string", "description": "Domain classification"},
                "duration_ms": {"type": "number", "description": "Execution time in ms"},
                "tokens_used": {"type": "integer", "description": "Total tokens consumed"},
            },
            "required": ["task_id", "prompt"],
        },
        "handler": memory_vault_sync_task,
        "category": "memory",
    },
    {
        "name": "memory_vault_sync_all",
        "description": "Sync all unsynced tasks from SessionMemory to the vault. Skips already-synced notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "description": "Max tasks to sync"},
            },
        },
        "handler": memory_vault_sync_all,
        "category": "memory",
    },
    {
        "name": "memory_vault_search",
        "description": "Search vault task notes for relevant knowledge. Returns scored results with snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        "handler": memory_vault_search,
        "category": "memory",
    },
    {
        "name": "memory_vault_pull",
        "description": "Pull a task note from vault and return parsed structured data (task_id, agent, success, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "vault_path": {"type": "string", "description": "Vault-relative path to the note"},
            },
            "required": ["vault_path"],
        },
        "handler": memory_vault_pull,
        "category": "memory",
    },
    {
        "name": "memory_vault_list",
        "description": "List recently synced task notes from the vault.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30, "description": "Only list tasks from last N days"},
            },
        },
        "handler": memory_vault_list,
        "category": "memory",
    },
    {
        "name": "memory_vault_moc",
        "description": "Generate a Map of Content (MOC) note linking all synced tasks in the vault.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": memory_vault_moc,
        "category": "memory",
    },
]
