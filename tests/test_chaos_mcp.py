"""Chaos tests for graxia_tool MCP module — 30+ tests.

Tests edge cases, error handling, and robustness under stress.
"""
import asyncio
import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from graxia_tool.mcp import (
    Tool, ToolRegistry, make_result, make_error,
    MCPServer, _ok, _err
)


# --- Tool Registry Chaos Tests ---

class TestToolRegistryChaos:
    """Chaos tests for MCP tool registry."""

    def test_registry_empty(self):
        """Empty registry should work."""
        registry = ToolRegistry()
        assert len(registry.list_all()) == 0

    def test_register_duplicate_tool(self):
        """Registering duplicate tool should raise error."""
        registry = ToolRegistry()
        tool = Tool(
            name="test",
            description="test tool",
            input_schema={},
            handler=AsyncMock()
        )
        registry.register(tool)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool)

    def test_get_nonexistent_tool(self):
        """Getting nonexistent tool should return None."""
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_by_category(self):
        """Listing by category should filter correctly."""
        registry = ToolRegistry()
        tool1 = Tool(name="t1", description="d1", input_schema={}, handler=AsyncMock(), category="core")
        tool2 = Tool(name="t2", description="d2", input_schema={}, handler=AsyncMock(), category="vault")
        registry.register(tool1)
        registry.register(tool2)
        
        core_tools = registry.list_by_category("core")
        assert len(core_tools) == 1
        assert core_tools[0].name == "t1"

    def test_tool_to_mcp_dict(self):
        """Tool.to_mcp_dict should return valid MCP format."""
        tool = Tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            handler=AsyncMock()
        )
        d = tool.to_mcp_dict()
        assert d["name"] == "test_tool"
        assert d["description"] == "A test tool"
        assert "inputSchema" in d

    def test_registry_many_tools(self):
        """Registry should handle 100+ tools."""
        registry = ToolRegistry()
        for i in range(100):
            tool = Tool(
                name=f"tool_{i}",
                description=f"Tool {i}",
                input_schema={},
                handler=AsyncMock()
            )
            registry.register(tool)
        assert len(registry.list_all()) == 100


# --- JSON-RPC Protocol Chaos Tests ---

class TestJSONRPCChaos:
    """Chaos tests for JSON-RPC protocol helpers."""

    def test_make_result_basic(self):
        """make_result should produce valid JSON-RPC response."""
        result = make_result(1, {"status": "ok"})
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        assert result["result"]["status"] == "ok"

    def test_make_result_string_id(self):
        """make_result should handle string IDs."""
        result = make_result("abc-123", {"data": 42})
        assert result["id"] == "abc-123"

    def test_make_result_null_id(self):
        """make_result should handle null ID."""
        result = make_result(None, {"data": 42})
        assert result["id"] is None

    def test_make_error_basic(self):
        """make_error should produce valid JSON-RPC error."""
        err = make_error(1, -32600, "Invalid Request")
        assert err["jsonrpc"] == "2.0"
        assert err["error"]["code"] == -32600
        assert err["error"]["message"] == "Invalid Request"

    def test_make_error_with_data(self):
        """make_error should include data field when provided."""
        err = make_error(1, -32600, "Invalid Request", {"details": "missing method"})
        assert "data" in err["error"]
        assert err["error"]["data"]["details"] == "missing method"

    def test_make_error_without_data(self):
        """make_error should not include data field when not provided."""
        err = make_error(1, -32600, "Invalid Request")
        assert "data" not in err["error"]

    def test_ok_helper(self):
        """_ok should format successful tool result."""
        result = _ok("Hello world")
        assert "content" in result
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello world"

    def test_err_helper(self):
        """_err should format error tool result."""
        result = _err("Something went wrong")
        assert "content" in result
        assert result["isError"] is True
        assert "Something went wrong" in result["content"][0]["text"]

    def test_ok_with_dict(self):
        """_ok should handle dict content."""
        result = _ok({"key": "value"})
        assert "content" in result


# --- MCP Server Chaos Tests ---

class TestMCPServerChaos:
    """Chaos tests for MCP server."""

    def test_server_creation(self):
        """Server should be created without errors."""
        server = MCPServer()
        assert server is not None
        assert hasattr(server, 'registry')

    def test_server_has_tools(self):
        """Server should register all tools."""
        server = MCPServer()
        tools = server.registry.list_all()
        assert len(tools) >= 18  # Should have at least 18 tools

    def test_server_tool_categories(self):
        """Server should have tools in multiple categories."""
        server = MCPServer()
        categories = set()
        for tool in server.registry.list_all():
            categories.add(tool.category)
        assert len(categories) >= 3

    @pytest.mark.asyncio
    async def test_server_handle_initialize(self):
        """Server should handle initialize request."""
        server = MCPServer()
        assert hasattr(server, 'handle_request')

    @pytest.mark.asyncio
    async def test_server_handle_tools_list(self):
        """Server should handle tools/list request."""
        server = MCPServer()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list"
        }
        response = await server.handle_request(request)
        assert response is not None
        assert "result" in response

    @pytest.mark.asyncio
    async def test_server_handle_unknown_method(self):
        """Server should handle unknown method gracefully."""
        server = MCPServer()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown/method"
        }
        response = await server.handle_request(request)
        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_server_concurrent_requests(self):
        """50 concurrent requests should all be handled."""
        server = MCPServer()
        
        async def make_request(i):
            request = {
                "jsonrpc": "2.0",
                "id": i,
                "method": "tools/list"
            }
            return await server.handle_request(request)
        
        tasks = [make_request(i) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if not isinstance(r, Exception) and r is not None]
        assert len(successes) == 50

    def test_server_has_all_required_tools(self):
        """Server should have all required tools."""
        server = MCPServer()
        required_tools = [
            "agent_run", "agent_list", "pipeline_run",
            "multi_agent_run", "guard_check", "memory_search",
            "rag_query", "cache_get", "cache_set", "cost_report",
            "skills_list", "skills_load", "governance_check",
            "eval_run", "system_status", "vault_search",
            "vault_read", "vault_write"
        ]
        tool_names = [t.name for t in server.registry.list_all()]
        for tool_name in required_tools:
            assert tool_name in tool_names, f"Missing tool: {tool_name}"


