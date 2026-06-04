"""MCP Declarative Workflows — Pattern-based multi-agent coordination.

Patterns:
- chain(agents)           — sequential execution, output→input passthrough
- parallel(agents, query) — fan-out to all agents, aggregate results
- router(agents, query)   — LLM-based route to best agent
- orchestrator(agents, goal) — plan steps then execute
- evaluator_optimizer(generator, evaluator) — generate→evaluate→refine loop

All patterns use graxia_agent_run under the hood and return structured results.
All handlers return _ok({...}) or _err(...) — see mcp.__init__.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import _ok, _err, logger  # type: ignore


@dataclass
class StepResult:
    step: int
    agent_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    workflow_id: str
    pattern: str
    success: bool
    steps: List[StepResult]
    final_output: Any
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Agent execution helper ───────────────────────────────────────────────


async def _run_agent(agent_name: str, query: str, context: Optional[Dict[str, Any]] = None) -> StepResult:
    """Run a single agent via the MCP _agent_run function."""
    from . import _agent_run  # type: ignore  # lazy import avoids circular

    t0 = time.time()
    args: Dict[str, Any] = {"agent_name": agent_name, "query": query}
    if context:
        args["context"] = context

    try:
        result = await _agent_run(args)
        duration_ms = (time.time() - t0) * 1000

        if isinstance(result, dict) and "content" in result:
            text = result["content"][0]["text"] if result["content"] else "{}"
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, IndexError):
                data = {"output": text}

            return StepResult(
                step=0, agent_name=agent_name,
                success=data.get("success", True),
                output=data.get("output", data),
                error=data.get("error"),
                duration_ms=data.get("duration_ms", duration_ms),
                metadata=data.get("metadata", {}),
            )

        return StepResult(step=0, agent_name=agent_name, success=True, output=result, duration_ms=duration_ms)
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        logger.exception("workflow_agent_run_failed", agent=agent_name)
        return StepResult(step=0, agent_name=agent_name, success=False, output=None, error=str(e), duration_ms=duration_ms)


# ── Pattern: Chain ──────────────────────────────────────────────────────


async def chain(
    agents: List[str],
    query: str,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Execute agents in sequence. Each agent's output becomes the next agent's input."""
    workflow_id = str(uuid.uuid4())
    t0 = time.time()
    steps: List[StepResult] = []
    current_input = query

    for i, agent_name in enumerate(agents):
        step = await _run_agent(agent_name, current_input, context)
        step.step = i + 1
        steps.append(step)

        if not step.success:
            return WorkflowResult(
                workflow_id=workflow_id, pattern="chain", success=False, steps=steps,
                final_output=None, duration_ms=(time.time() - t0) * 1000,
                metadata={"failed_at_step": i + 1, "failed_agent": agent_name},
            )

        current_input = str(step.output) if step.output is not None else ""

    return WorkflowResult(
        workflow_id=workflow_id, pattern="chain", success=True, steps=steps,
        final_output=steps[-1].output if steps else None,
        duration_ms=(time.time() - t0) * 1000,
        metadata={"agents_executed": len(steps)},
    )


# ── Pattern: Parallel ───────────────────────────────────────────────────


