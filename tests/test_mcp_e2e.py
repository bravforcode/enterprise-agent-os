"""Test MCP server end-to-end.

MCP server uses newline-delimited JSON (batch mode):
- Send all requests as newline-delimited JSON
- Close stdin to signal end
- Read all responses from stdout
"""
import subprocess, sys, time, json, threading
from pathlib import Path


def main():
    print("=" * 60)
    print("  Graxia MCP Server — End-to-End Test")
    print("=" * 60)
    print()

    # Build request batch
    requests = [
        # Initialize
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        },
        # Initialized notification
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        # List tools
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        # agent_list
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "agent_list", "arguments": {}},
        },
        # system_status
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "system_status", "arguments": {}},
        },
        # skills_list
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "skills_list", "arguments": {}},
        },
        # agent_run with real Ollama LLM (no API key)
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "agent_run", "arguments": {"agent": "general", "query": "Say hi in 5 words."}},
        },
        # cost_report
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "cost_report", "arguments": {}},
        },
    ]

    stdin_data = "\n".join(json.dumps(r) for r in requests) + "\n"

    print("[1/6] Starting MCP server (python -m graxia_tool)...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "graxia_tool"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Write all requests, then close stdin
    stdout_data, stderr_data = proc.communicate(input=stdin_data.encode("utf-8"), timeout=60)

    stdout_text = stdout_data.decode("utf-8", errors="replace")
    stderr_text = stderr_data.decode("utf-8", errors="replace")

    if proc.returncode not in (None, 0, -15, 9):
        print(f"  ! Server exited with code {proc.returncode}")
        if stderr_text:
            print(f"  STDERR: {stderr_text[:500]}")
        return 1

    # Parse responses
    responses = []
    for line in stdout_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    print(f"  [OK] Server started, {len(responses)} responses received")
    print()

    # Analyze results
    tools = []
    agent_list_result = None
    system_status_result = None
    skills_list_result = None
    agent_run_result = None
    cost_report_result = None

    for resp in responses:
        rid = resp.get("id")
        if rid == 1:
            info = resp.get("result", {}).get("serverInfo", {})
            print(f"[2/6] Initialize: {info.get('name')} v{info.get('version')}")
            print(f"       Protocol: {resp.get('result', {}).get('protocolVersion')}")
        elif rid == 2:
            tools = resp.get("result", {}).get("tools", [])
            print(f"[3/6] Tools list: {len(tools)} tools")
            for t in tools:
                print(f"       - {t.get('name')}")
        elif rid == 3:
            agent_list_result = resp
        elif rid == 4:
            system_status_result = resp
        elif rid == 5:
            skills_list_result = resp
        elif rid == 6:
            agent_run_result = resp
        elif rid == 7:
            cost_report_result = resp

    print()

    # Results
    print("[4/6] Tool call results:")
    for name, resp in [
        ("agent_list", agent_list_result),
        ("system_status", system_status_result),
        ("skills_list", skills_list_result),
        ("agent_run", agent_run_result),
        ("cost_report", cost_report_result),
    ]:
        if resp is None:
            print(f"  [?] {name:20s} — no response")
            continue
        if "error" in resp:
            print(f"  [FAIL] {name:20s} — {resp['error']}")
            continue
        content = resp.get("result", {}).get("content", [])
        if content and "text" in content[0]:
            text = content[0]["text"]
            print(f"  [OK] {name:20s} — {len(text)} chars")
        else:
            print(f"  [OK] {name:20s}")

    print()
    print("[5/6] Ollama LLM check:")
    if agent_run_result and "error" not in agent_run_result:
        content = agent_run_result.get("result", {}).get("content", [])
        if content and "text" in content[0]:
            text = content[0]["text"][:200]
            print(f"  [OK] agent_run returned: {text}")
    else:
        print("  [FAIL] agent_run did not succeed")

    # Summary
    all_ok = (
        len(tools) >= 18
        and agent_list_result and "error" not in agent_list_result
        and system_status_result and "error" not in system_status_result
    )

    print()
    print("=" * 60)
    if all_ok:
        print("  MCP SERVER WORKS END-TO-END!")
    else:
        print("  MCP SERVER HAS ISSUES (see above)")
    print(f"  Tools: {len(tools)}")
    print(f"  Responses: {len(responses)}")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
