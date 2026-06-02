"""Enterprise Agent OS — Web UI.

Lightweight dashboard using HTMX + Jinja2 templates.
No JS framework required.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Main dashboard."""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Agent OS Dashboard",
        },
    )


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(request: Request) -> HTMLResponse:
    """Runs list page."""
    return templates.TemplateResponse(
        "runs.html",
        {"request": request, "title": "Runs"},
    )


@router.get("/multi-agent", response_class=HTMLResponse)
async def multi_agent_page(request: Request) -> HTMLResponse:
    """Multi-agent playground page."""
    return templates.TemplateResponse(
        "multi_agent.html",
        {"request": request, "title": "Multi-Agent"},
    )


@router.get("/metrics-view", response_class=HTMLResponse)
async def metrics_page(request: Request) -> HTMLResponse:
    """Metrics viewer page."""
    return templates.TemplateResponse(
        "metrics.html",
        {"request": request, "title": "Metrics"},
    )


# HTMX partials

@router.get("/partials/stats", response_class=HTMLResponse)
async def stats_partial(request: Request) -> HTMLResponse:
    """Stats panel partial (refreshed by HTMX)."""
    return HTMLResponse(
        """
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Active Runs</div>
                <div class="stat-value" id="active-runs">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Runs Today</div>
                <div class="stat-value" id="runs-today">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Success Rate</div>
                <div class="stat-value" id="success-rate">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Cost Today</div>
                <div class="stat-value" id="cost-today">$--</div>
            </div>
        </div>
        """,
    )
