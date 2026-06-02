"""Enterprise Agent OS — Orchestrator Agent.

Plans → executes → validates agent runs.
Routes to sub-agents based on intent classification.
"""
from __future__ import annotations
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Awaitable
from datetime import datetime

from ..core.models import (
    AgentRun, RunStatus, RiskLevel,
    Session, Skill, Tool,
)
from ..core.intent_router import classify_intent, ClassifiedIntent, Intent
from ..core.database import async_session_factory
from ..core.logging import get_logger

logger = get_logger("orchestrator")


@dataclass
class AgentStep:
    """A single step in an execution plan."""
    id: str
    agent_type: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    tools_required: list[str] = field(default_factory=list)
    skills_required: list[str] = field(default_factory=list)
    status: RunStatus = RunStatus.PENDING
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


@dataclass
class ExecutionPlan:
    """Plan for executing a user query."""
    id: str
    query: str
    classified: ClassifiedIntent
    steps: list[AgentStep]
    estimated_tokens: int = 0
    estimated_cost: float = 0.0
    requires_approval: bool = False
    approval_reason: Optional[str] = None


# --- Agent type routing based on intent ---
INTENT_AGENT_MAP: dict[Intent, str] = {
    Intent.CODE: "coder",
    Intent.DEBUG: "debugger",
    Intent.TEST: "tester",
    Intent.REVIEW: "reviewer",
    Intent.DEPLOY: "deployer",
    Intent.DOCUMENT: "documenter",
    Intent.RESEARCH: "researcher",
    Intent.DATA: "data_engineer",
    Intent.SYSTEM: "sysadmin",
    Intent.CONVERSATION: "conversational",
    Intent.UNKNOWN: "general",
}

# Tools that require approval
APPROVAL_TOOLS = {"database", "production", "deploy", "secrets", "config"}
APPROVAL_RISK = {RiskLevel.HIGH, RiskLevel.CRITICAL}


