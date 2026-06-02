"""Enterprise Agent OS — End-to-End Pipeline API.

Single endpoint that runs the full pipeline:
Input → Guards → Classify → Route → Plan → Execute → Validate → Log
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any

from ..core.auth import get_current_user
from ..core.models import User
from ..pipeline import EndToEndPipeline, PipelineRequest

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


class PipelineRequestModel(BaseModel):
    input: str = Field(..., description="User input to process")
    user_id: str | None = None
    session_id: str | None = None
    pattern: str | None = Field(None, description="Optional multi-agent pattern: pipeline, supervisor, parallel, hierarchical, debate, consensus, marketplace")
    context: dict[str, Any] = Field(default_factory=dict)
    skip_guards: bool = False
    skip_governance: bool = False


class PipelineResponseModel(BaseModel):
    request_id: str
    success: bool
    output: Any
    duration_ms: float
    intent: str | None = None
    domain: str | None = None
    risk_level: str | None = None
    pattern_used: str | None = None
    blocked_reason: str | None = None
    approval_required: bool = False
    error: str | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Singleton pipeline
_pipeline: EndToEndPipeline | None = None


def get_pipeline() -> EndToEndPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = EndToEndPipeline()
    return _pipeline


@router.post("/run", response_model=PipelineResponseModel)
async def run_pipeline(
    request: PipelineRequestModel,
    user: User = Depends(get_current_user),
) -> PipelineResponseModel:
    """Run the full end-to-end pipeline.

    This is the main entry point for processing user requests.
    All stages (guards → classify → governance → route → execute → validate → log)
    are run automatically.

    Examples:
        Simple query:
            {"input": "write a function to add two numbers"}

        Multi-agent pattern:
            {"input": "design a REST API", "pattern": "hierarchical"}

        Skip guards (internal use):
            {"input": "...", "skip_guards": true}
    """
    try:
        pipeline = get_pipeline()
        pipeline_request = PipelineRequest(
            input=request.input,
            user_id=request.user_id or str(user.id),
            session_id=request.session_id,
            pattern=request.pattern,
            context=request.context,
            skip_guards=request.skip_guards,
            skip_governance=request.skip_governance,
        )
        result = await pipeline.process(pipeline_request)
        return PipelineResponseModel(
            request_id=result.request_id,
            success=result.success,
            output=result.output,
            duration_ms=result.duration_ms,
            intent=result.intent,
            domain=result.domain,
            risk_level=result.risk_level,
            pattern_used=result.pattern_used,
            blocked_reason=result.blocked_reason,
            approval_required=result.approval_required,
            error=result.error,
            stages=result.stages,
            metadata=result.metadata,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")


@router.get("/stages")
async def list_stages(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """List the pipeline stages for documentation/debugging."""
    return {
        "stages": [
            {
                "id": "input_guard",
                "name": "Input Guardrail",
                "description": "Check for prompt injection, harmful content, PII",
                "block_on": "block severity",
            },
            {
                "id": "classify",
                "name": "Intent Classification",
                "description": "Classify intent, domain, and risk level",
            },
            {
                "id": "governance",
                "name": "Policy Engine",
                "description": "Apply governance policies (allow/deny/require_approval)",
            },
            {
                "id": "route",
                "name": "Agent Routing",
                "description": "Route to appropriate sub-agent or multi-agent pattern",
            },
            {
                "id": "execute",
                "name": "Agent Execution",
                "description": "Run the selected agent(s)",
            },
            {
                "id": "output_validate",
                "name": "Output Validation",
                "description": "Check output for safety, sanitize secrets",
            },
            {
                "id": "log",
                "name": "Run Logging",
                "description": "Log run for analytics and auditing",
            },
        ]
    }
