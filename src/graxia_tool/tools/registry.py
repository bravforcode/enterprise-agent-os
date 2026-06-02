"""Enterprise Agent OS — Tool Registry.

Permission-based tool access (levels 0-4).
Tracks tool usage, enforces access control.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Awaitable
from ..core.models import RiskLevel
from ..core.logging import get_logger

logger = get_logger("tool_registry")


@dataclass
class ToolDefinition:
    """A registered tool with permission level."""
    name: str
    description: str
    permission_level: int  # 0=read, 1=write, 2=exec, 3=db, 4=prod
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    schema_def: dict[str, Any] = field(default_factory=dict)  # JSON Schema
    timeout_seconds: int = 30
    max_retries: int = 2
    category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)
    # Actual execution function
    _executor: Optional[Callable[..., Awaitable[Any]]] = field(default=None, repr=False)


# Permission level names
PERMISSION_NAMES = {
    0: "read",
    1: "write",
    2: "execute",
    3: "database",
    4: "production",
}

# Default tool definitions
DEFAULT_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="file_read",
        description="Read file contents",
        permission_level=0,
        risk_level=RiskLevel.LOW,
        category="filesystem",
        schema_def={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "Start line (0-indexed)"},
                "limit": {"type": "integer", "description": "Max lines to read"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="file_write",
        description="Write content to file",
        permission_level=1,
        risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        category="filesystem",
        schema_def={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"]},
            },
            "required": ["path", "content"],
        },
    ),
    ToolDefinition(
        name="shell_exec",
        description="Execute shell command",
        permission_level=2,
        risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        category="system",
        schema_def={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
                "workdir": {"type": "string"},
            },
            "required": ["command"],
        },
    ),
    ToolDefinition(
        name="database_query",
        description="Execute database query",
        permission_level=3,
        risk_level=RiskLevel.HIGH,
        requires_approval=True,
        category="database",
        schema_def={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "params": {"type": "object"},
                "read_only": {"type": "boolean"},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="deploy",
        description="Deploy to production",
        permission_level=4,
        risk_level=RiskLevel.CRITICAL,
        requires_approval=True,
        category="deployment",
        schema_def={
            "type": "object",
            "properties": {
                "environment": {"type": "string", "enum": ["staging", "production"]},
                "version": {"type": "string"},
                "rollback": {"type": "boolean"},
            },
            "required": ["environment", "version"],
        },
    ),
    ToolDefinition(
        name="git",
        description="Git operations",
        permission_level=1,
        risk_level=RiskLevel.LOW,
        category="vcs",
        schema_def={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "diff", "commit", "push", "pull"]},
                "message": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action"],
        },
    ),
    ToolDefinition(
        name="web_search",
        description="Search the web",
        permission_level=0,
        risk_level=RiskLevel.LOW,
        category="research",
        schema_def={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    ),
]


class ToolRegistry:
    """
    Registry of available tools with permission enforcement.
    """

    def __init__(self):
        self.tools: dict[str, ToolDefinition] = {}
        self._usage_stats: dict[str, int] = {}
        # Load default tools
        for tool in DEFAULT_TOOLS:
            self.tools[tool.name] = tool

    def register(self, tool: ToolDefinition) -> None:
        """Register a new tool."""
        self.tools[tool.name] = tool
        logger.info("tool_registered", name=tool.name, level=tool.permission_level)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self.tools.get(name)

    def can_access(self, tool_name: str, user_level: int) -> bool:
        """Check if user has permission to use a tool."""
        tool = self.tools.get(tool_name)
        if not tool:
            return False
        return tool.permission_level <= user_level

    def requires_approval(self, tool_name: str) -> bool:
        """Check if tool requires human approval."""
        tool = self.tools.get(tool_name)
        if not tool:
            return True  # Unknown tools require approval
        return tool.requires_approval

    def get_tools_for_level(self, max_level: int) -> list[ToolDefinition]:
        """Get all tools accessible at a given permission level."""
        return [t for t in self.tools.values() if t.permission_level <= max_level]

    def get_tools_for_intent(self, intent: str) -> list[ToolDefinition]:
        """Get tools commonly used for an intent."""
        INTENT_TOOLS = {
            "code": ["file_read", "file_write", "shell_exec"],
            "debug": ["file_read", "shell_exec"],
            "test": ["file_read", "shell_exec"],
            "review": ["file_read"],
            "deploy": ["shell_exec", "git", "deploy"],
            "research": ["web_search", "file_read"],
        }
        tool_names = INTENT_TOOLS.get(intent, [])
        return [self.tools[n] for n in tool_names if n in self.tools]

    async def execute(
        self, tool_name: str, params: dict[str, Any], user_level: int = 0
    ) -> dict[str, Any]:
        """Execute a tool with permission check."""
        # Permission check
        if not self.can_access(tool_name, user_level):
            return {
                "success": False,
                "error": f"Permission denied: {tool_name} requires level {self.tools[tool_name].permission_level}",
            }

        # Approval check
        if self.requires_approval(tool_name):
            return {
                "success": False,
                "requires_approval": True,
                "error": f"Tool '{tool_name}' requires human approval",
            }

        tool = self.tools[tool_name]

        # Execute
        if tool._executor:
            try:
                result = await tool._executor(**params)
                self._usage_stats[tool_name] = self._usage_stats.get(tool_name, 0) + 1
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        else:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' has no executor registered",
            }

    def get_usage_stats(self) -> dict[str, int]:
        """Get tool usage statistics."""
        return dict(self._usage_stats)

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self.tools.values())
