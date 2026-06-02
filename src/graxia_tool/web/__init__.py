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
from ..monitoring import get_activity_feed, get_metrics_summary, get_agent_statuses
from ..monitoring.agent_tracker import get_tracker
from ..monitoring.metrics_collector import get_monitoring_metrics


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
        "monitoring": "/monitoring",
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


# --- Monitoring API ---

@app.get("/api/monitoring/activity")
async def monitoring_activity(limit: int = 100, agent: Optional[str] = None):
    """Agent activity feed for real-time monitoring."""
    return get_activity_feed(limit=limit, agent=agent)


@app.get("/api/monitoring/metrics")
async def monitoring_metrics():
    """Aggregated metrics for dashboard charts."""
    return get_metrics_summary()


@app.get("/api/monitoring/agents")
async def monitoring_agents():
    """Agent status list with per-agent aggregates."""
    return get_agent_statuses()


@app.get("/api/monitoring/seed")
async def monitoring_seed():
    """Seed demo data so the dashboard has something to show."""
    import random
    tracker = get_tracker()
    collector = get_monitoring_metrics()
    agent_names = ["coder", "reviewer", "tester", "planner", "researcher", "deployer"]
    for i in range(25):
        name = agent_names[i % len(agent_names)]
        run_id = tracker.start(name, query=f"demo task {i}").run_id
        tokens = random.randint(200, 4000)
        cost = round(random.uniform(0.0001, 0.008), 6)
        duration = random.randint(100, 5000)
        success = random.random() > 0.15
        tracker.end(
            name,
            run_id=run_id,
            success=success,
            tokens_used=tokens,
            cost_usd=cost,
            duration_ms=duration,
            output_summary=f"Demo output {i}",
        )
        collector.record_run(name, tokens, cost, duration, success)
    return {"seeded": 25, "agents": agent_names}


# --- Monitoring Dashboard HTML ---