async def parallel(
    agents: List[str],
    query: str,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Execute all agents concurrently with the same query. Results are aggregated."""
    workflow_id = str(uuid.uuid4())
    t0 = time.time()

    tasks = [_run_agent(name, query, context) for name in agents]
    steps = await asyncio.gather(*tasks, return_exceptions=False)

    step_results: List[StepResult] = []
    for i, step in enumerate(steps):
        step.step = i + 1
        step_results.append(step)

    aggregated = [
        {"agent": s.agent_name, "success": s.success, "output": s.output, "error": s.error, "duration_ms": s.duration_ms}
        for s in step_results
    ]

    return WorkflowResult(
        workflow_id=workflow_id, pattern="parallel",
        success=all(s.success for s in step_results),
        steps=step_results, final_output=aggregated,
        duration_ms=(time.time() - t0) * 1000,
        metadata={
            "agents_executed": len(step_results),
            "success_count": sum(1 for s in step_results if s.success),
            "failure_count": sum(1 for s in step_results if not s.success),
        },
    )


# ── Pattern: Router ─────────────────────────────────────────────────────


async def router(
    agents: List[str],
    query: str,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Route the query to the most appropriate agent using LLM-based selection."""
    workflow_id = str(uuid.uuid4())
    t0 = time.time()

    if not agents:
        return WorkflowResult(workflow_id=workflow_id, pattern="router", success=False, steps=[], final_output=None, duration_ms=(time.time() - t0) * 1000, metadata={"error": "No agents provided"})

    if len(agents) == 1:
        step = await _run_agent(agents[0], query, context)
        step.step = 1
        return WorkflowResult(workflow_id=workflow_id, pattern="router", success=step.success, steps=[step], final_output=step.output, duration_ms=(time.time() - t0) * 1000, metadata={"routed_to": agents[0], "reason": "single_agent"})

    agent_list_str = ", ".join(agents)
    router_prompt = f"Given agents: [{agent_list_str}]\nChoose the SINGLE best agent. Reply with ONLY the agent name.\n\nQuery: {query}"

    router_step = await _run_agent("general", router_prompt, context)
    router_step.step = 1

    if not router_step.success or not router_step.output:
        selected = agents[0]
    else:
        selected_name = str(router_step.output).strip().strip('"').strip("'").lower()
        selected = agents[0]
        for a in agents:
            if a.lower() in selected_name or selected_name in a.lower():
                selected = a
                break

    exec_step = await _run_agent(selected, query, context)
    exec_step.step = 2

    return WorkflowResult(
        workflow_id=workflow_id, pattern="router", success=exec_step.success,
        steps=[router_step, exec_step], final_output=exec_step.output,
        duration_ms=(time.time() - t0) * 1000,
        metadata={"routed_to": selected, "candidates": agents, "router_reasoning": router_step.output},
    )


# ── Pattern: Orchestrator ───────────────────────────────────────────────


async def orchestrator(
    agents: List[str],
    goal: str,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Plan execution steps using a planner agent, then execute them sequentially."""
    workflow_id = str(uuid.uuid4())
    t0 = time.time()
    steps: List[StepResult] = []

    agent_list_str = ", ".join(agents)
    plan_prompt = (
        f"Decompose this goal into ordered steps. Available agents: [{agent_list_str}]\n"
        f"For each step, specify: agent_name | task description.\n"
        f"Format: one step per line as 'agent_name: task'\nGoal: {goal}"
    )

    plan_step = await _run_agent("general", plan_prompt, context)
    plan_step.step = 0
    steps.append(plan_step)

    if not plan_step.success or not plan_step.output:
        return WorkflowResult(workflow_id=workflow_id, pattern="orchestrator", success=False, steps=steps, final_output=None, duration_ms=(time.time() - t0) * 1000, metadata={"error": "Planning failed"})

    plan_text = str(plan_step.output)
    parsed_steps: List[Tuple[str, str]] = []
    for line in plan_text.strip().splitlines():
        line = line.strip()
        if not line or ("|" not in line and ":" not in line):
            continue
        sep = "|" if "|" in line else ":"
        parts = line.split(sep, 1)
        if len(parts) == 2:
            agent_name = parts[0].strip().strip("*").strip("-").strip()
            task = parts[1].strip()
            matched = next((a for a in agents if a.lower() == agent_name.lower()), None)
            if matched:
                parsed_steps.append((matched, task))

    if not parsed_steps:
        fallback_step = await _run_agent(agents[0], goal, context)
        fallback_step.step = 1
        steps.append(fallback_step)
        return WorkflowResult(workflow_id=workflow_id, pattern="orchestrator", success=fallback_step.success, steps=steps, final_output=fallback_step.output, duration_ms=(time.time() - t0) * 1000, metadata={"parse_failed": True, "fallback_agent": agents[0]})

    accumulated_context = dict(context) if context else {}
    for i, (agent_name, task) in enumerate(parsed_steps):
        step = await _run_agent(agent_name, task, accumulated_context)
        step.step = i + 1
        steps.append(step)

        if not step.success:
            return WorkflowResult(workflow_id=workflow_id, pattern="orchestrator", success=False, steps=steps, final_output=None, duration_ms=(time.time() - t0) * 1000, metadata={"failed_at_step": i + 1, "failed_agent": agent_name, "total_planned": len(parsed_steps)})

        accumulated_context["previous_output"] = str(step.output) if step.output else ""

    return WorkflowResult(
        workflow_id=workflow_id, pattern="orchestrator", success=True, steps=steps,
        final_output=steps[-1].output if len(steps) > 1 else None,
        duration_ms=(time.time() - t0) * 1000,
        metadata={"planned_steps": len(parsed_steps), "executed_steps": len(steps) - 1, "agents_used": list({s.agent_name for s in steps[1:]})},
    )


# ── Pattern: Evaluator-Optimizer ────────────────────────────────────────


async def evaluator_optimizer(
    generator: str,
    evaluator: str,
    goal: str,
    max_iterations: int = 3,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Generate → Evaluate → Refine loop until approval or max iterations."""
    workflow_id = str(uuid.uuid4())
    t0 = time.time()
    steps: List[StepResult] = []
    best_output = None

    for iteration in range(max_iterations):
        gen_prompt = goal if iteration == 0 else (
            f"Previous output was rejected. Improve it.\nGoal: {goal}\n"
            f"Previous output: {best_output}\n"
            f"Feedback: {steps[-1].metadata.get('evaluator_feedback', '')}\n"
            f"Generate an improved version."
        )
        gen_step = await _run_agent(generator, gen_prompt, context)
        gen_step.step = iteration * 2 + 1
        gen_step.metadata["iteration"] = iteration + 1
        gen_step.metadata["phase"] = "generate"
        steps.append(gen_step)

        if not gen_step.success:
            return WorkflowResult(workflow_id=workflow_id, pattern="evaluator_optimizer", success=False, steps=steps, final_output=None, duration_ms=(time.time() - t0) * 1000, metadata={"failed_at_iteration": iteration + 1, "phase": "generate"})

        best_output = gen_step.output

        eval_prompt = (
            f"Evaluate this output against the goal.\nGoal: {goal}\nOutput: {best_output}\n\n"
            f"Reply with EXACTLY one of: APPROVE or REVISE:<reason>"
        )
        eval_step = await _run_agent(evaluator, eval_prompt, context)
        eval_step.step = iteration * 2 + 2
        eval_step.metadata["iteration"] = iteration + 1
        eval_step.metadata["phase"] = "evaluate"
        steps.append(eval_step)

        if not eval_step.success:
            return WorkflowResult(workflow_id=workflow_id, pattern="evaluator_optimizer", success=False, steps=steps, final_output=best_output, duration_ms=(time.time() - t0) * 1000, metadata={"failed_at_iteration": iteration + 1, "phase": "evaluate"})

        eval_text = str(eval_step.output).strip().upper()
        if eval_text.startswith("APPROVE"):
            return WorkflowResult(workflow_id=workflow_id, pattern="evaluator_optimizer", success=True, steps=steps, final_output=best_output, duration_ms=(time.time() - t0) * 1000, metadata={"iterations": iteration + 1, "max_iterations": max_iterations, "approved": True})

        feedback = str(eval_step.output).split("REVISE:", 1)[1].strip() if "REVISE:" in str(eval_step.output) else str(eval_step.output)
        eval_step.metadata["evaluator_feedback"] = feedback

    return WorkflowResult(workflow_id=workflow_id, pattern="evaluator_optimizer", success=False, steps=steps, final_output=best_output, duration_ms=(time.time() - t0) * 1000, metadata={"iterations": max_iterations, "max_iterations": max_iterations, "approved": False, "reason": "max_iterations_reached"})


# ── Result serialization ────────────────────────────────────────────────


def _serialize_result(result: WorkflowResult) -> Dict[str, Any]:
    return {
        "workflow_id": result.workflow_id,
        "pattern": result.pattern,
        "success": result.success,
        "final_output": result.final_output,
        "duration_ms": result.duration_ms,
        "steps": [
            {"step": s.step, "agent_name": s.agent_name, "success": s.success, "output": s.output, "error": s.error, "duration_ms": s.duration_ms, "metadata": s.metadata}
            for s in result.steps
        ],
        "metadata": result.metadata,
    }


# ── MCP tool handlers ───────────────────────────────────────────────────


async def workflow_chain_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    agents = args.get("agents") or []
    query = str(args.get("query", ""))
    context = args.get("context")
    if not agents:
        return _err("agents list is required")
    if not query:
        return _err("query is required")
    return _ok(_serialize_result(await chain(agents, query, context)))


async def workflow_parallel_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    agents = args.get("agents") or []
    query = str(args.get("query", ""))
    context = args.get("context")
    if not agents:
        return _err("agents list is required")
    if not query:
        return _err("query is required")
    return _ok(_serialize_result(await parallel(agents, query, context)))


async def workflow_router_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    agents = args.get("agents") or []
    query = str(args.get("query", ""))
    context = args.get("context")
    if not agents:
        return _err("agents list is required")
    if not query:
        return _err("query is required")
    return _ok(_serialize_result(await router(agents, query, context)))


async def workflow_orchestrator_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    agents = args.get("agents") or []
    goal = str(args.get("goal", ""))
    context = args.get("context")
    if not agents:
        return _err("agents list is required")
    if not goal:
        return _err("goal is required")
    return _ok(_serialize_result(await orchestrator(agents, goal, context)))


async def workflow_evaluator_optimizer_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    generator = str(args.get("generator", ""))
    evaluator = str(args.get("evaluator", ""))
    goal = str(args.get("goal", ""))
    max_iterations = int(args.get("max_iterations", 3))
    context = args.get("context")
    if not generator or not evaluator:
        return _err("generator and evaluator agent names are required")
    if not goal:
        return _err("goal is required")
    return _ok(_serialize_result(await evaluator_optimizer(generator, evaluator, goal, max_iterations, context)))


# ── Tool specs ───────────────────────────────────────────────────────────

WORKFLOW_TOOL_SPECS = [
    {
        "name": "workflow_chain",
        "description": "Run a chain workflow: execute agents in sequence, each agent's output becomes the next agent's input.",
        "input_schema": {"type": "object", "properties": {"agents": {"type": "array", "items": {"type": "string"}}, "query": {"type": "string"}, "context": {"type": "object"}}, "required": ["agents", "query"]},
        "handler": workflow_chain_handler,
        "category": "workflow",
    },
    {
        "name": "workflow_parallel",
        "description": "Run a parallel workflow: fan-out query to all agents concurrently, aggregate results.",
        "input_schema": {"type": "object", "properties": {"agents": {"type": "array", "items": {"type": "string"}}, "query": {"type": "string"}, "context": {"type": "object"}}, "required": ["agents", "query"]},
        "handler": workflow_parallel_handler,
        "category": "workflow",
    },
    {
        "name": "workflow_router",
        "description": "Run a router workflow: LLM-based selection picks the best agent for the query.",
        "input_schema": {"type": "object", "properties": {"agents": {"type": "array", "items": {"type": "string"}}, "query": {"type": "string"}, "context": {"type": "object"}}, "required": ["agents", "query"]},
        "handler": workflow_router_handler,
        "category": "workflow",
    },
    {
        "name": "workflow_orchestrator",
        "description": "Run an orchestrator workflow: plan steps from a goal, then execute them sequentially.",
        "input_schema": {"type": "object", "properties": {"agents": {"type": "array", "items": {"type": "string"}}, "goal": {"type": "string"}, "context": {"type": "object"}}, "required": ["agents", "goal"]},
        "handler": workflow_orchestrator_handler,
        "category": "workflow",
    },
    {
        "name": "workflow_evaluator_optimizer",
        "description": "Run an evaluator-optimizer workflow: generate→evaluate→refine loop until approval.",
        "input_schema": {"type": "object", "properties": {"generator": {"type": "string"}, "evaluator": {"type": "string"}, "goal": {"type": "string"}, "max_iterations": {"type": "integer", "default": 3}, "context": {"type": "object"}}, "required": ["generator", "evaluator", "goal"]},
        "handler": workflow_evaluator_optimizer_handler,
        "category": "workflow",
    },
]
