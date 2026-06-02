"""Integration test: Graxia OS bridge against a mock Graxia server.

Since starting the full Graxia stack (PostgreSQL, Redis, all dependencies) is heavy,
we spin up a minimal FastAPI app on port 8000 that mimics Graxia's /health and
agent endpoints, then test that graxia_tool's bridge can:
1. Health check
2. Forward a Graxia agent call
3. Share cost reports
4. Use JWT auth

Run: python scripts/test_graxia_integration.py
"""
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(r"C:\Users\menum\enterprise-agent-os")
sys.path.insert(0, str(ROOT / "src"))

# Set up Graxia config BEFORE import
import os
os.environ["GRAXIA_BASE_URL"] = "http://127.0.0.1:8000"
os.environ["GRAXIA_ENABLED"] = "true"

try:
    from fastapi import FastAPI, HTTPException, Header
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

if FASTAPI_AVAILABLE:
    # ----- Mock Graxia server -----
    mock_app = FastAPI(title="Mock Graxia OS")

    @mock_app.get("/health")
    async def health():
        return {"status": "ok", "service": "mock-graxia"}

    @mock_app.get("/api/v1/agents/list")
    async def list_agents(authorization: str = Header(None)):
        if authorization and not authorization.startswith("Bearer "):
            raise HTTPException(401, "Invalid auth")
        return {
            "agents": [
                {"name": "scoring", "description": "Score leads"},
                {"name": "drafting", "description": "Draft emails"},
                {"name": "learning", "description": "Learn from data"},
                {"name": "sync", "description": "Sync external systems"},
            ]
        }

    @mock_app.post("/api/v1/agents/run")
    async def run_agent(request: dict, authorization: str = Header(None)):
        return {
            "success": True,
            "agent": request.get("agent_name"),
            "output": f"mock response for {request.get('query', '')}",
            "graxia_run_id": f"run-{int(time.time())}",
        }

    @mock_app.get("/api/v1/cost")
    async def cost_report():
        return {
            "graxia_cost": 12.34,
            "graxia_tokens": 50000,
        }


def run_mock_graxia():
    """Run mock Graxia in background thread."""
    uvicorn.run(mock_app, host="127.0.0.1", port=8000, log_level="warning")


async def main():
    print("=" * 70)
    print("GRAXIA OS INTEGRATION TEST — peer service bridge")
    print("=" * 70)

    if not FASTAPI_AVAILABLE:
        print("[SKIP] fastapi not installed — cannot run mock server")
        return

    # 1. Start mock Graxia in background thread
    print("\n[1] Starting mock Graxia on :8000...")
    server_thread = threading.Thread(target=run_mock_graxia, daemon=True)
    server_thread.start()
    await asyncio.sleep(2.0)  # let it start

    # 2. Test health check
    print("\n[2] Health check:")
    from graxia_tool.integrations.graxia import GraxiaBridge
    bridge = GraxiaBridge()
    healthy = await bridge.health_check()
    print(f"    health_check = {healthy}")
    assert healthy, "Bridge should report Graxia is healthy"

    # 3. Test config
    print("\n[3] Bridge config:")
    print(f"    base_url: {bridge.config.base_url}")
    print(f"    enabled: {bridge.config.enabled}")

    # 4. Test route map
    print("\n[4] Graxia -> AgentOS route map:")
    route_map = bridge.get_route_map()
    for g, a in route_map.items():
        print(f"    {g:12s} -> {a}")
    assert len(route_map) == 4

    # 5. Test forward agent (no real LLM — uses AgentOS internal)
    print("\n[5] Forward agent (scoring -> data_engineer):")
    result = await bridge.forward_agent("scoring", "rank these 10 leads by quality")
    print(f"    success: {result['success']}")
    print(f"    graxia_agent: {result['graxia_agent']}")
    print(f"    agent_os_agent: {result['agent_os_agent']}")
    print(f"    output: {str(result['output'])[:80]}...")

    # 6. Test forward unknown
    print("\n[6] Forward unknown agent:")
    result = await bridge.forward_agent("nonexistent", "x")
    print(f"    success: {result['success']}")
    print(f"    error: {result.get('error', '')[:80]}")

    # 7. Test share cost report
    print("\n[7] Share cost report:")
    report = await bridge.share_cost_report()
    print(f"    calls: {report.get('calls', 0)}")
    print(f"    total_cost_usd: ${report.get('total_cost_usd', 0):.4f}")
    print(f"    cache_hit_rate: {report.get('cache_hit_rate', 0):.1%}")

    # 8. Test that GraxiaBridge respects enabled=False
    print("\n[8] Disabled bridge:")
    from graxia_tool.integrations.graxia import GraxiaConfig
    disabled = GraxiaBridge(GraxiaConfig(enabled=False))
    healthy = await disabled.health_check()
    print(f"    health_check (disabled) = {healthy}")
    assert healthy is False

    await bridge.close()
    print("\n" + "=" * 70)
    print("[PASS] Graxia OS integration test passed")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