MONITORING_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Graxia Tool — AI Monitoring Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-primary: #0f1219;
            --bg-secondary: #161b26;
            --bg-card: #1a2035;
            --bg-card-hover: #1e2640;
            --border: #2a3352;
            --border-accent: #3d4f7c;
            --text-primary: #e0e6f0;
            --text-secondary: #8892a8;
            --text-muted: #5a6478;
            --accent-blue: #4dabf7;
            --accent-cyan: #22d3ee;
            --accent-green: #34d399;
            --accent-yellow: #fbbf24;
            --accent-red: #f87171;
            --accent-purple: #a78bfa;
            --glow-blue: rgba(77, 171, 247, 0.15);
            --glow-green: rgba(52, 211, 153, 0.15);
        }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.5;
            min-height: 100vh;
        }
        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 18px;
            font-weight: 600;
            color: var(--accent-blue);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .header .live-dot {
            width: 8px; height: 8px;
            background: var(--accent-green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .header-controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .header-controls button {
            background: var(--bg-card);
            color: var(--text-primary);
            border: 1px solid var(--border);
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.15s;
        }
        .header-controls button:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-accent);
        }
        .header-controls .seed-btn {
            background: rgba(34, 211, 238, 0.1);
            border-color: rgba(34, 211, 238, 0.3);
            color: var(--accent-cyan);
        }
        .header-controls .seed-btn:hover {
            background: rgba(34, 211, 238, 0.2);
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px 24px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 18px;
            transition: border-color 0.2s;
        }
        .stat-card:hover { border-color: var(--border-accent); }
        .stat-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-secondary);
            margin-bottom: 6px;
        }
        .stat-value {
            font-size: 26px;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .stat-value.blue { color: var(--accent-blue); }
        .stat-value.green { color: var(--accent-green); }
        .stat-value.yellow { color: var(--accent-yellow); }
        .stat-value.cyan { color: var(--accent-cyan); }
        .stat-value.red { color: var(--accent-red); }
        .stat-value.purple { color: var(--accent-purple); }
        .charts-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-bottom: 20px;
        }
        .chart-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 18px;
        }
        .chart-card h3 {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-secondary);
            margin-bottom: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .chart-card canvas {
            width: 100% !important;
            height: 220px !important;
        }
        .bottom-grid {
            display: grid;
            grid-template-columns: 1fr 380px;
            gap: 14px;
        }
        .agents-table {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow: hidden;
        }
        .agents-table h3 {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-secondary);
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .agents-table table {
            width: 100%;
            border-collapse: collapse;
        }
        .agents-table th {
            text-align: left;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-muted);
            padding: 10px 18px;
            border-bottom: 1px solid var(--border);
            font-weight: 500;
        }
        .agents-table td {
            padding: 10px 18px;
            font-size: 13px;
            border-bottom: 1px solid rgba(42, 51, 82, 0.5);
            font-variant-numeric: tabular-nums;
        }
        .agents-table tr:hover td {
            background: var(--bg-card-hover);
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        }
        .status-badge .dot {
            width: 6px; height: 6px;
            border-radius: 50%;
        }
        .status-active { background: rgba(52, 211, 153, 0.12); color: var(--accent-green); }
        .status-active .dot { background: var(--accent-green); }
        .status-completed { background: rgba(77, 171, 247, 0.12); color: var(--accent-blue); }
        .status-completed .dot { background: var(--accent-blue); }
        .status-failed { background: rgba(248, 113, 113, 0.12); color: var(--accent-red); }
        .status-failed .dot { background: var(--accent-red); }
        .status-idle { background: rgba(90, 100, 120, 0.15); color: var(--text-muted); }
        .status-idle .dot { background: var(--text-muted); }
        .activity-feed {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            max-height: 420px;
            display: flex;
            flex-direction: column;
        }
        .activity-feed h3 {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-secondary);
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            flex-shrink: 0;
        }
        .feed-list {
            overflow-y: auto;
            flex: 1;
            padding: 4px 0;
        }
        .feed-item {
            display: flex;
            gap: 10px;
            padding: 8px 18px;
            border-bottom: 1px solid rgba(42, 51, 82, 0.3);
            font-size: 12px;
            transition: background 0.1s;
        }
        .feed-item:hover { background: var(--bg-card-hover); }
        .feed-time {
            color: var(--text-muted);
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
            font-size: 11px;
        }
        .feed-agent {
            color: var(--accent-cyan);
            font-weight: 500;
            white-space: nowrap;
        }
        .feed-type {
            padding: 1px 7px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .feed-type.start { background: rgba(52, 211, 153, 0.15); color: var(--accent-green); }
        .feed-type.end { background: rgba(77, 171, 247, 0.15); color: var(--accent-blue); }
        .feed-type.error, .feed-type.failed { background: rgba(248, 113, 113, 0.15); color: var(--accent-red); }
        .feed-type.tool_start { background: rgba(167, 139, 250, 0.15); color: var(--accent-purple); }
        .feed-type.tool_done { background: rgba(251, 191, 36, 0.15); color: var(--accent-yellow); }
        .feed-detail {
            color: var(--text-secondary);
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .feed-cost {
            color: var(--text-muted);
            white-space: nowrap;
            font-size: 11px;
        }
        .empty-state {
            padding: 40px 20px;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
        }
        @media (max-width: 1024px) {
            .charts-grid { grid-template-columns: 1fr; }
            .bottom-grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 640px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .header { flex-direction: column; gap: 10px; align-items: flex-start; }
            .container { padding: 14px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span class="live-dot"></span> Graxia AI Monitoring</h1>
        <div class="header-controls">
            <span id="last-update" style="font-size:12px;color:var(--text-muted);"></span>
            <button class="seed-btn" onclick="seedDemo()">Seed Demo Data</button>
            <button onclick="refreshAll()">Refresh</button>
        </div>
    </div>

    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Active Agents</div>
                <div class="stat-value green" id="stat-active">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Runs</div>
                <div class="stat-value blue" id="stat-runs">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Success Rate</div>
                <div class="stat-value cyan" id="stat-success-rate">100%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Cost</div>
                <div class="stat-value yellow" id="stat-cost">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Tokens</div>
                <div class="stat-value purple" id="stat-tokens">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Failures</div>
                <div class="stat-value red" id="stat-failures">0</div>
            </div>
        </div>

        <div class="charts-grid">
            <div class="chart-card">
                <h3>Tokens Over Time</h3>
                <canvas id="chart-tokens"></canvas>
            </div>
            <div class="chart-card">
                <h3>Cost Over Time</h3>
                <canvas id="chart-cost"></canvas>
            </div>
            <div class="chart-card">
                <h3>Latency (ms)</h3>
                <canvas id="chart-latency"></canvas>
            </div>
            <div class="chart-card">
                <h3>Cost by Agent</h3>
                <canvas id="chart-cost-pie"></canvas>
            </div>
        </div>

        <div class="bottom-grid">
            <div class="agents-table">
                <h3>Agent Status</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Agent</th>
                            <th>Status</th>
                            <th>Runs</th>
                            <th>Success</th>
                            <th>Tokens</th>
                            <th>Cost</th>
                            <th>Avg Latency</th>
                        </tr>
                    </thead>
                    <tbody id="agents-body">
                        <tr><td colspan="7" class="empty-state">No agents tracked yet</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="activity-feed">
                <h3>Activity Feed</h3>
                <div class="feed-list" id="feed-list">
                    <div class="empty-state">No activity yet</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const COLORS = {
            blue: 'rgba(77, 171, 247, 1)',
            blueFill: 'rgba(77, 171, 247, 0.15)',
            cyan: 'rgba(34, 211, 238, 1)',
            cyanFill: 'rgba(34, 211, 238, 0.15)',
            green: 'rgba(52, 211, 153, 1)',
            greenFill: 'rgba(52, 211, 153, 0.15)',
            yellow: 'rgba(251, 191, 36, 1)',
            yellowFill: 'rgba(251, 191, 36, 0.15)',
            red: 'rgba(248, 113, 113, 1)',
            redFill: 'rgba(248, 113, 113, 0.15)',
            purple: 'rgba(167, 139, 250, 1)',
            purpleFill: 'rgba(167, 139, 250, 0.15)',
            grid: 'rgba(42, 51, 82, 0.5)',
            text: '#5a6478',
        };
        const PALETTE = [COLORS.blue, COLORS.cyan, COLORS.green, COLORS.yellow, COLORS.purple, COLORS.red];

        const chartOpts = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, maxTicksLimit: 8, font: { size: 10 } } },
                y: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, font: { size: 10 } }, beginAtZero: true },
            },
        };

        function timeSeries(data, key) {
            return data.map(d => ({
                x: new Date(d.timestamp * 1000),
                y: d[key] || d.value || 0,
            }));
        }

        let chartTokens, chartCost, chartLatency, chartPie;

        function initCharts() {
            const tsOpts = (clr, fill) => ({
                ...chartOpts,
                elements: { point: { radius: 2 }, line: { borderWidth: 2 } },
                scales: {
                    ...chartOpts.scales,
                    x: { ...chartOpts.scales.x, type: 'timeseries', time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } } },
                },
            });

            chartTokens = new Chart(document.getElementById('chart-tokens'), {
                type: 'line',
                data: { datasets: [{ data: [], borderColor: COLORS.purple, backgroundColor: COLORS.purpleFill, fill: true, tension: 0.3 }] },
                options: tsOpts(COLORS.purple, COLORS.purpleFill),
            });
            chartCost = new Chart(document.getElementById('chart-cost'), {
                type: 'line',
                data: { datasets: [{ data: [], borderColor: COLORS.yellow, backgroundColor: COLORS.yellowFill, fill: true, tension: 0.3 }] },
                options: tsOpts(COLORS.yellow, COLORS.yellowFill),
            });
            chartLatency = new Chart(document.getElementById('chart-latency'), {
                type: 'line',
                data: { datasets: [{ data: [], borderColor: COLORS.cyan, backgroundColor: COLORS.cyanFill, fill: true, tension: 0.3 }] },
                options: tsOpts(COLORS.cyan, COLORS.cyanFill),
            });
            chartPie = new Chart(document.getElementById('chart-cost-pie'), {
                type: 'doughnut',
                data: { labels: [], datasets: [{ data: [], backgroundColor: PALETTE, borderWidth: 0 }] },
                options: {
                    responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
                    plugins: {
                        legend: { position: 'right', labels: { color: '#8892a8', font: { size: 11 }, padding: 12, usePointStyle: true, pointStyleWidth: 8 } },
                    },
                    cutout: '65%',
                },
            });
        }

        async function fetchJSON(url) {
            const r = await fetch(url);
            return r.json();
        }

        function formatNum(n) {
            if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
            if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
            return n.toString();
        }

        function statusClass(s) {
            const map = { active: 'status-active', completed: 'status-completed', failed: 'status-failed', idle: 'status-idle' };
            return map[s] || 'status-idle';
        }

        function timeAgo(ts) {
            const s = Math.floor(Date.now() / 1000 - ts);
            if (s < 5) return 'now';
            if (s < 60) return s + 's ago';
            if (s < 3600) return Math.floor(s / 60) + 'm ago';
            return Math.floor(s / 3600) + 'h ago';
        }

        async function updateDashboard() {
            const [metricsRes, agentsRes, feedRes] = await Promise.all([
                fetchJSON('/api/monitoring/metrics'),
                fetchJSON('/api/monitoring/agents'),
                fetchJSON('/api/monitoring/activity?limit=50'),
            ]);

            const s = metricsRes.summary;
            document.getElementById('stat-active').textContent = s.active_agents;
            document.getElementById('stat-runs').textContent = formatNum(s.total_runs);
            document.getElementById('stat-success-rate').textContent = (s.success_rate * 100).toFixed(1) + '%';
            document.getElementById('stat-cost').textContent = '$' + s.total_cost_usd.toFixed(4);
            document.getElementById('stat-tokens').textContent = formatNum(s.total_tokens);
            document.getElementById('stat-failures').textContent = s.total_failures;
            document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();

            if (metricsRes.tokens_over_time && chartTokens) {
                chartTokens.data.datasets[0].data = timeSeries(metricsRes.tokens_over_time);
                chartTokens.update('none');
            }
            if (metricsRes.cost_over_time && chartCost) {
                chartCost.data.datasets[0].data = timeSeries(metricsRes.cost_over_time);
                chartCost.update('none');
            }
            if (metricsRes.latency_over_time && chartLatency) {
                chartLatency.data.datasets[0].data = timeSeries(metricsRes.latency_over_time);
                chartLatency.update('none');
            }
            if (metricsRes.cost_by_agent && chartPie) {
                const labels = Object.keys(metricsRes.cost_by_agent);
                const values = Object.values(metricsRes.cost_by_agent);
                chartPie.data.labels = labels;
                chartPie.data.datasets[0].data = values;
                chartPie.update('none');
            }

            const tbody = document.getElementById('agents-body');
            if (agentsRes.agents && agentsRes.agents.length > 0) {
                tbody.innerHTML = agentsRes.agents.map(a => `
                    <tr>
                        <td style="font-weight:500;color:var(--accent-cyan);">${a.agent_name}</td>
                        <td><span class="status-badge ${statusClass(a.status)}"><span class="dot"></span>${a.status}</span></td>
                        <td>${a.total_runs}</td>
                        <td>${(a.success_rate * 100).toFixed(0)}%</td>
                        <td>${formatNum(a.total_tokens)}</td>
                        <td>$${a.total_cost_usd.toFixed(4)}</td>
                        <td>${a.avg_duration_ms.toFixed(0)}ms</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No agents tracked yet — click "Seed Demo Data"</td></tr>';
            }

            const feed = document.getElementById('feed-list');
            if (feedRes.events && feedRes.events.length > 0) {
                feed.innerHTML = feedRes.events.slice().reverse().map(e => `
                    <div class="feed-item">
                        <span class="feed-time">${timeAgo(e.timestamp)}</span>
                        <span class="feed-agent">${e.agent_name}</span>
                        <span class="feed-type ${e.event_type}">${e.event_type}</span>
                        <span class="feed-detail">${e.query || e.metadata?.tool_name || '-'}</span>
                        ${e.cost_usd > 0 ? '<span class="feed-cost">$' + e.cost_usd.toFixed(4) + '</span>' : ''}
                    </div>
                `).join('');
            } else {
                feed.innerHTML = '<div class="empty-state">No activity yet — click "Seed Demo Data"</div>';
            }
        }

        async function refreshAll() {
            await updateDashboard();
        }

        async function seedDemo() {
            const btn = document.querySelector('.seed-btn');
            btn.textContent = 'Seeding...';
            btn.disabled = true;
            await fetch('/api/monitoring/seed');
            btn.textContent = 'Seed Demo Data';
            btn.disabled = false;
            await updateDashboard();
        }

        initCharts();
        updateDashboard();
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
"""

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


@app.get("/monitoring", response_class=HTMLResponse)
async def monitoring_dashboard():
    """AI Monitoring Dashboard — real-time agent observability."""
    return MONITORING_DASHBOARD_HTML


# --- Server Entry Point ---


def run_server(host: str = "127.0.0.1", port: int = 8000, log_level: str = "info") -> None:
    """Run the FastAPI server with uvicorn.

    Usage:
        from graxia_tool.web import run_server
        run_server()  # http://127.0.0.1:8000
    """
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError(
            "uvicorn is required for the web server. "
            "Install with: pip install graxia-tool[web]"
        ) from e
    print(f"Starting Graxia Tool web UI at http://{host}:{port}")
    print("Press Ctrl+C to stop")
    uvicorn.run(app, host=host, port=port, log_level=log_level)
