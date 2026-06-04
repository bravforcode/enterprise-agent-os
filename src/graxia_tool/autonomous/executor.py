"""Autonomous execution loop: plan -> execute -> observe -> replan.

This is the runtime half of ANUS-style autonomous mode. Given a high-level
goal and a registry of MCP tools, the executor:

    1. builds a plan with the GOAP planner
    2. calls each step's tool through the registry
    3. observes the result, mutates the world state accordingly
    4. on failure, replans from the *current* state (not from scratch)
    5. asks the LLM after each step whether the goal looks satisfied

The executor is fully autonomous — it never blocks for user input.
"""
from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ..llm import LLMClient
from .planner import GOAPPlanner, Plan, PlanStep, ToolSpec, WorldState, specs_from_registry
from .store import RunRecord, RunStatus, StepRecord


# A ToolHandler is any async function taking (Dict[str,Any]) and returning
# a Dict[str,Any] that follows the MCP _ok/_err shape. The MCP registry
# already exposes one of these for every tool.
ToolHandler = Callable[[Dict[str, Any]], "asyncio.Future[Any]"]


@dataclass
class ExecutionResult:
    """What the executor returns after a (possibly partial) autonomous run."""
    run_id: str
    success: bool
    goal: str
    steps_executed: int = 0
    replans: int = 0
    final_output: Any = None
    error: Optional[str] = None
    tool_chain: List[str] = field(default_factory=list)
    duration_s: float = 0.0
    record: Optional[RunRecord] = None
    plan: Optional[Plan] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "success": self.success,
            "goal": self.goal,
            "steps_executed": self.steps_executed,
            "replans": self.replans,
            "final_output": self.final_output,
            "error": self.error,
            "tool_chain": self.tool_chain,
            "duration_s": round(self.duration_s, 2),
            "plan_source": self.plan.source if self.plan else None,
        }


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class AutonomousExecutor:
    """Run a goal end-to-end through the MCP tool registry."""

    def __init__(
        self,
        registry,
        llm_client: Optional[LLMClient] = None,
        store=None,
        max_steps: int = 20,
        max_replans: int = 2,
        on_step: Optional[Callable[[StepRecord], None]] = None,
    ):
        self.registry = registry
        self.llm = llm_client
        self.store = store
        self.max_steps = max(1, max_steps)
        self.max_replans = max(0, max_replans)
        self.on_step = on_step

    # -- public --------------------------------------------------------

    async def run(self, goal: str, initial_state: Optional[WorldState] = None,
                  constraints: Optional[List[str]] = None,
                  run_id: Optional[str] = None) -> ExecutionResult:
        """Plan + execute + observe + replan until goal met or budget exhausted."""
        run_id = run_id or str(uuid.uuid4())
        record = RunRecord(run_id=run_id, goal=goal,
                           status=RunStatus.IN_PROGRESS, started_at=time.time())
        if self.store is not None:
            self.store.upsert(record)
        t0 = time.time()

        specs = specs_from_registry(self.registry)
        planner = GOAPPlanner(specs, llm_client=self.llm)

        state = (initial_state or WorldState()).clone()
        replans = 0
        last_plan: Optional[Plan] = None
        last_error: Optional[str] = None
        all_steps: List[PlanStep] = []

        try:
            while True:
                if len(all_steps) >= self.max_steps:
                    record.error = f"max_steps={self.max_steps} reached"
                    break

                plan = await planner.plan(goal, state, constraints)
                last_plan = plan
                if not plan.steps:
                    record.error = "planner returned no steps"
                    break

                # execute steps in order
                halted = False
                for step in plan.steps:
                    if len(all_steps) >= self.max_steps:
                        halted = True
                        break
                    if step.tool in (s.tool for s in all_steps):
                        # already used this tool in this run — skip duplicate
                        continue
                    step_record = await self._execute_step(step)
                    record.steps.append(step_record)
                    if self.on_step:
                        try:
                            self.on_step(step_record)
                        except Exception:
                            pass
                    all_steps.append(step)
                    if step_record.success:
                        state.add(
                            f"tool_called:{step.tool}",
                            f"tool_succeeded:{step.tool}",
                            f"result_available:{step.tool}",
                        )
                    else:
                        state.add(f"tool_called:{step.tool}", f"tool_failed:{step.tool}")
                        last_error = step_record.error
                    # ask LLM: is the goal met?
                    if self.llm is not None and step_record.success:
                        if await self._goal_likely_met(goal, state, record):
                            state.add("goal_signal")
                            break

                # success condition
                if state.has("goal_signal"):
                    record.status = RunStatus.COMPLETED
                    break

                # replan if we have budget and the plan didn't fully succeed
                if replans >= self.max_replans:
                    if not record.error:
                        record.error = (
                            last_error or "exhausted replan budget without goal_signal"
                        )
                    break
                replans += 1
                record.replans = replans
                record.status = RunStatus.REPLANNED
                if halted:
                    break
                # continue loop -> plan again from current state
        except Exception as e:
            record.status = RunStatus.FAILED
            record.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}"

        record.tool_chain = [s.tool for s in all_steps]
        record.plan_steps = len(all_steps)
        record.finished_at = time.time()
        record.final_output = _summarize_output(record)

        if record.status not in (RunStatus.COMPLETED,):
            if record.error and "max_steps" not in record.error:
                if not record.status == RunStatus.REPLANNED:
                    record.status = RunStatus.FAILED

        if self.store is not None:
            self.store.upsert(record)

        return ExecutionResult(
            run_id=run_id,
            success=record.status == RunStatus.COMPLETED,
            goal=goal,
            steps_executed=len(all_steps),
            replans=replans,
            final_output=record.final_output,
            error=record.error,
            tool_chain=record.tool_chain,
            duration_s=time.time() - t0,
            record=record,
            plan=last_plan,
        )

    # -- internals -----------------------------------------------------

    async def _execute_step(self, step: PlanStep) -> StepRecord:
        """Call the tool through the MCP registry and capture the result."""
        tool = self.registry.get(step.tool)
        t0 = time.time()
        if tool is None:
            return StepRecord(
                step_id=step.step_id, tool=step.tool, args=step.args,
                success=False, error=f"unknown tool: {step.tool}",
                duration_s=0.0,
            )
        try:
            result = await tool.handler(step.args)
            ok = _is_ok(result)
            return StepRecord(
                step_id=step.step_id, tool=step.tool, args=step.args,
                success=ok,
                output=_extract_text(result) if ok else None,
                error=None if ok else _extract_error(result),
                duration_s=time.time() - t0,
            )
        except Exception as e:
            return StepRecord(
                step_id=step.step_id, tool=step.tool, args=step.args,
                success=False, error=f"{type(e).__name__}: {e}",
                duration_s=time.time() - t0,
            )

    async def _goal_likely_met(
        self,
        goal: str,
        state: WorldState,
        record: RunRecord,
    ) -> bool:
        """Ask the LLM whether the observed state already satisfies the goal."""
        if self.llm is None:
            return False
        recent = [
            f"{s.tool}({'OK' if s.success else 'FAIL'}): "
            f"{str(s.output or s.error or '')[:80]}"
            for s in record.steps[-5:]
        ]
        prompt = f"""Given the recent tool outputs below, is the GOAL satisfied?

GOAL: {goal}

RECENT STEPS:
{chr(10).join(recent) or '(none)'}

Reply with a single JSON object: {{"done": <bool>, "reason": "<short>"}}"""
        try:
            resp = await self.llm.complete(
                prompt=prompt,
                system="You are a strict goal-checker. Reply with JSON only.",
                max_tokens=120, temperature=0.0,
            )
            txt = resp.content or ""
            txt = txt.strip()
            txt = txt.replace("```json", "").replace("```", "").strip()
            obj = json.loads(txt) if txt.startswith("{") else {}
            return bool(obj.get("done", False))
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_ok(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("isError") is True:
        return False
    # mcp error shape: { error: { code, message } }
    if "error" in result and isinstance(result["error"], dict):
        return False
    return True


def _extract_text(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                return json.loads(first["text"])
            except (json.JSONDecodeError, TypeError):
                return first["text"]
    return result


def _extract_error(result: Any) -> str:
    if not isinstance(result, dict):
        return "unknown error"
    if "error" in result and isinstance(result["error"], dict):
        return str(result["error"].get("message", "error"))
    if "isError" in result and result["isError"]:
        content = result.get("content") or []
        if content and isinstance(content[0], dict):
            return str(content[0].get("text", "error"))
    return "error"


def _summarize_output(record: RunRecord) -> Dict[str, Any]:
    """Pick a compact, useful summary of the run's outputs."""
    last_ok = next(
        (s for s in reversed(record.steps) if s.success and s.output is not None),
        None,
    )
    return {
        "status": record.status.value,
        "tool_chain": record.tool_chain,
        "steps": len(record.steps),
        "last_output": last_ok.output if last_ok else None,
    }
