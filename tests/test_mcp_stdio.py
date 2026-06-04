"""Test the MCP stdio transport end-to-end (regression for -32001 timeout).

Reproduces the IDE MCP startup handshake: spawns the server, sends
initialize + tools/list + ping + tools/call, asserts responses.

This is the test that catches the Windows ProactorEventLoop + sys.stdin
crash that caused the -32001 timeout in Claude/Codex/Cursor/etc.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _send_requests(requests: list, timeout: float = 15.0) -> list:
    """Spawn the MCP server, send JSON-RPC requests, return parsed responses."""
    input_data = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.Popen(
        [PYTHON, "-m", "graxia_tool.mcp"],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        stdout, stderr = proc.communicate(input=input_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(
            f"MCP server timed out after {timeout}s. "
            f"This is the -32001 timeout bug. stderr: {stderr[:500]}"
        )
    if proc.returncode != 0:
        pytest.fail(
            f"MCP server crashed with exit code {proc.returncode}. "
            f"stderr: {stderr[:1000]}"
        )
    responses = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return responses


def test_mcp_initialize():
    """initialize handshake must return within 10s (regression for -32001)."""
    start = time.time()
    responses = _send_requests([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}}},
    ], timeout=10.0)
    elapsed = time.time() - start
    assert elapsed < 10.0, f"initialize took {elapsed:.1f}s (>10s timeout)"
    assert len(responses) == 1
    r = responses[0]
    assert r["id"] == 1
    assert "result" in r, f"Got error: {r.get('error')}"
    assert r["result"]["protocolVersion"] == "2024-11-05"
    assert r["result"]["serverInfo"]["name"] == "graxia_tool"


def test_mcp_tools_list():
    """tools/list must return all registered tools."""
    responses = _send_requests([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ], timeout=10.0)
    assert len(responses) == 2
    tools = responses[1]["result"]["tools"]
    assert len(tools) >= 26, f"Expected >=26 tools, got {len(tools)}"
    tool_names = {t["name"] for t in tools}
    assert "agent_run" in tool_names
    assert "pipeline_run" in tool_names
    assert "system_status" in tool_names
    assert "auto_route" in tool_names
    assert "graxia_skills" in tool_names
    assert "graxia_vault" in tool_names
    assert "graxia_swarm" in tool_names


def test_mcp_ping():
    """ping must return empty result."""
    responses = _send_requests([
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
    ], timeout=10.0)
    assert len(responses) == 1
    assert responses[0]["id"] == 1
    assert responses[0]["result"] == {}


def test_mcp_tool_call_system_status():
    """tools/call system_status must return operational status."""
    responses = _send_requests([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "system_status", "arguments": {}}},
    ], timeout=15.0)
    assert len(responses) == 2, f"Expected 2 responses (init + call), got {len(responses)}"
    call_resp = responses[1]
    assert call_resp["id"] == 2
    assert "result" in call_resp, f"Tool error: {call_resp.get('error')}"
    content = call_resp["result"]["content"][0]["text"]
    assert "operational" in content


def test_mcp_unknown_method():
    """Unknown method must return -32601 error, not crash."""
    responses = _send_requests([
        {"jsonrpc": "2.0", "id": 1, "method": "unknown/method", "params": {}},
    ], timeout=10.0)
    assert len(responses) == 1
    assert "error" in responses[0]
    assert responses[0]["error"]["code"] == -32601


def test_mcp_startup_time_under_timeout():
    """MCP server must respond to initialize within 5s (regression for IDE timeouts)."""
    proc = subprocess.Popen(
        [PYTHON, "-m", "graxia_tool.mcp"],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    start = time.time()
    try:
        stdout, stderr = proc.communicate(
            input=json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1.0"}}
            }) + "\n",
            timeout=5.0,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(
            "MCP server did not respond to initialize within 5s. "
            "This is the -32001 timeout bug — Windows ProactorEventLoop + sys.stdin crash."
        )
    elapsed = time.time() - start
    assert elapsed < 5.0, f"MCP startup took {elapsed:.1f}s — IDEs will time out"
    assert proc.returncode == 0, f"MCP crashed: {stderr[:500]}"


def test_mcp_multiple_concurrent_calls():
    """Server must handle multiple sequential calls correctly."""
    responses = _send_requests([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    ], timeout=10.0)
    assert len(responses) == 4
    assert [r["id"] for r in responses] == [1, 2, 3, 4]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
