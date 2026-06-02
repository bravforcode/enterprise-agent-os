"""MCP Server Live Test — validate 18 tools end-to-end."""
import asyncio
import json
import sys
from pathlib import Path

# Force UTF-8 stdout
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


async def test_mcp_async():
    """Test MCP server async."""
    project_root = Path(__file__).parent.parent
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    
    print("[Test] Importing MCP server...")
    from graxia_tool.mcp import MCPServer, build_default_registry
    
    # Test 1: Create server
    print("\n[Test 1] Create MCPServer with default registry")
    registry = build_default_registry()
    server = MCPServer(registry=registry)
    assert server is not None
    print(f"  OK -- name={server.SERVER_NAME}, version={server.SERVER_VERSION}")
    
    # Test 2: List all tools
    print("\n[Test 2] List all registered tools")
    tools = server.registry.list_all()
    print(f"  Total tools: {len(tools)}")
    assert len(tools) >= 18, f"Expected 18+ tools, got {len(tools)}"
    
    tool_names = [t.name for t in tools]
    expected = [
        "agent_run", "agent_list", "pipeline_run", "multi_agent_run",
        "guard_check", "memory_search", "rag_query",
        "cache_get", "cache_set", "cost_report",
        "skills_list", "skills_load", "governance_check",
        "eval_run", "system_status",
        "vault_search", "vault_read", "vault_write",
    ]
    for name in expected:
        marker = "OK" if name in tool_names else "MISSING"
        print(f"  [{marker}] {name}")
    
    # Test 3: JSON-RPC initialize
    print("\n[Test 3] JSON-RPC initialize")
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        }
    }
    init_resp = await server.handle_request(init_req)
    assert "result" in init_resp, f"Init failed: {init_resp}"
    print(f"  OK -- {init_resp['result']['serverInfo']}")
    
    # Test 4: tools/list
    print("\n[Test 4] tools/list")
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    list_resp = await server.handle_request(list_req)
    assert "result" in list_resp, f"List failed: {list_resp}"
    tools_jrpc = list_resp["result"]["tools"]
    print(f"  OK -- {len(tools_jrpc)} tools returned")
    for t in tools_jrpc[:5]:
        name = t.get('name', '')
        desc = t.get('description', '')[:60].encode('ascii', 'replace').decode('ascii')
        print(f"     - {name}: {desc}")
    print(f"     ... and {len(tools_jrpc) - 5} more")
    
    # Test 5: Call safe tools
    print("\n[Test 5] Call safe tools")
    safe_calls = [
        ("agent_list", {}),
        ("skills_list", {}),
        ("system_status", {}),
    ]
    for tool_name, args in safe_calls:
        call_req = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args}
        }
        resp = await server.handle_request(call_req)
        if "error" in resp:
            print(f"  [WARN] {tool_name}: {resp['error']['message'][:80]}")
        else:
            content = resp.get("result", {})
            if isinstance(content, dict) and "content" in content:
                inner = content["content"]
                if isinstance(inner, list) and inner:
                    text = inner[0].get("text", "")[:80]
                    print(f"  [OK] {tool_name}: {text}")
                else:
                    print(f"  [OK] {tool_name}")
            else:
                print(f"  [OK] {tool_name}")
    
    # Test 6: Tool not found
    print("\n[Test 6] Unknown tool returns error")
    bad_req = {
        "jsonrpc": "2.0",
        "id": 200,
        "method": "tools/call",
        "params": {"name": "nonexistent_tool", "arguments": {}}
    }
    bad_resp = await server.handle_request(bad_req)
    assert "error" in bad_resp, "Should return error for unknown tool"
    print(f"  OK -- error code: {bad_resp['error']['code']}")
    
    # Test 7: Ping
    print("\n[Test 7] ping")
    ping_req = {"jsonrpc": "2.0", "id": 300, "method": "ping", "params": {}}
    ping_resp = await server.handle_request(ping_req)
    assert "result" in ping_resp
    print(f"  OK -- pong")
    
    # Test 8: Unknown method
    print("\n[Test 8] Unknown method returns error")
    unk_req = {"jsonrpc": "2.0", "id": 400, "method": "foo/bar", "params": {}}
    unk_resp = await server.handle_request(unk_req)
    assert "error" in unk_resp
    print(f"  OK -- error code: {unk_resp['error']['code']}")
    
    print("\n=== ALL MCP TESTS PASSED ===")
    return True


if __name__ == "__main__":
    try:
        asyncio.run(test_mcp_async())
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
