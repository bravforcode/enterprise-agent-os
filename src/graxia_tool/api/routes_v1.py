"""Enterprise Agent OS — API Routes for Phase 1.

Endpoints:
- POST /api/v1/runs — Execute agent run
- GET /api/v1/runs — List runs
- GET /api/v1/runs/{id} — Get run details
- GET /api/v1/skills — List skills
- GET /api/v1/tools — List tools
- POST /api/v1/approve — Approve pending action
- GET /api/v1/stats — Usage statistics
"""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Any, Optional

from ..core.auth import get_current_user
from ..core.models import User, RunStatus
from ..core.orchestrator import Orchestrator
from ..core.run_logger import RunLogger
from ..core.approval_flow import ApprovalFlow
from ..core.output_validator import OutputValidator
from ..skills.registry import SkillRegistry
from ..tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1", tags=["v1"])

# Singletons
orchestrator = Orchestrator()
run_logger = RunLogger()
approval_flow = ApprovalFlow()
output_validator = OutputValidator()
skill_registry = SkillRegistry()
tool_registry = ToolRegistry()


# --- Request/Response Models ---
class RunRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    tool: str = "claude"
    max_tokens: int = 4096


class RunResponse(BaseModel):
    run_id: str
    status: str
    intent: str
    domain: str
    risk_level: str
    requires_approval: bool
    approval_id: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0


class ApprovalRequest(BaseModel):
    request_id: str
    approved: bool
    notes: str = ""


# --- Runs ---
@router.post("/runs", response_model=RunResponse)
async def execute_run(
    request: RunRequest,
    user: User = Depends(get_current_user),
):
    """Execute an agent run."""
    # Create session if needed
    session_id = uuid.UUID(request.session_id) if request.session_id else uuid.uuid4()

    # Plan
    plan = await orchestrator.plan(request.query, session_id)

    # Check approval
    if plan.requires_approval:
        approval_req = approval_flow.request_approval(
            run_id=plan.id,
            step_id=plan.steps[0].id if plan.steps else "",
            tool_name=plan.steps[0].tools_required[0] if plan.steps and plan.steps[0].tools_required else "unknown",
            description=f"Execute: {request.query[:100]}",
            params={"query": request.query},
            risk_level=plan.classified.risk_level,
        )
        return RunResponse(
            run_id=plan.id,
            status="awaiting_approval",
            intent=plan.classified.intent.value,
            domain=plan.classified.domain.value,
            risk_level=plan.classified.risk_level.value,
            requires_approval=True,
            approval_id=approval_req.id,
        )

    # Execute
    run = await orchestrator.execute(plan, session_id)

    # Validate output
    output_str = str(run.result) if run.result else ""
    validation = output_validator.validate(output_str, intent=plan.classified.intent.value)

    return RunResponse(
        run_id=str(run.id),
        status=run.status.value,
        intent=plan.classified.intent.value,
        domain=plan.classified.domain.value,
        risk_level=plan.classified.risk_level.value,
        requires_approval=False,
        result=run.result,
        error=run.error,
        tokens_used=run.tokens_input,
        cost_usd=run.cost_usd,
    )


@router.get("/runs")
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """List agent runs."""
    run_status = RunStatus(status) if status else None
    runs = await run_logger.get_runs(limit=limit, offset=offset, status=run_status)
    return {"runs": [{"id": str(r.id), "status": r.status.value, "agent": r.agent_type} for r in runs]}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
):
    """Get run details."""
    run = await run_logger.get_run(uuid.UUID(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": str(run.id),
        "status": run.status.value,
        "agent": run.agent_type,
        "intent": run.classified_intent,
        "domain": run.classified_domain,
        "risk": run.risk_level.value if run.risk_level else "low",
        "query": run.user_query,
        "result": run.result,
        "error": run.error,
        "tokens": {"input": run.tokens_input, "output": run.tokens_output},
        "cost_usd": run.cost_usd,
        "duration_ms": run.duration_ms,
    }


# --- Skills ---
@router.get("/skills")
async def list_skills(user: User = Depends(get_current_user)):
    """List registered skills."""
    skills = skill_registry.list_skills()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description[:100],
                "tier": s.tier,
                "trust": s.trust_score,
                "triggers": s.triggers[:5],
            }
            for s in skills
        ]
    }


# --- Tools ---
@router.get("/tools")
async def list_tools(
    user: User = Depends(get_current_user),
):
    """List available tools."""
    tools = tool_registry.list_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "permission_level": t.permission_level,
                "risk_level": t.risk_level.value,
                "requires_approval": t.requires_approval,
                "category": t.category,
            }
            for t in tools
        ]
    }


# --- Approval ---
@router.post("/approve")
async def approve_action(
    request: ApprovalRequest,
    user: User = Depends(get_current_user),
):
    """Approve or reject a pending action."""
    if request.approved:
        result = approval_flow.approve(request.request_id, request.notes)
    else:
        result = approval_flow.reject(request.request_id, request.notes)

    if not result:
        raise HTTPException(status_code=404, detail="Approval request not found")

    return {
        "request_id": result.id,
        "status": result.status.value,
        "tool": result.tool_name,
    }


@router.get("/approvals")
async def list_approvals(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """List pending approval requests."""
    from ..core.approval_flow import ApprovalStatus
    pending = approval_flow.get_pending()
    return {
        "pending": [
            {
                "id": r.id,
                "tool": r.tool_name,
                "description": r.description,
                "risk": r.risk_level.value,
                "requested_at": r.requested_at.isoformat(),
            }
            for r in pending
        ]
    }


# --- Stats ---
@router.get("/stats")
async def get_stats(user: User = Depends(get_current_user)):
    """Get usage statistics."""
    stats = await run_logger.get_stats()
    tool_usage = tool_registry.get_usage_stats()
    return {
        "runs": stats,
        "tool_usage": tool_usage,
    }
