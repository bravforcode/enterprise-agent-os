"""End-to-end pipeline for Agent OS.

Flow: Input → Guards → Classify → Route → Plan → Execute → Validate → Log
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .core.logging import get_logger
from .core.intent_router import classify_intent, Intent
from .core.orchestrator import Orchestrator
from .core.output_validator import OutputValidator
from .core.run_logger import RunLogger
from .core.approval_flow import ApprovalFlow
from .governance import PolicyEngine, PolicyDecision
from .guards import check_input, check_output
from .agents.base import BaseSubAgent
from .agents.implementations import AGENT_REGISTRY
from .multi_agent import (
    PatternType,
    PipelineCoordinator,
    SupervisorCoordinator,
    ParallelCoordinator,
    create_coordinator,
)
from .observability.prometheus import (
    record_run,
    record_agent,
    record_pattern,
    record_guardrail,
    record_policy,
)

logger = get_logger(__name__)


@dataclass
class PipelineRequest:
    """Request to process through the pipeline."""
    input: str
    user_id: str | None = None
    session_id: str | None = None
    pattern: str | None = None  # Optional: force a multi-agent pattern
    context: dict[str, Any] = field(default_factory=dict)
    skip_guards: bool = False
    skip_governance: bool = False


@dataclass
class PipelineResponse:
    """Response from the pipeline."""
    request_id: str
    success: bool
    output: Any
    stages: list[dict[str, Any]]
    duration_ms: float
    intent: str | None = None
    domain: str | None = None
    risk_level: str | None = None
    pattern_used: str | None = None
    blocked_reason: str | None = None
    approval_required: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class EndToEndPipeline:
    """Full pipeline: Input → Guards → Classify → Route → Plan → Execute → Validate → Log.

    This wires all the major Agent OS components together.
    """

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        output_validator: OutputValidator | None = None,
        run_logger: RunLogger | None = None,
        policy_engine: PolicyEngine | None = None,
        agents: dict[str, BaseSubAgent] | None = None,
    ) -> None:
        self.orchestrator = orchestrator or Orchestrator()
        self.output_validator = output_validator or OutputValidator()
        self.run_logger = run_logger
        self.policy_engine = policy_engine or PolicyEngine()
        self.agents = agents or AGENT_REGISTRY

    async def process(self, request: PipelineRequest) -> PipelineResponse:
        """Run the full pipeline."""
        request_id = str(uuid.uuid4())
        start = time.time()
        stages: list[dict[str, Any]] = []

        def _log_stage(name: str, status: str, **details: Any) -> None:
            stage = {
                "name": name,
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
                **details,
            }
            stages.append(stage)
            logger.info("pipeline.stage", **stage)

        # ============================================================
        # Stage 1: Input Guards
        # ============================================================
        if not request.skip_guards:
            guard_result = check_input(request.input)
            _log_stage("input_guard", "block" if not guard_result.passed else "pass",
                       reason=guard_result.reason, severity=guard_result.severity)
            if not guard_result.passed and guard_result.severity == "block":
                record_guardrail(guard_result.metadata.get("type", "input"), True)
                return self._fail_response(
                    request_id, start, stages,
                    f"Input blocked by guardrail: {guard_result.reason}",
                )
            record_guardrail(guard_result.metadata.get("type", "input"), False)

        # ============================================================
        # Stage 2: Intent Classification
        # ============================================================
        intent = await classify_intent(request.input)
        _log_stage("classify", "pass",
                   intent=intent.intent.value, domain=intent.domain.value,
                   risk_level=intent.risk_level.value, confidence=intent.confidence)

        # ============================================================
        # Stage 3: Governance Check
        # ============================================================
        if not request.skip_governance:
            action = self._map_intent_to_action(intent.intent)
            decision, reason = self.policy_engine.evaluate(
                action, {"input": request.input, "user_id": request.user_id}
            )
            _log_stage("governance", decision.value, action=action, reason=reason)
            record_policy(decision.value)

            if decision == PolicyDecision.DENY:
                return self._fail_response(
                    request_id, start, stages,
                    f"Blocked by policy: {reason}",
                )
            if decision == PolicyDecision.ALLOW_WITH_APPROVAL:
                return PipelineResponse(
                    request_id=request_id,
                    success=False,
                    output=None,
                    stages=stages,
                    duration_ms=(time.time() - start) * 1000,
                    intent=intent.intent.value,
                    domain=intent.domain.value,
                    risk_level=intent.risk_level.value,
                    approval_required=True,
                    blocked_reason=reason,
                )

        # ============================================================
        # Stage 4: Route to pattern or direct agent
        # ============================================================
        if request.pattern:
            # Multi-agent pattern
            pattern_result = await self._run_pattern(
                request, intent, request.pattern
            )
            _log_stage("pattern", "pass" if pattern_result["success"] else "fail",
                       pattern=request.pattern,
                       agents_used=pattern_result.get("agents_used", 0))
            output = pattern_result["output"]
            pattern_used = request.pattern
            record_pattern(
                request.pattern, pattern_result["success"],
                pattern_result.get("agents_used", 0)
            )
        else:
            # Direct agent routing
            agent_name = self._route_to_agent(intent.intent)
            if agent_name is None:
                return self._fail_response(
                    request_id, start, stages,
                    f"No agent found for intent {intent.intent.value}",
                )
            _log_stage("route", "pass", agent=agent_name)
            agent = self._get_agent_instance(agent_name)
            agent_result = await agent.run(
                request.input, context=request.context
            )
            _log_stage("execute", "pass" if agent_result.success else "fail",
                       agent=agent_name, duration_ms=agent_result.duration_ms)
            if not agent_result.success:
                return self._fail_response(
                    request_id, start, stages,
                    agent_result.error or "Agent execution failed",
                )
            output = agent_result.output
            record_agent(agent_name, "direct", agent_result.duration_ms / 1000, agent_result.success)
            pattern_used = "direct"

        # ============================================================
        # Stage 5: Output Validation
        # ============================================================
        if not request.skip_guards:
            validation = self.output_validator.validate(str(output))
            _log_stage("output_validate", "pass" if validation.valid else "fail",
                       errors=validation.errors[:3],
                       warnings=validation.warnings[:3],
                       safety_blocked=validation.safety_blocked)
            if validation.safety_blocked:
                return self._fail_response(
                    request_id, start, stages,
                    f"Output blocked by safety check: {validation.errors}",
                )
            # Use sanitized output
            output = validation.sanitized_output
            record_guardrail("output", validation.safety_blocked)

        # ============================================================
        # Stage 6: Log
        # ============================================================
        duration = (time.time() - start) * 1000
        if self.run_logger:
            try:
                await self.run_logger.log_run(
                    request_id=request_id,
                    user_id=request.user_id,
                    input_text=request.input,
                    output=str(output),
                    intent=intent.intent.value,
                    domain=intent.domain.value,
                    duration_ms=duration,
                    metadata={"pattern": pattern_used},
                )
            except Exception as e:
                logger.warning("log_failed", error=str(e))

        # Record metrics
        record_run(
            intent.intent.value, intent.domain.value, "success", duration / 1000
        )

        return PipelineResponse(
            request_id=request_id,
            success=True,
            output=output,
            stages=stages,
            duration_ms=duration,
            intent=intent.intent.value,
            domain=intent.domain.value,
            risk_level=intent.risk_level.value,
            pattern_used=pattern_used,
            metadata={"stages_count": len(stages)},
        )

    def _get_agent_instance(self, agent_name: str) -> BaseSubAgent:
        """Get agent instance, instantiating class if needed."""
        agent = self.agents.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent {agent_name!r} not found")
        if isinstance(agent, type):
            # Instantiate and cache only locally (don't mutate shared registry)
            instance = agent()
            # Only cache locally if self.agents is a copy, not the shared registry
            if self.agents is not AGENT_REGISTRY:
                self.agents[agent_name] = instance
            return instance
        return agent

    def _map_intent_to_action(self, intent: Any) -> str:
        """Map intent to a policy action."""
        # Accept either ClassifiedIntent or Intent enum
        intent_val = intent.intent if hasattr(intent, "intent") else intent
        action_map = {
            Intent.CODE: "exec",
            Intent.REVIEW: "read_file",
            Intent.DEBUG: "exec",
            Intent.RESEARCH: "read_file",
            Intent.DOCUMENT: "write_file",
            Intent.DEPLOY: "deploy",
            Intent.TEST: "exec",
            Intent.DATA: "delete_file",
            Intent.SYSTEM: "exec",
            Intent.CONVERSATION: "read_file",
            Intent.UNKNOWN: "read_file",
        }
        return action_map.get(intent_val, "read_file")

    def _route_to_agent(self, intent: Any) -> str | None:
        """Map intent to agent name."""
        intent_val = intent.intent if hasattr(intent, "intent") else intent
        route_map = {
            Intent.CODE: "coder",
            Intent.REVIEW: "reviewer",
            Intent.DEBUG: "debugger",
            Intent.RESEARCH: "researcher",
            Intent.DOCUMENT: "documenter",
            Intent.DEPLOY: "deployer",
            Intent.TEST: "tester",
            Intent.DATA: "data_engineer",
            Intent.SYSTEM: "sysadmin",
            Intent.CONVERSATION: "conversational",
        }
        return route_map.get(intent_val)

    async def _run_pattern(
        self,
        request: PipelineRequest,
        intent: Any,
        pattern: str,
    ) -> dict[str, Any]:
        """Run a multi-agent pattern."""
        try:
            pattern_type = PatternType(pattern)
        except ValueError:
            return {"success": False, "output": None, "agents_used": 0,
                    "error": f"Unknown pattern: {pattern}"}

        # Auto-build config based on pattern
        if pattern_type == PatternType.PIPELINE:
            config = {"stages": ["coder", "reviewer", "tester"]}
        elif pattern_type == PatternType.SUPERVISOR:
            config = {"workers": ["coder", "reviewer", "researcher"]}
        elif pattern_type == PatternType.PARALLEL:
            config = {"branches": ["researcher", "analyst"]}
        elif pattern_type == PatternType.HIERARCHICAL:
            config = {
                "root": "architect",
                "tree": {"architect": ["coder", "reviewer"]},
            }
        elif pattern_type == PatternType.DEBATE:
            config = {
                "debaters": ["coder", "reviewer"],
                "judge": "validator",
                "rounds": 1,
            }
        elif pattern_type == PatternType.CONSENSUS:
            config = {"voters": ["coder", "reviewer", "tester"], "threshold": 0.5}
        elif pattern_type == PatternType.MARKETPLACE:
            config = {"workers": ["coder", "researcher"], "strategy": "first"}
        else:
            return {"success": False, "output": None, "agents_used": 0,
                    "error": f"Unsupported pattern: {pattern}"}

        # Filter to only available agents
        for key in ["stages", "workers", "branches", "debaters", "voters"]:
            if key in config:
                config[key] = [a for a in config[key] if a in self.agents]
        if "judge" in config and config["judge"] not in self.agents:
            config["judge"] = next(iter(self.agents.keys()))

        try:
            coord = create_coordinator(pattern, config, agents=self.agents)
            result = await coord.coordinate(request.input, context=request.context)
            return {
                "success": result.success,
                "output": result.output,
                "agents_used": len(result.agent_results),
                "error": result.error,
            }
        except Exception as e:
            return {"success": False, "output": None, "agents_used": 0,
                    "error": str(e)}

    def _fail_response(
        self,
        request_id: str,
        start: float,
        stages: list[dict[str, Any]],
        reason: str,
    ) -> PipelineResponse:
        """Create a failure response."""
        duration = (time.time() - start) * 1000
        record_run("unknown", "unknown", "failure", duration / 1000)
        return PipelineResponse(
            request_id=request_id,
            success=False,
            output=None,
            stages=stages,
            duration_ms=duration,
            blocked_reason=reason,
            error=reason,
        )
