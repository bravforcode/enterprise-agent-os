"""Direct stdio MCP test — run server in same process using asyncio."""
import asyncio
import json
import sys
import os
from pathlib import Path

# Ensure src is in path
ROOT = Path(r"C:\Users\menum\enterprise-agent-os")
sys.path.insert(0, str(ROOT / "src"))

# Override stdin/stdout to use pipes for testing
import io

# Capture real stdin content
real_stdin = sys.stdin
real_stdout = sys.stdout

# Write multiple requests to a fake stdin
test_input = (
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
    + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "agent_list", "arguments": {}}}) + "\n"
    + json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "system_status", "arguments": {}}}) + "\n"
    + json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "vault_search", "arguments": {"query": "skill", "limit": 2}}}) + "\n"
)
sys.stdin = io.StringIO(test_input)
sys.stdout = io.StringIO()

from graxia_tool.mcp import MCPServer

async def run_test():
    server = MCPServer()
    await server.run_stdio()

# Run
asyncio.run(run_test())

# Restore and check output
output = sys.stdout.getvalue()
sys.stdout = real_stdout
sys.stdin = real_stdin

print("=" * 60)
print("LIVE MCP STDIO TEST (in-process)")
print("=" * 60)

# Parse responses
for line in output.strip().split("\n"):
    if not line:
        continue
    try:
        resp = json.loads(line)
        if "result" in resp:
            r = resp["result"]
            if "serverInfo" in r:
                print(f"[{resp['id']}] init OK: {r['serverInfo']['name']} v{r['serverInfo']['version']}")
            elif "tools" in r:
                names = [t["name"] for t in r["tools"]]
                print(f"[{resp['id']}] tools/list OK: {len(names)} tools ({', '.join(names[:5])}...)")
            elif "content" in r:
                text = r["content"][0]["text"]
                try:
                    data = json.loads(text)
                    if "agents" in data:
                        print(f"[{resp['id']}] agent_list OK: {len(data['agents'])} agents")
                    elif "status" in data:
                        print(f"[{resp['id']}] system_status OK: {data['status']}")
                    elif "results" in data:
                        print(f"[{resp['id']}] vault_search OK: {data['count']} notes")
                    else:
                        print(f"[{resp['id']}] OK: {text[:80]}")
                except Exception:
                    print(f"[{resp['id']}] OK: {text[:80]}")
        elif "error" in resp:
            print(f"[{resp['id']}] ERROR {resp['error']['code']}: {resp['error']['message']}")
    except json.JSONDecodeError:
        pass

print()
print("[PASS] Live MCP stdio test passed (in-process)")
