"""MCP tools for skill management.

This package contains all MCP tool implementations for the
mcp-skillset server. Tools are automatically registered with
FastMCP when imported.

Consolidated Tools (v2.0):
- find_tool: Unified find() tool for discovery (replaces 4 separate tools)
- skill_tool: Unified skill() tool for CRUD operations (replaces 3 separate tools)

Legacy Implementation:
- skill_tools_legacy.py: Archived 7-tool implementation (reference only)
"""

# Import all tool modules to register them with FastMCP
from . import (
    find_tool,  # noqa: F401
    skill_tool,  # noqa: F401
)


__all__ = ["find_tool", "skill_tool"]
