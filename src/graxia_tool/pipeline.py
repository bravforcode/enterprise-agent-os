"""End-to-end pipeline for Agent OS.

Flow: Input → Guards → Classify → Route → Hydrate Skills → Plan → Execute → Heal → Validate → Log
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

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
from .auto_router import AutoRouter, RoutingDecision
from .session_memory import SessionMemory, TaskRecord
from .context_cache import ContextCache
from .skills.registry import SkillRegistry, SkillDefinition
from .learning.self_learner import SelfLearner
from .optimization.token_optimizer import TokenOptimizer, get_optimizer
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
    skills_context: dict[str, str] = field(default_factory=dict)
    routing_decision: Optional[dict[str, Any]] = None


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
    healing_attempts: int = 0
    skills_loaded: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Fallback map for auto-healing ─────────────────────────────────────

FALLBACK_MAP: dict[str, list[str]] = {
    'coder': ['general', 'conversational'],
    'debugger': ['coder', 'general'],
    'tester': ['coder', 'general'],
    'reviewer': ['general', 'conversational'],
    'deployer': ['sysadmin', 'general'],
    'documenter': ['general', 'conversational'],
    'researcher': ['architect', 'general'],
    'data_engineer': ['coder', 'general'],
    'sysadmin': ['general', 'conversational'],
    'planner': ['architect', 'general'],
    'architect': ['planner', 'general'],
    'security_auditor': ['reviewer', 'general'],
    'database_admin': ['data_engineer', 'coder', 'general'],
    'network_engineer': ['sysadmin', 'general'],
    'frontend_designer': ['coder', 'general'],
    'conversational': ['general'],
    'general': ['conversational'],
    'validator': ['general'],
}


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
        session_memory: SessionMemory | None = None,
        context_cache: ContextCache | None = None,
        skill_registry: SkillRegistry | None = None,
        token_optimizer: TokenOptimizer | None = None,
        self_learner: SelfLearner | None = None,
        max_retries: int = 2,
    ) -> None:
        self.orchestrator = orchestrator or Orchestrator()
        self.output_validator = output_validator or OutputValidator()
        self.run_logger = run_logger
        self.policy_engine = policy_engine or PolicyEngine()
        self.agents = agents or AGENT_REGISTRY
        self.self_learner = self_learner
        self.auto_router = AutoRouter(self_learner=self_learner)
        self.session_memory = session_memory or SessionMemory()
        self.context_cache = context_cache or ContextCache()
        self.skill_registry = skill_registry or SkillRegistry()
        self.token_optimizer = token_optimizer or get_optimizer()
        self.max_retries = max_retries

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
        # Stage 2: Auto-Route (intent + skills + RAG + agent + model)
        # ============================================================
        routing_decision = self.auto_router.route(
            request.input,
            context={**request.context, "session_memory": self.session_memory},
        )
        _log_stage("auto_route", "pass",
                    intent=routing_decision.intent,
                    agent=routing_decision.agent_type,
                    rag=routing_decision.rag_technique,
                    skills=routing_decision.skills,
                    mcp_tools=routing_decision.mcp_tools,
                    confidence=routing_decision.confidence,
                    model_tier=routing_decision.model_tier)

        # Store routing decision in request
        request.routing_decision = routing_decision.to_dict()

        # Stage 2b: Skill Auto-Hydration
        skills_context = self._hydrate_skills(routing_decision)
        request.skills_context = skills_context
        skills_loaded = list(skills_context.keys())
        _log_stage("skill_hydrate", "pass" if skills_loaded else "skip",
                   skills=skills_loaded, count=len(skills_loaded))

        # Use routing decision to override intent classification
        # (keep original for governance, but use routing for agent selection)
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
        # Stage 4: Route to pattern or direct agent (using AutoRouter)
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
            # Use AutoRouter's agent selection (falls back to intent-based routing)
            agent_name = routing_decision.agent_type
            if agent_name not in self.agents:
                agent_name = self._route_to_agent(intent.intent)
            if agent_name is None or agent_name not in self.agents:
                return self._fail_response(
                    request_id, start, stages,
                    f"No agent found for intent {intent.intent.value}",
                )
            _log_stage("route", "pass", agent=agent_name)

            # Build enriched context with skill content and token optimizer
            enriched_context = {
                **request.context,
                "skills_context": skills_context,
                "routing_decision": request.routing_decision,
                "token_optimizer": self.token_optimizer,
            }

            # Execute with auto-healing
            agent_result, healing_attempts = await self._execute_with_healing(
                agent_name=agent_name,
                prompt=request.input,
                context=enriched_context,
                intent=routing_decision.intent,
                stages_log=_log_stage,
                request_id=request_id,
            )

            if not agent_result.success:
                # Record failure for learning
                if self.self_learner is not None:
                    try:
                        self.self_learner.record_outcome(
                            task={
                                "intent": routing_decision.intent,
                                "domain": intent.domain.value,
                            },
                            success=False,
                            agent_used=agent_name,
                            duration_ms=agent_result.duration_ms,
                            skills_used=skills_loaded,
                        )
                    except Exception:
                        pass
                return self._fail_response(
                    request_id, start, stages,
                    agent_result.error or "Agent execution failed after healing",
                )
            output = agent_result.output
            record_agent(agent_name, "direct", agent_result.duration_ms / 1000, agent_result.success)
            pattern_used = "direct"

            # Stage 4b: Feedback — mark skills as useful if execution succeeded
            if agent_result.success and skills_loaded:
                self._store_skill_feedback(routing_decision, skills_loaded, success=True)

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

        # Collect token optimization stats
        token_opt_stats = self.token_optimizer.get_savings_report()

        # ============================================================
        # Stage 7: Store in Session Memory + Context Cache
        # ============================================================
        try:
            task_record = TaskRecord(
                task_id=request_id,
                prompt=request.input,
                routing_decision=routing_decision.to_dict(),
                outcome=str(output)[:500],
                success=True,
                duration_ms=duration,
                tokens_used=0,
                agent_type=routing_decision.agent_type,
                intent=routing_decision.intent,
                domain=intent.domain.value,
            )
            self.session_memory.remember_task(task_record)
        except Exception as e:
            logger.warning("memory_store_failed", error=str(e))

        try:
            self.context_cache.set(
                request.input,
                routing_decision,
                {"output": str(output)[:1000], "success": True},
            )
        except Exception as e:
            logger.warning("cache_store_failed", error=str(e))

        # ============================================================
        # Stage 8: Record outcome in SelfLearner
        # ============================================================
        if self.self_learner is not None:
            try:
                self.self_learner.record_outcome(
                    task={
                        "intent": routing_decision.intent,
                        "domain": intent.domain.value,
                    },
                    success=True,
                    agent_used=routing_decision.agent_type,
                    duration_ms=duration,
                    skills_used=skills_loaded,
                )
            except Exception as e:
                logger.warning("self_learner_record_failed", error=str(e))

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
            healing_attempts=healing_attempts if not request.pattern else 0,
            skills_loaded=skills_loaded,
            metadata={
                "stages_count": len(stages),
                "token_optimization": token_opt_stats,
            },
        )

    # ── Skill Auto-Hydration ─────────────────────────────────────────

    def _hydrate_skills(self, decision: RoutingDecision) -> dict[str, str]:
        """Load skill content for all skills in the routing decision.

        Returns dict of skill_name -> skill_content (text from skill file).
        """
        hydrated: dict[str, str] = {}
        self.skill_registry.maybe_reload()

        for skill_name in decision.skills:
            try:
                skill_def = self.skill_registry.get_skill(skill_name)
                if skill_def is None:
                    logger.debug("skill_not_found", skill=skill_name)
                    continue
                content = self._read_skill_content(skill_def)
                if content:
                    hydrated[skill_name] = content
                    logger.info("skill_hydrated", skill=skill_name, path=skill_def.path)
            except Exception as e:
                logger.warning("skill_hydrate_failed", skill=skill_name, error=str(e))

        return hydrated

    def _read_skill_content(self, skill_def: SkillDefinition) -> str:
        """Read the raw content of a skill definition file."""
        skill_path = skill_def.path
        # skill_def.path may point to a directory (SKILL.md) or a file
        if os.path.isdir(skill_path):
            md_path = os.path.join(skill_path, "SKILL.md")
            if os.path.isfile(md_path):
                with open(md_path, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            return ""
        if os.path.isfile(skill_path):
            with open(skill_path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        return ""

    def _store_skill_feedback(
        self,
        decision: RoutingDecision,
        skills_loaded: list[str],
        success: bool,
    ) -> None:
        """Record whether hydrated skills contributed to a successful outcome."""
        if not skills_loaded:
            return
        try:
            entry = {
                "intent": decision.intent,
                "skills": skills_loaded,
                "agent": decision.agent_type,
                "success": success,
                "timestamp": datetime.utcnow().isoformat(),
            }
            feedback_key = f"skill_feedback:{decision.cache_key}"
            self.context_cache.set(feedback_key, decision, entry)
            logger.info("skill_feedback_stored", skills=skills_loaded, success=success)
        except Exception as e:
            logger.debug("skill_feedback_failed", error=str(e))

    # ── Auto-Healing ─────────────────────────────────────────────────

    async def _execute_with_healing(
        self,
        agent_name: str,
        prompt: str,
        context: dict[str, Any],
        intent: str,
        stages_log: Any,
        request_id: str,
    ) -> tuple[Any, int]:
        """Execute agent with automatic fallback healing on failure.

        Returns (SubAgentResult, healing_attempts).
        """
        current_agent = agent_name
        healing_attempts = 0

        for attempt in range(self.max_retries + 1):
            agent = self._get_agent_instance(current_agent)
            agent_context = {
                **context,
                "healing_attempt": attempt,
                "healing_from": agent_name if attempt > 0 else None,
            }

            agent_result = await agent.run(prompt, context=agent_context)
            stages_log(
                "execute",
                "pass" if agent_result.success else "fail",
                agent=current_agent,
                duration_ms=agent_result.duration_ms,
                attempt=attempt + 1,
                healing_attempts=healing_attempts,
            )
            record_agent(
                current_agent, "direct",
                agent_result.duration_ms / 1000,
                agent_result.success,
            )

            if agent_result.success:
                return agent_result, healing_attempts

            # Attempt healing
            if attempt < self.max_retries:
                fallback = self._find_fallback_agent(intent, current_agent)
                if fallback is None or fallback == current_agent:
                    logger.warning(
                        "no_fallback_available",
                        agent=current_agent,
                        intent=intent,
                    )
                    break
                logger.info(
                    "healing_triggered",
                    failed_agent=current_agent,
                    fallback=fallback,
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )
                healing_attempts += 1
                current_agent = fallback

        return agent_result, healing_attempts

    def _find_fallback_agent(self, intent: str, failed_agent: str) -> str | None:
        """Find a fallback agent for a failed agent.

        Uses FALLBACK_MAP first, then tries intent-based mapping,
        then falls back to 'general' -> 'conversational'.
        """
        # Direct fallback map lookup
        fallbacks = FALLBACK_MAP.get(failed_agent)
        if fallbacks:
            for fb in fallbacks:
                if fb in self.agents:
                    return fb

        # Try intent-based fallback
        intent_lower = intent.lower()
        intent_fallback = {
            "code": "general",
            "debug": "coder",
            "test": "coder",
            "review": "general",
            "deploy": "sysadmin",
            "document": "general",
            "research": "general",
            "data": "coder",
            "system": "general",
            "conversation": "general",
        }
        candidate = intent_fallback.get(intent_lower)
        if candidate and candidate != failed_agent and candidate in self.agents:
            return candidate

        # Last resort
        if "general" in self.agents and "general" != failed_agent:
            return "general"
        if "conversational" in self.agents and "conversational" != failed_agent:
            return "conversational"
        return None

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
            healing_attempts=0,
            skills_loaded=[],
        )
