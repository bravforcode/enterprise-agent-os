"""Merged super-tools — 8 tools replace 46 individual tools.

Each super-tool takes an `action` parameter and routes to the original handler.
All original functionality is preserved via action dispatch.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("graxia_tool.mcp.super_tools")


def _ok(content: Any) -> Dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "isError": True}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_skills
# Replaces: skills_list, skills_load
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_skills_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Manage skills — actions: list, load."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: list, load")

    if action == "list":
        from ..skills import list_skills
        return _ok({"skills": list_skills()})

    elif action == "load":
        from ..skills import load_skill
        skill_name = args.get("skill_name", "")
        if not skill_name:
            return _err("skill_name is required for action='load'")
        try:
            skill = load_skill(skill_name)
            return _ok({"name": skill.name, "content": skill.content, "tokens": skill.tokens})
        except Exception as e:
            return _err(f"{type(e).__name__}: {e}")

    return _err(f"Unknown action: {action}. Use: list, load")


GRAXIA_SKILLS_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "load"],
            "description": "Sub-action to perform.",
        },
        "skill_name": {
            "type": "string",
            "description": "Skill name (required for action='load').",
        },
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_vault
# Replaces: vault_search, vault_read, vault_write, vault_link, vault_tag,
#           vault_moc, vault_tasks, vault_graph
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_vault_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Manage Obsidian vault — actions: search, read, write, link, tag, moc, tasks, graph."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: search, read, write, link, tag, moc, tasks, graph")

    if action == "search":
        from ..integrations.obsidian import ObsidianBridge
        query = args.get("query", "")
        limit = int(args.get("limit", 10))
        if not query:
            return _err("query is required for action='search'")
        try:
            bridge = ObsidianBridge()
            results = await bridge.search(query, limit=limit)
            return _ok({"results": results, "count": len(results)})
        except Exception as e:
            return _err(f"{type(e).__name__}: {e}")

    elif action == "read":
        from ..integrations.obsidian import ObsidianBridge
        path = args.get("path", "")
        if not path:
            return _err("path is required for action='read'")
        try:
            bridge = ObsidianBridge()
            content = await bridge.read_note(path)
            return _ok({"path": path, "content": content})
        except Exception as e:
            return _err(f"{type(e).__name__}: {e}")

    elif action == "write":
        from ..integrations.obsidian import ObsidianBridge
        path = args.get("path", "")
        content = args.get("content", "")
        if not path or content is None:
            return _err("path and content are required for action='write'")
        try:
            bridge = ObsidianBridge()
            await bridge.write_note(path, content)
            return _ok({"path": path, "written": True})
        except Exception as e:
            return _err(f"{type(e).__name__}: {e}")

    elif action == "link":
        from .vault_tools import vault_link
        return await vault_link(args)

    elif action == "tag":
        from .vault_tools import vault_tag
        # vault_tag uses 'action' internally for add/remove — remap from tag_action
        tag_args = {k: v for k, v in args.items() if k != "action"}
        if "tag_action" in tag_args:
            tag_args["action"] = tag_args.pop("tag_action")
        else:
            tag_args["action"] = "add"
        return await vault_tag(tag_args)

    elif action == "moc":
        from .vault_tools import vault_moc
        return await vault_moc(args)

    elif action == "tasks":
        from .vault_tools import vault_tasks
        return await vault_tasks(args)

    elif action == "graph":
        from .vault_tools import vault_graph
        return await vault_graph(args)

    return _err(f"Unknown action: {action}. Use: search, read, write, link, tag, moc, tasks, graph")


GRAXIA_VAULT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search", "read", "write", "link", "tag", "moc", "tasks", "graph"],
            "description": "Sub-action to perform.",
        },
        "query": {"type": "string", "description": "Search query (for search)."},
        "path": {"type": "string", "description": "Note path (for read, write, link, tag, graph)."},
        "content": {"type": "string", "description": "Note content (for write)."},
        "limit": {"type": "integer", "default": 10, "description": "Max results (for search)."},
        "source": {"type": "string", "description": "Source note path (for link)."},
        "target": {"type": "string", "description": "Target note path (for link)."},
        "link_text": {"type": "string", "description": "Display text (for link)."},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags (for tag)."},
        "tag_action": {"type": "string", "enum": ["add", "remove"], "default": "add", "description": "Add or remove tags (for tag)."},
        "topic": {"type": "string", "description": "Topic name (for moc)."},
        "folder": {"type": "string", "description": "Folder path (for moc, tasks)."},
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_vault_auto
# Replaces: vault_auto_link, vault_auto_tag, vault_auto_classify,
#           vault_auto_find_duplicates, vault_auto_check_consistency,
#           vault_auto_extract_tasks, vault_analytics
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_vault_auto_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Vault automation — actions: analytics, auto_link, auto_tag, auto_classify, find_duplicates, check_consistency, extract_tasks."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: analytics, auto_link, auto_tag, auto_classify, find_duplicates, check_consistency, extract_tasks")

    if action == "analytics":
        from .vault_tools import vault_analytics
        return await vault_analytics(args)

    elif action == "auto_link":
        from .auto_tools import vault_run_auto_link
        return await vault_run_auto_link(args)

    elif action == "auto_tag":
        from .auto_tools import vault_run_auto_tag
        return await vault_run_auto_tag(args)

    elif action == "auto_classify":
        from .auto_tools import vault_auto_classify
        return await vault_auto_classify(args)

    elif action == "find_duplicates":
        from .auto_tools import vault_auto_find_duplicates
        return await vault_auto_find_duplicates(args)

    elif action == "check_consistency":
        from .auto_tools import vault_auto_check_consistency
        return await vault_auto_check_consistency(args)

    elif action == "extract_tasks":
        from .auto_tools import vault_auto_extract_tasks
        return await vault_auto_extract_tasks(args)

    return _err(f"Unknown action: {action}. Use: analytics, auto_link, auto_tag, auto_classify, find_duplicates, check_consistency, extract_tasks")


GRAXIA_VAULT_AUTO_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["analytics", "auto_link", "auto_tag", "auto_classify", "find_duplicates", "check_consistency", "extract_tasks"],
            "description": "Sub-action to perform.",
        },
        "dry_run": {"type": "boolean", "default": False, "description": "Preview changes without writing."},
        "max_files": {"type": "integer", "default": 50, "description": "Max files to process."},
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_memory_ext
# Replaces: acontext_learn, acontext_list_skills, acontext_recall,
#           acontext_get_skill, acontext_delete_skill
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_memory_ext_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Extended memory — actions: learn, list_skills, recall, get_skill, delete_skill,
    vault_sync_task, vault_sync_all, vault_search, vault_pull, vault_list, vault_moc,
    learning_stats, learning_suggest, learning_record, learning_reset."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: learn, list_skills, recall, get_skill, delete_skill, "
                     "vault_sync_task, vault_sync_all, vault_search, vault_pull, vault_list, vault_moc, "
                     "learning_stats, learning_suggest, learning_record, learning_reset")

    if action == "learn":
        from .acontext_tools import acontext_learn
        return await acontext_learn(args)

    elif action == "list_skills":
        from .acontext_tools import acontext_list_skills
        return await acontext_list_skills(args)

    elif action == "recall":
        from .acontext_tools import acontext_recall
        return await acontext_recall(args)

    elif action == "get_skill":
        from .acontext_tools import acontext_get_skill
        return await acontext_get_skill(args)

    elif action == "delete_skill":
        from .acontext_tools import acontext_delete_skill
        return await acontext_delete_skill(args)

    elif action == "vault_sync_task":
        from .memory_tools import memory_vault_sync_task
        return await memory_vault_sync_task(args)

    elif action == "vault_sync_all":
        from .memory_tools import memory_vault_sync_all
        return await memory_vault_sync_all(args)

    elif action == "vault_search":
        from .memory_tools import memory_vault_search
        return await memory_vault_search(args)

    elif action == "vault_pull":
        from .memory_tools import memory_vault_pull
        return await memory_vault_pull(args)

    elif action == "vault_list":
        from .memory_tools import memory_vault_list
        return await memory_vault_list(args)

    elif action == "vault_moc":
        from .memory_tools import memory_vault_moc
        return await memory_vault_moc(args)

    elif action == "learning_stats":
        from .learning_tools import learning_stats
        return await learning_stats(args)

    elif action == "learning_suggest":
        from .learning_tools import learning_suggest
        return await learning_suggest(args)

    elif action == "learning_record":
        from .learning_tools import learning_record
        return await learning_record(args)

    elif action == "learning_reset":
        from .learning_tools import learning_reset
        return await learning_reset(args)

    return _err(f"Unknown action: {action}. Use: learn, list_skills, recall, get_skill, delete_skill, "
                "vault_sync_task, vault_sync_all, vault_search, vault_pull, vault_list, vault_moc, "
                "learning_stats, learning_suggest, learning_record, learning_reset")


GRAXIA_MEMORY_EXT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "learn", "list_skills", "recall", "get_skill", "delete_skill",
                "vault_sync_task", "vault_sync_all", "vault_search", "vault_pull", "vault_list", "vault_moc",
                "learning_stats", "learning_suggest", "learning_record", "learning_reset",
            ],
            "description": "Sub-action to perform.",
        },
        "space": {"type": "string", "description": "Space name (e.g. 'coding', 'support')."},
        "session_messages": {
            "type": "array",
            "items": {"type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}},
            "description": "Session messages for learn action.",
        },
        "outcome": {"type": "string", "enum": ["success", "failure", "partial", "unknown"], "default": "success"},
        "outcome_note": {"type": "string"},
        "source_session": {"type": "string"},
        "save": {"type": "boolean", "default": True},
        "dry_run": {"type": "boolean", "default": False},
        "query": {"type": "string", "description": "Search query (for recall, vault_search)."},
        "limit": {"type": "integer", "default": 5},
        "rerank": {"type": "boolean", "default": False},
        "name": {"type": "string", "description": "Skill name (for get_skill, delete_skill)."},
        "task_id": {"type": "string", "description": "Task ID (for vault_sync_task)."},
        "prompt": {"type": "string", "description": "Task prompt (for vault_sync_task)."},
        "success": {"type": "boolean", "default": True},
        "agent_type": {"type": "string"},
        "intent": {"type": "string"},
        "domain": {"type": "string"},
        "duration_ms": {"type": "number"},
        "tokens_used": {"type": "integer"},
        "vault_path": {"type": "string", "description": "Vault path (for vault_pull)."},
        "days": {"type": "integer", "default": 30, "description": "Days to look back (for vault_list)."},
        "data_dir": {"type": "string", "description": "Data directory (for learning tools)."},
        "agent_used": {"type": "string", "description": "Agent used (for learning_record)."},
        "skills_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_swarm
# Replaces: swarm_init, swarm_run, swarm_status, federation_init,
#           federation_send, federation_list_peers, sona_record, sona_suggest,
#           sona_stats
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_swarm_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Swarm orchestration — actions: init, run, status, federation_init, federation_send, federation_list_peers, sona_record, sona_suggest, sona_stats."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: init, run, status, federation_init, federation_send, federation_list_peers, sona_record, sona_suggest, sona_stats")

    if action == "init":
        from .swarm_tools import swarm_init
        return await swarm_init(args)

    elif action == "run":
        from .swarm_tools import swarm_run
        return await swarm_run(args)

    elif action == "status":
        from .swarm_tools import swarm_status
        return await swarm_status(args)

    elif action == "federation_init":
        from .swarm_tools import federation_init
        return await federation_init(args)

    elif action == "federation_send":
        from .swarm_tools import federation_send
        return await federation_send(args)

    elif action == "federation_list_peers":
        from .swarm_tools import federation_list_peers
        return await federation_list_peers(args)

    elif action == "sona_record":
        from .swarm_tools import sona_record
        return await sona_record(args)

    elif action == "sona_suggest":
        from .swarm_tools import sona_suggest
        return await sona_suggest(args)

    elif action == "sona_stats":
        from .swarm_tools import sona_stats
        return await sona_stats(args)

    return _err(f"Unknown action: {action}. Use: init, run, status, federation_init, federation_send, federation_list_peers, sona_record, sona_suggest, sona_stats")


GRAXIA_SWARM_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["init", "run", "status", "federation_init", "federation_send", "federation_list_peers", "sona_record", "sona_suggest", "sona_stats"],
            "description": "Sub-action to perform.",
        },
        "topology": {"type": "string", "enum": ["hierarchical", "mesh", "adaptive"], "default": "hierarchical"},
        "agents": {"type": "array", "items": {"type": "string"}},
        "config": {"type": "object"},
        "auto_register_extended": {"type": "boolean", "default": True},
        "swarm_id": {"type": "string"},
        "query": {"type": "string"},
        "topology_override": {"type": "string", "enum": ["hierarchical", "mesh", "adaptive"]},
        "preferred_agents": {"type": "array", "items": {"type": "string"}},
        "context": {"type": "object"},
        "node_name": {"type": "string"},
        "port": {"type": "integer", "default": 0},
        "host": {"type": "string", "default": "127.0.0.1"},
        "token": {"type": "string"},
        "target_node": {"type": "string"},
        "target_host": {"type": "string"},
        "target_port": {"type": "integer"},
        "source_node": {"type": "string", "default": "external-client"},
        "source_token": {"type": "string"},
        "message_type": {"type": "string"},
        "payload": {"type": "object"},
        "intent": {"type": "string"},
        "agent": {"type": "string"},
        "success": {"type": "boolean", "default": True},
        "duration_ms": {"type": "number", "default": 0},
        "candidates": {"type": "array", "items": {"type": "string"}},
        "top_k": {"type": "integer", "default": 1},
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_autonomous
# Replaces: context_load, context_save, context_update, autonomous_plan,
#           autonomous_run, autonomous_status, autonomous_list_runs
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_autonomous_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Autonomous mode — actions: load, save, update, plan, run, status, list_runs."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: load, save, update, plan, run, status, list_runs")

    if action == "load":
        from .autonomous_tools import context_load
        return await context_load(args)

    elif action == "save":
        from .autonomous_tools import context_save
        return await context_save(args)

    elif action == "update":
        from .autonomous_tools import context_update
        return await context_update(args)

    elif action == "plan":
        from .autonomous_tools import autonomous_plan
        return await autonomous_plan(args)

    elif action == "run":
        from .autonomous_tools import autonomous_run
        return await autonomous_run(args)

    elif action == "status":
        from .autonomous_tools import autonomous_status
        return await autonomous_status(args)

    elif action == "list_runs":
        from .autonomous_tools import autonomous_list_runs
        return await autonomous_list_runs(args)

    return _err(f"Unknown action: {action}. Use: load, save, update, plan, run, status, list_runs")


GRAXIA_AUTONOMOUS_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["load", "save", "update", "plan", "run", "status", "list_runs"],
            "description": "Sub-action to perform.",
        },
        "project_path": {"type": "string", "description": "Project root path."},
        "content": {"type": "string", "description": "Raw markdown (for save)."},
        "project": {"type": "object", "description": "Structured project (for save)."},
        "learnings": {
            "type": "array",
            "items": {"oneOf": [
                {"type": "string"},
                {"type": "object", "properties": {"text": {"type": "string"}, "applied": {"type": "boolean"}, "source": {"type": "string"}}},
            ]},
            "description": "Learnings to append (for update).",
        },
        "goal": {"type": "string", "description": "Goal (for plan, run)."},
        "available_tools": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "max_steps": {"type": "integer", "default": 20},
        "max_replans": {"type": "integer", "default": 2},
        "learn": {"type": "boolean", "default": True},
        "update_context": {"type": "boolean", "default": True},
        "run_id": {"type": "string", "description": "Run ID (for status)."},
        "limit": {"type": "integer", "default": 10, "description": "Max runs (for list_runs)."},
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_data
# Replaces: faker_generate, faker_schema, faker_locales
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_data_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Synthetic data generation — actions: generate, schema, locales."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: generate, schema, locales")

    if action == "generate":
        from .faker_tools import faker_generate
        return await faker_generate(args)

    elif action == "schema":
        from .faker_tools import faker_schema
        return await faker_schema(args)

    elif action == "locales":
        from .faker_tools import faker_locales
        return await faker_locales(args)

    return _err(f"Unknown action: {action}. Use: generate, schema, locales")


GRAXIA_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["generate", "schema", "locales"],
            "description": "Sub-action to perform.",
        },
        "category": {"type": "string", "description": "Data category (for generate)."},
        "field": {"type": "string", "description": "Method within category (for generate)."},
        "count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 1000},
        "locale": {"type": "string", "default": "en"},
        "seed": {"type": "integer"},
        "schema": {"type": "object", "description": "Field->spec mapping (for schema)."},
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Super-tool: graxia_optimize
# Replaces: token_optimize, token_report, token_thai
# ─────────────────────────────────────────────────────────────────────────────

async def graxia_optimize_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Token optimization — actions: optimize, report, thai."""
    action = args.get("action")
    if not action:
        return _err("action is required. Use: optimize, report, thai")

    if action == "optimize":
        from .token_tools import token_optimize
        return await token_optimize(args)

    elif action == "report":
        from .token_tools import token_report
        return await token_report(args)

    elif action == "thai":
        from .token_tools import token_thai
        return await token_thai(args)

    return _err(f"Unknown action: {action}. Use: optimize, report, thai")


