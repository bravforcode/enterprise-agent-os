"""Universal adapter — export Agent OS as tool/function definitions for any LLM.

Supports formats:
- Anthropic (Claude): tool_use blocks
- OpenAI (GPT-4, local): function calling
- Gemini: function_declarations
- Generic: OpenAI-compatible JSON (works with most local LLMs)
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------------
# Format-specific exporters
# ----------------------------------------------------------------------------

def to_anthropic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic tool_use format.

    Anthropic format:
    {"name": ..., "description": ..., "input_schema": {...}}
    """
    out: List[Dict[str, Any]] = []
    for tool in tools:
        out.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("inputSchema", {"type": "object", "properties": {}}),
        })
    return out


def to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tool definitions to OpenAI function-calling format.

    OpenAI format:
    {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
    """
    out: List[Dict[str, Any]] = []
    for tool in tools:
        out.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            },
        })
    return out


def to_gemini_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tool definitions to Gemini function_declarations format."""
    out: List[Dict[str, Any]] = []
    for tool in tools:
        out.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        })
    return [{"function_declarations": out}]


def to_generic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generic OpenAI-compatible format (works with most local LLMs via Ollama, etc.)."""
    return to_openai_tools(tools)


# ----------------------------------------------------------------------------
# Vault agent adapter — map 12 routing agents → Agent OS tools
# ----------------------------------------------------------------------------

VAULT_AGENT_MAP: Dict[str, Dict[str, str]] = {
    "architect": {
        "agent_os_tool": "pipeline_run",
        "description": "Scaffold MOCs, areas, templates for the vault",
        "param_map": {"query": "scaffold vault structure for {user_input}"},
    },
    "scribe": {
        "agent_os_tool": "vault_write",
        "description": "Capture raw text into vault inbox",
        "param_map": {"path": "00-Inbox/captured-{timestamp}.md", "content": "{user_input}"},
    },
    "seeker": {
        "agent_os_tool": "vault_search",
        "description": "Vault-wide retrieval",
        "param_map": {"query": "{user_input}", "limit": 10},
    },
    "connector": {
        "agent_os_tool": "vault_search",
        "description": "Build note relationships — find related notes",
        "param_map": {"query": "related to {user_input}", "limit": 20},
    },
    "librarian": {
        "agent_os_tool": "agent_run",
        "description": "Cleanup, dedup, link repair (uses general agent)",
        "param_map": {"agent_name": "general", "query": "audit and clean vault: {user_input}"},
    },
    "postman": {
        "agent_os_tool": "agent_run",
        "description": "Gmail / Calendar ops (placeholder)",
        "param_map": {"agent_name": "general", "query": "postman: {user_input}"},
    },
    "strategist": {
        "agent_os_tool": "agent_run",
        "description": "Goal alignment (uses planner agent)",
        "param_map": {"agent_name": "planner", "query": "strategy: {user_input}"},
    },
    "ghostwriter": {
        "agent_os_tool": "agent_run",
        "description": "Voice-mimic drafting (uses documenter agent)",
        "param_map": {"agent_name": "documenter", "query": "draft: {user_input}"},
    },
    "auditor": {
        "agent_os_tool": "agent_run",
        "description": "Adversarial review (uses security_auditor agent)",
        "param_map": {"agent_name": "security_auditor", "query": "audit: {user_input}"},
    },
    "researcher": {
        "agent_os_tool": "rag_query",
        "description": "Web/knowledge research via RAG",
        "param_map": {"query": "{user_input}", "top_k": 10},
    },
    "pulse": {
        "agent_os_tool": "system_status",
        "description": "Daily summary / system status",
        "param_map": {},
    },
    "bridge": {
        "agent_os_tool": "agent_run",
        "description": "Sync notes ↔ code (uses coder agent)",
        "param_map": {"agent_name": "coder", "query": "bridge: {user_input}"},
    },
}


def expand_vault_agent(agent_name: str, user_input: str) -> Optional[Dict[str, Any]]:
    """Expand a vault routing agent invocation into an Agent OS tool call."""
    import time
    mapping = VAULT_AGENT_MAP.get(agent_name)
    if not mapping:
        return None

    template = dict(mapping["param_map"])  # copy
    # Substitute placeholders
    for k, v in template.items():
        if isinstance(v, str):
            template[k] = v.replace("{user_input}", user_input).replace("{timestamp}", str(int(time.time())))
    return {
        "tool": mapping["agent_os_tool"],
        "arguments": template,
        "description": mapping["description"],
    }


# ----------------------------------------------------------------------------
# Convenience: export all tools in the requested format
# ----------------------------------------------------------------------------

def export_all_tools(format: str = "openai") -> List[Dict[str, Any]]:
    """Export all Agent OS MCP tools in the requested LLM format.

    Args:
        format: "anthropic" | "openai" | "gemini" | "generic"
    """
    from ..mcp import build_default_registry

    reg = build_default_registry()
    tools = [t.to_mcp_dict() for t in reg.list_all()]

    if format == "anthropic":
        return to_anthropic_tools(tools)
    if format == "openai":
        return to_openai_tools(tools)
    if format == "gemini":
        return to_gemini_tools(tools)
    return to_generic_tools(tools)


def export_skill_manifest() -> Dict[str, Any]:
    """Export the Agent OS skill manifest in a vendor-neutral format.

    Compatible with Anthropic's skill spec: each skill has name, description, when_to_use, inputs.
    """
    from ..mcp import build_default_registry
    from ..agents import list_agents

    reg = build_default_registry()
    manifest = {
        "name": "agent-os",
        "version": "0.1.0",
        "description": "Enterprise AI Agent OS — 15 sub-agents, 7 multi-agent patterns, governance, cost engine, RAG, memory, vault integration.",
        "tools": [t.to_mcp_dict() for t in reg.list_all()],
        "agents": list_agents(),
        "categories": sorted({t.category for t in reg.list_all()}),
    }
    return manifest