class Orchestrator:
    """
    Orchestrator agent that:
    1. Classifies user intent
    2. Creates execution plan
    3. Routes to appropriate sub-agents
    4. Validates outputs
    5. Logs everything
    """

    def __init__(self, llm_func: Optional[Callable[..., Awaitable[str]]] = None):
        self.llm_func = llm_func
        self.tool_registry: dict[str, Tool] = {}
        self.skill_registry: dict[str, Skill] = {}

    async def plan(self, query: str, session_id: uuid.UUID) -> ExecutionPlan:
        """Create execution plan from user query."""
        t0 = time.time()

        # Step 1: Classify intent
        classified = await classify_intent(query, self.llm_func)
        logger.info(
            "intent_classified",
            intent=classified.intent.value,
            domain=classified.domain.value,
            risk=classified.risk_level.value,
            confidence=classified.confidence,
        )

        # Step 2: Determine agent type
        agent_type = INTENT_AGENT_MAP.get(classified.intent, "general")

        # Step 3: Create steps
        steps = self._create_steps(agent_type, classified, query)

        # Step 4: Check if approval needed
        requires_approval, approval_reason = self._check_approval(classified, steps)

        # Step 5: Estimate tokens
        est_tokens = self._estimate_tokens(query, steps)

        plan = ExecutionPlan(
            id=str(uuid.uuid4()),
            query=query,
            classified=classified,
            steps=steps,
            estimated_tokens=est_tokens,
            estimated_cost=est_tokens * 0.000005,  # rough GPT-4o-mini estimate
            requires_approval=requires_approval,
            approval_reason=approval_reason,
        )

        dt = (time.time() - t0) * 1000
        logger.info("plan_created", plan_id=plan.id, steps=len(steps), ms=dt)
        return plan

    def _create_steps(
        self, agent_type: str, classified: ClassifiedIntent, query: str
    ) -> list[AgentStep]:
        """Create execution steps based on intent."""
        steps = []

        # Main execution step
        main_step = AgentStep(
            id=str(uuid.uuid4()),
            agent_type=agent_type,
            action=classified.intent.value,
            params={"query": query, "domain": classified.domain.value},
        )

        # Add tools based on intent
        if classified.intent in (Intent.CODE, Intent.DEBUG, Intent.TEST):
            main_step.tools_required = ["file_read", "file_write", "shell_exec"]
            main_step.skills_required = ["rtk-tdd", "systematic-debugging"]
        elif classified.intent == Intent.REVIEW:
            main_step.tools_required = ["file_read"]
            main_step.skills_required = ["caveman-review", "requesting-code-review"]
        elif classified.intent == Intent.RESEARCH:
            main_step.tools_required = ["web_search", "file_read"]
            main_step.skills_required = ["web-search", "researcher"]
        elif classified.intent == Intent.DEPLOY:
            main_step.tools_required = ["shell_exec", "git"]
            main_step.skills_required = ["finishing-a-development-branch"]

        steps.append(main_step)

        # Add validation step
        if classified.intent in (Intent.CODE, Intent.DEBUG, Intent.TEST, Intent.DEPLOY):
            steps.append(AgentStep(
                id=str(uuid.uuid4()),
                agent_type="validator",
                action="validate",
                params={"validate_output": True},
                tools_required=["shell_exec"],
            ))

        return steps

    def _check_approval(
        self, classified: ClassifiedIntent, steps: list[AgentStep]
    ) -> tuple[bool, Optional[str]]:
        """Check if execution requires human approval."""
        # High/critical risk always needs approval
        if classified.risk_level in APPROVAL_RISK:
            return True, f"Risk level: {classified.risk_level.value}"

        # Check tools
        for step in steps:
            for tool in step.tools_required:
                if tool in APPROVAL_TOOLS:
                    return True, f"Tool requires approval: {tool}"

        # Deploy always needs approval
        if classified.intent == Intent.DEPLOY:
            return True, "Deploy operations require approval"

        return False, None

    def _estimate_tokens(self, query: str, steps: list[AgentStep]) -> int:
        """Rough token estimate for budget checking."""
        # Query tokens (~4 chars per token)
        query_tokens = len(query) // 4
        # System prompt
        system_tokens = 500
        # Per step
        step_tokens = len(steps) * 1000
        return query_tokens + system_tokens + step_tokens

    async def execute(
        self, plan: ExecutionPlan, session_id: uuid.UUID
    ) -> AgentRun:
        """Execute the plan and return the run record."""
        run = AgentRun(
            id=uuid.uuid4(),
            session_id=session_id,
            agent_type=plan.steps[0].agent_type if plan.steps else "general",
            status=RunStatus.RUNNING,
            risk_level=plan.classified.risk_level,
            user_query=plan.query,
            classified_intent=plan.classified.intent.value,
            classified_domain=plan.classified.domain.value,
            confidence=plan.classified.confidence,
            selected_skills=[s.id for s in plan.steps],
            selected_tools=[t for step in plan.steps for t in step.tools_required],
            plan=[{"id": s.id, "action": s.action, "agent": s.agent_type} for s in plan.steps],
            tokens_input=plan.estimated_tokens,
            model_used="pending",
        )

        t0 = time.time()
        try:
            # Execute each step
            for step in plan.steps:
                step.status = RunStatus.RUNNING
                logger.info("step_started", step_id=step.id, action=step.action)

                # Here would be actual sub-agent execution
                # For now, mark as success
                step.status = RunStatus.SUCCESS
                step.result = {"status": "simulated"}
                step.duration_ms = 100

            run.status = RunStatus.SUCCESS
            run.result = {"steps_completed": len(plan.steps)}

        except Exception as e:
            run.status = RunStatus.FAILED
            run.error = str(e)
            logger.error("execution_failed", error=str(e))

        run.completed_at = datetime.utcnow()
        run.duration_ms = int((time.time() - t0) * 1000)
        return run