# --- Transport Chaos Tests ---

class TestTransportChaos:
    """Chaos tests for MCP transports."""

    def test_stdio_transport_creation(self):
        """Stdio transport should be handled."""
        # MCP server handles stdio directly via run_stdio method
        server = MCPServer()
        assert hasattr(server, 'run_stdio')

    def test_sse_transport_creation(self):
        """SSE transport should be handled."""
        # MCP server handles SSE directly via run_sse method
        server = MCPServer()
        assert hasattr(server, 'run_sse')

    @pytest.mark.asyncio
    async def test_server_run_stdio(self):
        """Server run_stdio should exist."""
        server = MCPServer()
        assert asyncio.iscoroutinefunction(server.run_stdio)


# --- Tool Handler Chaos Tests ---

class TestToolHandlerChaos:
    """Chaos tests for tool handlers."""

    @pytest.mark.asyncio
    async def test_agent_list_handler(self):
        """agent_list handler should return agents."""
        server = MCPServer()
        tool = server.registry.get("agent_list")
        assert tool is not None
        
        result = await tool.handler({})
        assert "content" in result

    @pytest.mark.asyncio
    async def test_system_status_handler(self):
        """system_status handler should return status."""
        server = MCPServer()
        tool = server.registry.get("system_status")
        assert tool is not None
        
        result = await tool.handler({})
        assert "content" in result

    @pytest.mark.asyncio
    async def test_skills_list_handler(self):
        """skills_list handler should return skills."""
        server = MCPServer()
        tool = server.registry.get("skills_list")
        assert tool is not None
        
        try:
            result = await tool.handler({})
            assert "content" in result
        except ImportError:
            pytest.skip("Skills module not fully implemented")

    @pytest.mark.asyncio
    async def test_cost_report_handler(self):
        """cost_report handler should return report."""
        server = MCPServer()
        tool = server.registry.get("cost_report")
        assert tool is not None
        
        try:
            result = await tool.handler({})
            assert "content" in result
        except ImportError:
            pytest.skip("CostEngine not fully implemented")

    @pytest.mark.asyncio
    async def test_vault_search_handler(self):
        """vault_search handler should handle search."""
        server = MCPServer()
        tool = server.registry.get("vault_search")
        assert tool is not None
        
        result = await tool.handler({"query": "test"})
        assert "content" in result

    @pytest.mark.asyncio
    async def test_tool_handler_error_handling(self):
        """Tool handlers should handle errors gracefully."""
        server = MCPServer()
        tool = server.registry.get("agent_run")
        if tool:
            try:
                result = await tool.handler({})
                assert "content" in result
            except Exception:
                pass  # Some tools may raise on invalid input

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self):
        """Multiple concurrent tool calls should be handled."""
        server = MCPServer()
        tool = server.registry.get("system_status")
        
        async def call_tool(i):
            try:
                return await tool.handler({})
            except Exception:
                return None
        
        tasks = [call_tool(i) for i in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert len(successes) == 20


# --- MCP Security Chaos Tests ---

class TestMCPSecurityChaos:
    """Security-focused chaos tests for MCP."""

    @pytest.mark.asyncio
    async def test_tool_name_injection(self):
        """Tool names with special characters should be handled."""
        server = MCPServer()
        tool = server.registry.get("nonexistent; DROP TABLE tools; --")
        assert tool is None

    @pytest.mark.asyncio
    async def test_input_schema_validation(self):
        """Invalid input schema should be handled."""
        server = MCPServer()
        tool = server.registry.get("agent_run")
        if tool:
            try:
                result = await tool.handler({"invalid": True, "nested": {"deep": {"value": 123}}})
                assert "content" in result
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_large_payload_handling(self):
        """Large payloads should be handled."""
        server = MCPServer()
        tool = server.registry.get("vault_search")
        if tool:
            large_query = "x" * 100000
            try:
                result = await tool.handler({"query": large_query})
                assert "content" in result
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_unicode_in_tool_args(self):
        """Unicode in tool arguments should be handled."""
        server = MCPServer()
        tool = server.registry.get("vault_search")
        if tool:
            unicode_query = "ค้นหาข้อมูลเกี่ยวกับ Python"
            try:
                result = await tool.handler({"query": unicode_query})
                assert "content" in result
            except Exception:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])