GRAXIA_OPTIMIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["optimize", "report", "thai"],
            "description": "Sub-action to perform.",
        },
        "text": {"type": "string", "description": "Text to optimize (for optimize, thai)."},
        "context": {
            "type": "string",
            "enum": ["command", "file_read", "thai", "general"],
            "default": "general",
            "description": "Optimization context (for optimize).",
        },
    },
    "required": ["action"],
}


# ─────────────────────────────────────────────────────────────────────────────
# All super-tools metadata for registration
# ─────────────────────────────────────────────────────────────────────────────

SUPER_TOOLS = [
    {
        "name": "graxia_skills",
        "description": "Manage skills — actions: list, load.",
        "input_schema": GRAXIA_SKILLS_SCHEMA,
        "handler": graxia_skills_handler,
        "category": "skills",
    },
    {
        "name": "graxia_vault",
        "description": "Manage Obsidian vault — actions: search, read, write, link, tag, moc, tasks, graph.",
        "input_schema": GRAXIA_VAULT_SCHEMA,
        "handler": graxia_vault_handler,
        "category": "vault",
    },
    {
        "name": "graxia_vault_auto",
        "description": "Vault automation — actions: analytics, auto_link, auto_tag, auto_classify, find_duplicates, check_consistency, extract_tasks.",
        "input_schema": GRAXIA_VAULT_AUTO_SCHEMA,
        "handler": graxia_vault_auto_handler,
        "category": "vault",
    },
    {
        "name": "graxia_memory_ext",
        "description": "Extended memory — actions: learn, list_skills, recall, get_skill, delete_skill, vault_sync_task, vault_sync_all, vault_search, vault_pull, vault_list, vault_moc, learning_stats, learning_suggest, learning_record, learning_reset.",
        "input_schema": GRAXIA_MEMORY_EXT_SCHEMA,
        "handler": graxia_memory_ext_handler,
        "category": "acontext",
    },
    {
        "name": "graxia_swarm",
        "description": "Swarm orchestration — actions: init, run, status, federation_init, federation_send, federation_list_peers, sona_record, sona_suggest, sona_stats.",
        "input_schema": GRAXIA_SWARM_SCHEMA,
        "handler": graxia_swarm_handler,
        "category": "swarm",
    },
    {
        "name": "graxia_autonomous",
        "description": "Autonomous mode — actions: load, save, update, plan, run, status, list_runs.",
        "input_schema": GRAXIA_AUTONOMOUS_SCHEMA,
        "handler": graxia_autonomous_handler,
        "category": "autonomous",
    },
    {
        "name": "graxia_data",
        "description": "Synthetic data generation — actions: generate, schema, locales.",
        "input_schema": GRAXIA_DATA_SCHEMA,
        "handler": graxia_data_handler,
        "category": "faker",
    },
    {
        "name": "graxia_optimize",
        "description": "Token optimization — actions: optimize, report, thai.",
        "input_schema": GRAXIA_OPTIMIZE_SCHEMA,
        "handler": graxia_optimize_handler,
        "category": "optimization",
    },
]
