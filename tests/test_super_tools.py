"""Tests for super-tools — verifies 8 merged tools replace 46 individual tools."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on sys.path
_root = str(Path(__file__).resolve().parent.parent / "src")
if _root not in sys.path:
    sys.path.insert(0, _root)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _text(result: dict) -> str:
    """Extract text from MCP content result."""
    return result["content"][0]["text"]


def _is_error(result: dict) -> bool:
    return result.get("isError", False)


def _ok(content: Any) -> dict:
    text = content if isinstance(content, str) else json.dumps(content, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


# ─── Import the module under test ─────────────────────────────────────────────

from graxia_tool.mcp.super_tools import (
    SUPER_TOOLS,
    graxia_skills_handler,
    graxia_vault_handler,
    graxia_vault_auto_handler,
    graxia_memory_ext_handler,
    graxia_swarm_handler,
    graxia_autonomous_handler,
    graxia_data_handler,
    graxia_optimize_handler,
)


# ─── 1. SUPER_TOOLS metadata ─────────────────────────────────────────────────

def test_super_tools_count():
    """8 merged tools should be defined."""
    assert len(SUPER_TOOLS) == 8


def test_super_tools_have_required_keys():
    """Each super-tool must have name, description, input_schema, handler."""
    for td in SUPER_TOOLS:
        for key in ("name", "description", "input_schema", "handler"):
            assert key in td, f"Missing key '{key}' in {td.get('name', '?')}"


def test_super_tools_names():
    """Verify the 8 expected tool names."""
    names = {td["name"] for td in SUPER_TOOLS}
    expected = {
        "graxia_skills", "graxia_vault", "graxia_vault_auto",
        "graxia_memory_ext", "graxia_swarm", "graxia_autonomous",
        "graxia_data", "graxia_optimize",
    }
    assert names == expected


# ─── 2. graxia_skills ─────────────────────────────────────────────────────────

def test_graxia_skills_list():
    with patch("graxia_tool.mcp.super_tools.graxia_skills_handler.__wrapped__", create=True):
        pass  # just verify import

    with patch("graxia_tool.skills.list_skills", return_value=["skill-a", "skill-b"]):
        result = _run(graxia_skills_handler({"action": "list"}))
        text = _text(result)
        assert "skill-a" in text
        assert "skill-b" in text


def test_graxia_skills_load():
    mock_skill = MagicMock()
    mock_skill.name = "test-skill"
    mock_skill.content = "# Test"
    mock_skill.tokens = 42

    with patch("graxia_tool.skills.load_skill", return_value=mock_skill):
        result = _run(graxia_skills_handler({"action": "load", "skill_name": "test-skill"}))
        text = _text(result)
        assert "test-skill" in text
        assert "42" in text


def test_graxia_skills_load_missing_name():
    result = _run(graxia_skills_handler({"action": "load"}))
    assert _is_error(result)
    assert "skill_name" in _text(result)


def test_graxia_skills_unknown_action():
    result = _run(graxia_skills_handler({"action": "bogus"}))
    assert _is_error(result)
    assert "Unknown action" in _text(result)


def test_graxia_skills_missing_action():
    result = _run(graxia_skills_handler({}))
    assert _is_error(result)
    assert "action is required" in _text(result)


# ─── 3. graxia_vault ──────────────────────────────────────────────────────────

def test_graxia_vault_search():
    with patch("graxia_tool.integrations.obsidian.ObsidianBridge") as MockBridge:
        instance = MockBridge.return_value
        instance.search = AsyncMock(return_value=[{"title": "note1"}])
        result = _run(graxia_vault_handler({"action": "search", "query": "test"}))
        text = _text(result)
        assert "note1" in text


def test_graxia_vault_read():
    with patch("graxia_tool.integrations.obsidian.ObsidianBridge") as MockBridge:
        instance = MockBridge.return_value
        instance.read_note = AsyncMock(return_value="# Hello")
        result = _run(graxia_vault_handler({"action": "read", "path": "notes/hello.md"}))
        text = _text(result)
        assert "Hello" in text


def test_graxia_vault_write():
    with patch("graxia_tool.integrations.obsidian.ObsidianBridge") as MockBridge:
        instance = MockBridge.return_value
        instance.write_note = AsyncMock(return_value=None)
        result = _run(graxia_vault_handler({"action": "write", "path": "test.md", "content": "hello"}))
        text = _text(result)
        assert "written" in text


def test_graxia_vault_search_missing_query():
    result = _run(graxia_vault_handler({"action": "search"}))
    assert _is_error(result)
    assert "query" in _text(result)


def test_graxia_vault_tag_remapping():
    """vault_tag uses 'action' for add/remove — verify tag_action remapping."""
    with patch("graxia_tool.mcp.vault_tools.vault_tag", new_callable=AsyncMock) as mock_tag:
        mock_tag.return_value = _ok({"tagged": True})
        result = _run(graxia_vault_handler({
            "action": "tag",
            "path": "note.md",
            "tags": ["important"],
            "tag_action": "add",
        }))
        # Verify the mock was called with action="add" (not "tag")
        call_args = mock_tag.call_args[0][0]
        assert call_args["action"] == "add"
        assert call_args["path"] == "note.md"
        assert call_args["tags"] == ["important"]


def test_graxia_vault_unknown_action():
    result = _run(graxia_vault_handler({"action": "nope"}))
    assert _is_error(result)
    assert "Unknown action" in _text(result)


# ─── 4. graxia_vault_auto ─────────────────────────────────────────────────────

def test_graxia_vault_auto_analytics():
    with patch("graxia_tool.mcp.vault_tools.vault_analytics", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"notes": 42})
        result = _run(graxia_vault_auto_handler({"action": "analytics"}))
        assert "42" in _text(result)


def test_graxia_vault_auto_find_duplicates():
    with patch("graxia_tool.mcp.auto_tools.vault_auto_find_duplicates", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"duplicates": []})
        result = _run(graxia_vault_auto_handler({"action": "find_duplicates", "dry_run": True}))
        assert "duplicates" in _text(result)


def test_graxia_vault_auto_check_consistency():
    with patch("graxia_tool.mcp.auto_tools.vault_auto_check_consistency", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"issues": 0})
        result = _run(graxia_vault_auto_handler({"action": "check_consistency"}))
        assert "issues" in _text(result)


def test_graxia_vault_auto_extract_tasks():
    with patch("graxia_tool.mcp.auto_tools.vault_auto_extract_tasks", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"tasks": []})
        result = _run(graxia_vault_auto_handler({"action": "extract_tasks"}))
        assert "tasks" in _text(result)


# ─── 5. graxia_memory_ext ─────────────────────────────────────────────────────

def test_graxia_memory_ext_list_skills():
    with patch("graxia_tool.mcp.acontext_tools.acontext_list_skills", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"skills": ["a", "b"]})
        result = _run(graxia_memory_ext_handler({"action": "list_skills", "space": "coding"}))
        text = _text(result)
        assert "a" in text


def test_graxia_memory_ext_recall():
    with patch("graxia_tool.mcp.acontext_tools.acontext_recall", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"results": [{"skill": "test"}]})
        result = _run(graxia_memory_ext_handler({"action": "recall", "space": "coding", "query": "test"}))
        assert "test" in _text(result)


def test_graxia_memory_ext_delete_skill():
    with patch("graxia_tool.mcp.acontext_tools.acontext_delete_skill", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"deleted": True})
        result = _run(graxia_memory_ext_handler({"action": "delete_skill", "space": "coding", "name": "old-skill"}))
        assert "deleted" in _text(result)


def test_graxia_memory_ext_vault_sync_task():
    with patch("graxia_tool.mcp.memory_tools.memory_vault_sync_task", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"success": True, "vault_path": "tasks/t1.md"})
        result = _run(graxia_memory_ext_handler({
            "action": "vault_sync_task", "task_id": "t1", "prompt": "test",
        }))
        assert "t1" in _text(result)


def test_graxia_memory_ext_vault_search():
    with patch("graxia_tool.mcp.memory_tools.memory_vault_search", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"results": [{"title": "note1"}]})
        result = _run(graxia_memory_ext_handler({
            "action": "vault_search", "query": "test",
        }))
        assert "note1" in _text(result)


def test_graxia_memory_ext_learning_stats():
    with patch("graxia_tool.mcp.learning_tools.learning_stats", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"total_tasks": 5})
        result = _run(graxia_memory_ext_handler({"action": "learning_stats"}))
        assert "5" in _text(result)


def test_graxia_memory_ext_learning_record():
    with patch("graxia_tool.mcp.learning_tools.learning_record", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"recorded": True})
        result = _run(graxia_memory_ext_handler({
            "action": "learning_record", "intent": "code", "agent_used": "coder",
        }))
        assert "recorded" in _text(result)


def test_graxia_memory_ext_learning_reset():
    with patch("graxia_tool.mcp.learning_tools.learning_reset", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"reset": True})
        result = _run(graxia_memory_ext_handler({"action": "learning_reset"}))
        assert "reset" in _text(result)


# ─── 6. graxia_swarm ──────────────────────────────────────────────────────────

def test_graxia_swarm_init():
    with patch("graxia_tool.mcp.swarm_tools.swarm_init", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"swarm_id": "abc", "topology": "hierarchical"})
        result = _run(graxia_swarm_handler({"action": "init", "topology": "hierarchical"}))
        assert "abc" in _text(result)


def test_graxia_swarm_sona_record():
    with patch("graxia_tool.mcp.swarm_tools.sona_record", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"recorded": True})
        result = _run(graxia_swarm_handler({"action": "sona_record", "intent": "code", "agent": "coder"}))
        assert "recorded" in _text(result)


def test_graxia_swarm_sona_suggest():
    with patch("graxia_tool.mcp.swarm_tools.sona_suggest", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"agent": "coder", "score": 0.95})
        result = _run(graxia_swarm_handler({"action": "sona_suggest", "intent": "code"}))
        assert "coder" in _text(result)


def test_graxia_swarm_sona_stats():
    with patch("graxia_tool.mcp.swarm_tools.sona_stats", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"total": 10})
        result = _run(graxia_swarm_handler({"action": "sona_stats"}))
        assert "10" in _text(result)


# ─── 7. graxia_autonomous ─────────────────────────────────────────────────────

def test_graxia_autonomous_load():
    with patch("graxia_tool.mcp.autonomous_tools.context_load", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"content": "# Project"})
        result = _run(graxia_autonomous_handler({"action": "load", "project_path": "/tmp"}))
        assert "Project" in _text(result)


def test_graxia_autonomous_list_runs():
    with patch("graxia_tool.mcp.autonomous_tools.autonomous_list_runs", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"runs": ["run-1"]})
        result = _run(graxia_autonomous_handler({"action": "list_runs"}))
        assert "run-1" in _text(result)


# ─── 8. graxia_data ───────────────────────────────────────────────────────────

def test_graxia_data_generate():
    with patch("graxia_tool.mcp.faker_tools.faker_generate", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"data": ["John"]})
        result = _run(graxia_data_handler({"action": "generate", "category": "person"}))
        assert "John" in _text(result)


def test_graxia_data_locales():
    with patch("graxia_tool.mcp.faker_tools.faker_locales", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"locales": ["en", "th"]})
        result = _run(graxia_data_handler({"action": "locales"}))
        assert "th" in _text(result)


# ─── 9. graxia_optimize ───────────────────────────────────────────────────────

def test_graxia_optimize_report():
    with patch("graxia_tool.mcp.token_tools.token_report", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"saved": 42})
        result = _run(graxia_optimize_handler({"action": "report"}))
        assert "42" in _text(result)


def test_graxia_optimize_thai():
    with patch("graxia_tool.mcp.token_tools.token_thai", new_callable=AsyncMock) as mock:
        mock.return_value = _ok({"original": 100, "optimized": 60})
        result = _run(graxia_optimize_handler({"action": "thai", "text": "สวัสดี"}))
        assert "60" in _text(result)


# ─── 10. Registry integration ─────────────────────────────────────────────────

def test_registry_tool_count():
    """build_default_registry() should register exactly 26 tools."""
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    tools = reg.list_all()
    assert len(tools) == 26, f"Expected 26 tools, got {len(tools)}: {[t.name for t in tools]}"


def test_registry_has_super_tools():
    """All 8 super-tools should be in the registry."""
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    for name in ("graxia_skills", "graxia_vault", "graxia_vault_auto",
                 "graxia_memory_ext", "graxia_swarm", "graxia_autonomous",
                 "graxia_data", "graxia_optimize"):
        assert reg.get(name) is not None, f"Missing super-tool: {name}"


def test_registry_has_standalone_tools():
    """Key standalone tools should still be present."""
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    for name in ("agent_run", "agent_list", "pipeline_run", "multi_agent_run",
                 "system_status", "auto_route", "guard_check", "memory_search",
                 "memory_recall", "memory_store", "rag_query", "cache_get",
                 "cache_set", "cost_report", "context_cache_get",
                 "governance_check", "eval_run", "context_cache_stats"):
        assert reg.get(name) is not None, f"Missing standalone tool: {name}"


def test_registry_no_old_individual_tools():
    """Old individual tools should NOT be in the registry."""
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    removed = [
        "skills_list", "skills_load", "vault_link", "vault_tag", "vault_moc",
        "vault_tasks", "vault_graph", "vault_analytics", "vault_auto_link",
        "vault_auto_tag", "vault_auto_classify", "vault_auto_find_duplicates",
        "vault_auto_check_consistency", "vault_auto_extract_tasks",
        "token_optimize", "token_report", "token_thai",
        "acontext_learn", "acontext_list_skills", "acontext_recall",
        "acontext_get_skill", "acontext_delete_skill",
        "swarm_init", "swarm_run", "swarm_status", "federation_init",
        "federation_send", "federation_list_peers", "sona_record",
        "sona_suggest", "sona_stats",
        "context_load", "context_save", "context_update",
        "autonomous_plan", "autonomous_run", "autonomous_status",
        "autonomous_list_runs",
        "faker_generate", "faker_schema", "faker_locales",
        "learning_stats", "learning_suggest", "learning_record", "learning_reset",
        "memory_vault_sync_task", "memory_vault_sync_all", "memory_vault_search",
        "memory_vault_pull", "memory_vault_list", "memory_vault_moc",
    ]
    for name in removed:
        assert reg.get(name) is None, f"Old tool '{name}' should be removed"


# ─── 11. Schema validation ────────────────────────────────────────────────────

def test_schemas_require_action():
    """All super-tool schemas must require 'action'."""
    for td in SUPER_TOOLS:
        schema = td["input_schema"]
        assert "action" in schema.get("properties", {}), f"{td['name']} missing action property"
        assert "action" in schema.get("required", []), f"{td['name']} missing action from required"


def test_schemas_have_action_enum():
    """All super-tool schemas should enumerate valid actions."""
    for td in SUPER_TOOLS:
        action_prop = td["input_schema"]["properties"]["action"]
        assert "enum" in action_prop, f"{td['name']} action missing enum"
        assert len(action_prop["enum"]) >= 2, f"{td['name']} action enum too small"


# ─── 12. Error handling ───────────────────────────────────────────────────────

def test_all_handlers_reject_missing_action():
    """Every handler returns an error when action is missing."""
    handlers = [
        graxia_skills_handler, graxia_vault_handler, graxia_vault_auto_handler,
        graxia_memory_ext_handler, graxia_swarm_handler, graxia_autonomous_handler,
        graxia_data_handler, graxia_optimize_handler,
    ]
    for h in handlers:
        result = _run(h({}))
        assert _is_error(result), f"{h.__name__} should reject missing action"
        assert "action is required" in _text(result), f"{h.__name__} wrong error message"


def test_all_handlers_reject_unknown_action():
    """Every handler returns an error for an unknown action."""
    handlers = [
        graxia_skills_handler, graxia_vault_handler, graxia_vault_auto_handler,
        graxia_memory_ext_handler, graxia_swarm_handler, graxia_autonomous_handler,
        graxia_data_handler, graxia_optimize_handler,
    ]
    for h in handlers:
        result = _run(h({"action": "__bogus__"}))
        assert _is_error(result), f"{h.__name__} should reject unknown action"
        assert "Unknown action" in _text(result), f"{h.__name__} wrong error message"
