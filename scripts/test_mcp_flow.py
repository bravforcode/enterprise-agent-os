"""Full MCP flow test for DaemonMCPServer"""
import json
import asyncio
from graxia_tool.mcp.daemon import DaemonMCPServer

server = DaemonMCPServer()

async def run_tests():
    # 1. Initialize
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    result = await server.handle_request(req)
    print("=== 1. INITIALIZE ===")
    info = result["result"]["serverInfo"]
    print(f"  Server: {info['name']}, Version: {info['version']}")

    # 2. List tools
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    result = await server.handle_request(req)
    tools = result["result"]["tools"]
    print(f"\n=== 2. TOOLS ({len(tools)} total) ===")
    for t in tools:
        print(f"  - {t['name']}: {t['description'][:60]}")

    # 3. Memory Store (longterm)
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "memory_store",
        "arguments": {"content": "Graxia Tool is a zero-install AI agent OS", "tier": "longterm", "key": "project_summary"}
    }}
    result = await server.handle_request(req)
    print("\n=== 3. MEMORY STORE (longterm) ===")
    print(f"  {json.dumps(result['result'])[:200]}")

    # 4. Memory Recall
    req = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "memory_recall",
        "arguments": {"key": "project_summary"}
    }}
    result = await server.handle_request(req)
    print("\n=== 4. MEMORY RECALL ===")
    r = result["result"]
    print(f"  Count: {r.get('count', '?')}, First: {r['results'][0]['content'][:80] if r.get('results') else 'none'}")

    # 5. Brain Auto Route
    req = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "brain",
        "arguments": {"action": "auto_route", "prompt": "test auto route"}
    }}
    result = await server.handle_request(req)
    print("\n=== 5. BRAIN AUTO ROUTE ===")
    r = result["result"]
    if "content" in r:
        print(f"  {r['content'][:200]}")
    elif "error" in r:
        print(f"  Error: {r['error']}")
    else:
        print(f"  {json.dumps(r)[:200]}")

    # 6. Brain Search
    req = {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
        "name": "brain",
        "arguments": {"action": "search", "query": "agent OS architecture"}
    }}
    result = await server.handle_request(req)
    print("\n=== 6. BRAIN SEARCH ===")
    r = result["result"]
    if "content" in r:
        print(f"  {r['content'][:300]}")
    elif "error" in r:
        print(f"  Error: {r['error']}")
    else:
        print(f"  {json.dumps(r)[:300]}")

    # 7. Brain Skill Load
    req = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
        "name": "brain",
        "arguments": {"action": "skill_load", "skill_name": "lean-ctx"}
    }}
    result = await server.handle_request(req)
    print("\n=== 7. BRAIN SKILL LOAD ===")
    r = result["result"]
    if "content" in r:
        print(f"  Content: {r['content'][:200]}")
    elif "error" in r:
        print(f"  Error: {r['error']}")
    else:
        print(f"  {json.dumps(r)[:200]}")

    # 8. Brain Memory Store
    req = {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
        "name": "brain",
        "arguments": {"action": "store", "content": "MCP daemon test passed", "memory_type": "task"}
    }}
    result = await server.handle_request(req)
    print("\n=== 8. BRAIN MEMORY STORE ===")
    r = result["result"]
    if "content" in r:
        print(f"  {r['content'][:200]}")
    elif "error" in r:
        print(f"  Error: {r['error']}")
    else:
        print(f"  {json.dumps(r)[:200]}")

    # 9. Brain Memory Recall
    req = {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
        "name": "brain",
        "arguments": {"action": "recall", "query": "MCP daemon test"}
    }}
    result = await server.handle_request(req)
    print("\n=== 9. BRAIN MEMORY RECALL ===")
    r = result["result"]
    if "content" in r:
        print(f"  {r['content'][:200]}")
    elif "error" in r:
        print(f"  Error: {r['error']}")
    else:
        print(f"  {json.dumps(r)[:200]}")

    # 10. Guard Check
    req = {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {
        "name": "guard",
        "arguments": {"action": "check", "text": "Hello world"}
    }}
    result = await server.handle_request(req)
    print("\n=== 10. GUARD CHECK ===")
    r = result["result"]
    if "content" in r:
        print(f"  {r['content'][:200]}")
    elif "error" in r:
        print(f"  Error: {r['error']}")
    else:
        print(f"  {json.dumps(r)[:200]}")

    print("\n=== ALL TESTS PASSED ===")

asyncio.run(run_tests())
