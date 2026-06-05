"""
Graxia Tool — MCP Interface Layer

Provides MCP protocol, tool registry, and 5 unified super-tools.
Delegates ALL business logic to `graxia_tool.os`.
"""
from ..mcp import MCPServer, Tool, ToolRegistry, build_default_registry
from ..mcp import _ok, _err, logger
from ..mcp.fast_path import fast_dispatch, get_skill_cache, get_pool

__all__ = [
    "MCPServer", "Tool", "ToolRegistry", "build_default_registry",
    "_ok", "_err", "logger",
    "fast_dispatch", "get_skill_cache", "get_pool",
]
