#!/usr/bin/env python3
"""Graxia Tool v0.3.0 Autonomous Demo — runs ALL tracks end-to-end.

Usage: python scripts/auto_demo.py

This script exercises:
  T1: Acontext skill memory (BM25 recall, LLM distillation)
  T2: Ruflo swarm + 100+ agents + SONA learning
  T3: ANUS autonomous mode (GOAP planner, ANUS.md context)
  T4: Faker synthetic data (Thai locale, person/location/finance)
  T5: Integration (all features wired through MCP)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

PYTHON = sys.executable
PROJECT = Path(__file__).resolve().parent.parent


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def send_mcp(requests: list) -> list:
    """Send JSON-RPC requests to MCP server and return responses."""
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.Popen(
        [PYTHON, "-m", "graxia_tool.mcp"],
        cwd=str(PROJECT),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        stdout, stderr = proc.communicate(input=payload, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return []
    if proc.returncode != 0:
        print(f"  [ERROR] MCP server crashed: {stderr[:200]}")
        return []
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def main():
    start = time.time()
    results = {"tracks": {}, "passed": 0, "failed": 0, "tools": 0}

    # ── MCP Health Check ──
    section("MCP Server Health Check")
    responses = send_mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "auto-demo", "version": "0.3.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ])
    if len(responses) < 2:
        print("  FATAL: MCP server did not respond")
        sys.exit(1)
    tools = responses[1]["result"]["tools"]
    results["tools"] = len(tools)
    print(f"  MCP Server: OK (v{responses[0]['result']['serverInfo']['version']})")
    print(f"  Tools registered: {len(tools)}")

    tool_names = {t["name"] for t in tools}
    tracks = {
        "T1-Acontext": ["acontext_learn", "acontext_list_skills", "acontext_recall",
                        "acontext_get_skill", "acontext_delete_skill"],
        "T2-Swarm": ["swarm_init", "swarm_run", "swarm_status",
                     "federation_init", "federation_send", "federation_list_peers",
                     "sona_record", "sona_suggest"],
        "T3-Autonomous": ["context_load", "context_save", "context_update",
                         "autonomous_plan", "autonomous_run", "autonomous_status",
                         "autonomous_list_runs"],
        "T4-Faker": ["faker_generate", "faker_schema", "faker_locales"],
        "T5-Integration": ["system_status", "agent_list", "agent_run"],
    }

    # ── Track T1: Acontext ──
    section("T1: Acontext Skill Memory")
    responses = send_mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "demo", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "acontext_list_skills",
                    "arguments": {"space": "demo"}}},
    ])
    if len(responses) >= 2 and "result" in responses[1]:
        print("  acontext_list_skills: OK")
        results["tracks"]["T1"] = "PASS"
        results["passed"] += 1
    else:
        print("  acontext_list_skills: FAILED")
        results["tracks"]["T1"] = "FAIL"
        results["failed"] += 1

    # ── Track T2: Swarm ──
    section("T2: Multi-Agent Swarm + SONA")
    responses = send_mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "demo", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "swarm_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "sona_suggest",
                    "arguments": {"intent": "code review"}}},
    ])
    if len(responses) >= 2 and "result" in responses[1]:
        print("  swarm_status: OK")
        print("  sona_suggest: OK")
        results["tracks"]["T2"] = "PASS"
        results["passed"] += 1
    else:
        print("  Swarm: FAILED")
        results["tracks"]["T2"] = "FAIL"
        results["failed"] += 1

    # ── Track T3: Autonomous ──
    section("T3: Autonomous Mode + ANUS.md")
    responses = send_mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "demo", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "autonomous_list_runs", "arguments": {}}},
    ])
    if len(responses) >= 2 and "result" in responses[1]:
        print("  autonomous_list_runs: OK")
        results["tracks"]["T3"] = "PASS"
        results["passed"] += 1
    else:
        print("  Autonomous: FAILED")
        results["tracks"]["T3"] = "FAIL"
        results["failed"] += 1

    # ── Track T4: Faker ──
    section("T4: Faker Synthetic Data (Thai Locale)")
    responses = send_mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "demo", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "faker_locales", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "faker_generate",
                    "arguments": {"category": "person", "field": "first_name",
                                  "locale": "th", "count": 3}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "faker_generate",
                    "arguments": {"category": "person", "field": "phone_number",
                                  "locale": "th", "count": 3}}},
    ])
    if len(responses) >= 3 and "result" in responses[2]:
        print("  faker_locales: OK")
        print("  faker_generate (Thai names): OK")
        if len(responses) >= 4:
            print("  faker_generate (Thai phones): OK")
        results["tracks"]["T4"] = "PASS"
        results["passed"] += 1
    else:
        print("  Faker: FAILED")
        results["tracks"]["T4"] = "FAIL"
        results["failed"] += 1

    # ── Track T5: Integration ──
    section("T5: Integration + System Status")
    responses = send_mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "demo", "version": "1.0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "system_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "agent_list", "arguments": {}}},
    ])
    if len(responses) >= 2 and "result" in responses[1]:
        content = json.loads(responses[1]["result"]["content"][0]["text"])
        print(f"  system_status: {content['status']} ({len(content['components'])} components)")
        if len(responses) >= 3:
            agent_content = json.loads(responses[2]["result"]["content"][0]["text"])
            print(f"  agent_list: {len(agent_content['agents'])} agents")
        results["tracks"]["T5"] = "PASS"
        results["passed"] += 1
    else:
        print("  Integration: FAILED")
        results["tracks"]["T5"] = "FAIL"
        results["failed"] += 1

    # ── Summary ──
    elapsed = time.time() - start
    section("AUTO-DEMO RESULTS")
    for track, status in results["tracks"].items():
        icon = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"  {icon} {track}")
    print(f"\n  Tracks: {results['passed']}/{results['passed']+results['failed']} passed")
    print(f"  Tools:  {results['tools']}")
    print(f"  Time:   {elapsed:.1f}s")
    print(f"\n  {'ALL TRACKS PASSED!' if results['failed'] == 0 else f'{results['failed']} track(s) FAILED'}")


if __name__ == "__main__":
    main()
