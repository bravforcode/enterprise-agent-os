"""Web UI — FastAPI dashboard for Graxia Tool.

Provides:
- REST API for agents, vault, cost, audit
- HTML dashboard
- /metrics endpoint for Prometheus
- SSE for real-time updates
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents import list_agents, get_agent
from ..audit import get_audit_logger
from ..metrics import metrics_endpoint
from ..performance import (
    ConnectionPool, AdvancedRateLimiter, CircuitBreaker, LoadBalancer, TTLCache,
)
from ..auth import get_current_user, create_token, UserStore, get_user_store
from ..audit import AuditLogger
from ..audit import AuditEvent


# --- App Setup ---

app = FastAPI(
    title="Graxia Tool API",
    description="Universal AI Agent OS — API + Dashboard",
    version="0.2.0",
)

# Static files (dashboard)
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


# --- Pydantic Models ---

class AgentRunRequest(BaseModel):
    agent: str
    query: str
    context: Optional[dict] = None


class AgentRunResponse(BaseModel):
    success: bool
    output: Any
    cost_usd: float
    tokens_used: int
    duration_ms: int
    agent: str


class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    tenant_id: str
    role: str


class VaultSearchRequest(BaseModel):
    query: str
    limit: int = 20


class VaultReadRequest(BaseModel):
    path: str


# --- Routes ---

@app.get("/")
async def root():
    """API root."""
    return {
        "name": "Graxia Tool",
        "version": "0.2.0",
        "docs": "/docs",
        "dashboard": "/dashboard",
    }


@app.get("/api/agents")
async def list_agents_endpoint():
    """List all available agents."""
    agents = list_agents()
    return {"agents": agents, "count": len(agents)}


@app.post("/api/agents/run")
async def run_agent_endpoint(req: AgentRunRequest):
    """Run an agent."""
    agent = get_agent(req.agent)
    if agent is None:
        raise HTTPException(404, f"Unknown agent: {req.agent}")

    result = await agent.run(req.query, req.context)
    return {
        "success": result.success,
        "output": result.output,
        "agent": result.agent_name or req.agent,
        "cost_usd": result.cost_usd,
        "tokens_used": result.tokens_used,
        "duration_ms": result.duration_ms,
    }


@app.get("/api/status")
async def system_status():
    """System status."""
    return {
        "status": "operational",
        "version": "0.2.0",
        "components": {
            "agents": len(list_agents()),
            "mcp_server": "ready",
            "audit": "ready",
            "metrics": "ready",
        },
    }


@app.get("/api/cost")
async def cost_report():
    """Cost report (placeholder)."""
    return {
        "total_cost_usd": 0.0,
        "total_tokens": 0,
        "by_model": {},
        "by_agent": {},
    }


@app.get("/api/skills")
async def list_skills():
    """List all skills."""
    return {"skills": []}


@app.post("/api/vault/search")
async def vault_search(req: VaultSearchRequest):
    """Search vault (placeholder)."""
    return {"results": [], "query": req.query, "total": 0}


@app.post("/api/vault/read")
async def vault_read(req: VaultReadRequest):
    """Read a vault note (placeholder)."""
    return {"path": req.path, "content": ""}


@app.get("/api/audit")
async def get_audit_logs(limit: int = 50):
    """Get recent audit logs."""
    logger = get_audit_logger()
    events = logger.query(limit=limit)
    return {
        "events": [e.to_dict() for e in events],
        "count": len(events),
        "stats": logger.get_stats(),
    }


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """Login and get JWT token."""
    store = get_user_store()
    user = store.authenticate(req.user_id, req.password)
    if user is None:
        raise HTTPException(401, "Invalid credentials")

    token = create_token(user)
    return {
        "token": token,
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "role": user.role,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    data, content_type = metrics_endpoint()
    return JSONResponse(content=data.decode("utf-8") if isinstance(data, bytes) else data)


# --- Dashboard HTML ---

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Graxia Tool Dashboard</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            margin: 0;
            padding: 20px;
        }
        h1 { color: #58a6ff; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 20px;
            margin: 10px 0;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
        }
        .stat { font-size: 2em; color: #58a6ff; font-weight: bold; }
        .stat-label { color: #8b949e; font-size: 0.9em; }
        button {
            background: #238636;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
        }
        input, select, textarea {
            background: #0d1117;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 8px;
            border-radius: 4px;
            width: 100%;
            box-sizing: border-box;
        }
        pre {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 10px;
            overflow: auto;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Graxia Tool Dashboard</h1>

        <div class="grid">
            <div class="card">
                <div class="stat" id="agent-count">-</div>
                <div class="stat-label">Available Agents</div>
            </div>
            <div class="card">
                <div class="stat" id="status">-</div>
                <div class="stat-label">System Status</div>
            </div>
            <div class="card">
                <div class="stat" id="cost">$0</div>
                <div class="stat-label">Total Cost</div>
            </div>
            <div class="card">
                <div class="stat" id="audit-count">0</div>
                <div class="stat-label">Audit Events</div>
            </div>
        </div>

        <div class="card">
            <h2>Run Agent</h2>
            <div>
                <label>Agent:</label>
                <select id="agent-select"></select>
            </div>
            <div style="margin-top: 10px;">
                <label>Query:</label>
                <textarea id="query-input" rows="3" placeholder="Enter your query..."></textarea>
            </div>
            <div style="margin-top: 10px;">
                <button onclick="runAgent()">Run</button>
            </div>
            <div style="margin-top: 15px;">
                <label>Output:</label>
                <pre id="agent-output">-</pre>
            </div>
        </div>

        <div class="card">
            <h2>Audit Log (Recent)</h2>
            <pre id="audit-log">Loading...</pre>
        </div>
    </div>

    <script>
        async function loadAgents() {
            const res = await fetch('/api/agents');
            const data = await res.json();
            document.getElementById('agent-count').textContent = data.count;
            const select = document.getElementById('agent-select');
            data.agents.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a;
                opt.textContent = a;
                select.appendChild(opt);
            });
        }

        async function loadStatus() {
            const res = await fetch('/api/status');
            const data = await res.json();
            document.getElementById('status').textContent = data.status;
        }

        async function loadAudit() {
            const res = await fetch('/api/audit');
            const data = await res.json();
            document.getElementById('audit-count').textContent = data.count;
            const log = data.events.slice(-10).map(e =>
                `[${new Date(e.timestamp * 1000).toISOString()}] ${e.event_type} - ${e.user_id || 'system'} - ${e.result}`
            ).join('\\n');
            document.getElementById('audit-log').textContent = log || 'No events';
        }

        async function runAgent() {
            const agent = document.getElementById('agent-select').value;
            const query = document.getElementById('query-input').value;
            if (!query) { alert('Enter a query'); return; }
            document.getElementById('agent-output').textContent = 'Running...';
            try {
                const res = await fetch('/api/agents/run', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({agent, query})
                });
                const data = await res.json();
                document.getElementById('agent-output').textContent =
                    JSON.stringify(data, null, 2);
            } catch (e) {
                document.getElementById('agent-output').textContent = 'Error: ' + e;
            }
        }

        loadAgents();
        loadStatus();
        loadAudit();
        setInterval(() => { loadStatus(); loadAudit(); }, 5000);
    </script>
</body>
</html>
"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Web dashboard."""
    return DASHBOARD_HTML
