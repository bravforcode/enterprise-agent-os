"""GOAP-style A* planner over the available MCP tools.

GOAP (Goal-Oriented Action Planning) is a small, well-known planning
algorithm from the games-AI world. The key idea:

    - the world is a set of typed state variables
    - each tool/action has preconditions (what must be true to use it)
      and effects (what becomes true after using it)
    - we search the state graph from the current state to a goal state
      using A* with a domain heuristic

In our case the world state is small (which MCP tools have we already
called, what did they return) and the heuristic is the LLM's estimate
of how many more steps are likely needed to reach the goal. The LLM is
also used to filter/sequence the candidate tools at expansion time, so
the search stays tractable on a 40+ tool registry.
"""
from __future__ import annotations

import asyncio
import heapq
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

# LLM client factory: use the same HybridLLMClient as the rest of Graxia
from ..llm import HybridLLMClient, LLMClient


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class WorldState:
    """Minimal state representation used by the planner.

    We only track *categorical* facts:
      - "tool_called:<name>"               → True after we call a tool
      - "tool_succeeded:<name>"            → True if the call returned _ok
      - "result_available:<name>"          → True if a tool produced output
      - "goal_signal"                      → True when LLM thinks goal met
    """
    facts: Set[str] = field(default_factory=set)

    def has(self, fact: str) -> bool:
        return fact in self.facts

    def add(self, *facts: str) -> None:
        for f in facts:
            if f:
                self.facts.add(f)

    def remove(self, *facts: str) -> None:
        for f in facts:
            self.facts.discard(f)

    def clone(self) -> "WorldState":
        return WorldState(set(self.facts))

    def fingerprint(self) -> Tuple[str, ...]:
        return tuple(sorted(self.facts))


@dataclass
class PlanStep:
    """A single tool call inside a plan."""
    step_id: int
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    expected_effects: List[str] = field(default_factory=list)
    cost: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "args": self.args,
            "rationale": self.rationale,
            "expected_effects": self.expected_effects,
            "cost": self.cost,
        }


@dataclass
class Plan:
    """A complete plan: an ordered sequence of PlanSteps."""
    run_id: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    expected_steps: int = 0
    estimated_cost: float = 0.0
    heuristic_remaining: float = 0.0
    tool_chain: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    source: str = "goap-astar"  # or "llm-direct"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "expected_steps": self.expected_steps,
            "estimated_cost": round(self.estimated_cost, 3),
            "heuristic_remaining": round(self.heuristic_remaining, 3),
            "tool_chain": self.tool_chain,
            "created_at": self.created_at,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Minimal tool description used by the planner."""
    name: str
    description: str
    category: str = "general"
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def keywords(self) -> Set[str]:
        """Cheap keyword set used by the relevance filter."""
        text = (self.name + " " + self.description).lower()
        return {w for w in re.findall(r"[a-z_]{3,}", text)}


# ---------------------------------------------------------------------------
# A* planner
# ---------------------------------------------------------------------------

class GOAPPlanner:
    """A* GOAP planner over the MCP tool graph.

    Search state = a (world_state, steps_so_far) tuple.
    g = steps already used + accumulated cost
    h = LLM-estimated remaining steps to reach the goal
    f = g + h
    """

    MAX_EXPANSION = 25
    DEFAULT_CANDIDATE_LIMIT = 6  # how many tools to consider per expansion

    def __init__(
        self,
        tools: List[ToolSpec],
        llm_client: Optional[LLMClient] = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        max_expansion: int = MAX_EXPANSION,
    ):
        self.tools = {t.name: t for t in tools}
        self.llm = llm_client
        self.candidate_limit = max(1, candidate_limit)
        self.max_expansion = max(1, max_expansion)

    # -- public ----------------------------------------------------------

    async def plan(
        self,
        goal: str,
        initial_state: Optional[WorldState] = None,
        constraints: Optional[List[str]] = None,
    ) -> Plan:
        """Build a plan that aims to satisfy ``goal``."""
        run_id = str(uuid.uuid4())
        state = (initial_state or WorldState()).clone()
        # Estimate upfront how many steps the LLM thinks we'll need.
        try:
            h0 = await self._llm_estimate_remaining(goal, state, [], 0.0)
        except Exception:
            h0 = float(max(1, len(self.tools) // 8))

        # If no LLM available, fall back to a single LLM-direct chain.
        if self.llm is None:
            return await self._llm_direct_plan(goal, run_id, h0)

        # ---- A* search ----
        # frontier entries: (f, tiebreak, g, state_fp, steps_list)
        start_fp = state.fingerprint()
        counter = 0
        frontier: List[Tuple[float, int, float, Tuple[str, ...], List[PlanStep]]] = [
            (h0, counter, 0.0, start_fp, [])
        ]
        visited: Set[Tuple[str, ...]] = set()
        expansions = 0
        best_plan: Optional[Plan] = None
        best_f = float("inf")

        while frontier and expansions < self.max_expansion:
            f, _, g, fp, steps = heapq.heappop(frontier)
            if fp in visited:
                continue
            visited.add(fp)
            expansions += 1

            current_state = WorldState(set(fp))
            # LLM picks the most promising next tools, filtered to known tools.
            try:
                candidates = await self._llm_candidates(
                    goal, current_state, steps, constraints,
                )
            except Exception as e:
                # LLM errored mid-search: degrade to LLM-direct plan.
                return await self._llm_direct_plan(
                    goal, run_id, h0, error=str(e),
                )

            if not candidates:
                # Nothing to try — stop and return whatever we have.
                break

            for cand in candidates:
                tool_name = cand.get("tool", "")
                if tool_name not in self.tools:
                    continue
                if any(s.tool == tool_name for s in steps):
                    # Don't repeat a tool in the same plan
                    continue
                spec = self.tools[tool_name]
                step = PlanStep(
                    step_id=len(steps) + 1,
                    tool=tool_name,
                    args=cand.get("args", {}) or {},
                    rationale=cand.get("rationale", ""),
                    expected_effects=[
                        f"result_available:{tool_name}",
                        f"tool_called:{tool_name}",
                    ],
                    cost=float(cand.get("cost", 1.0)),
                )
                new_state = current_state.clone()
                new_state.add(*step.expected_effects)
                # mark tool_succeeded optimistically; executor will adjust.
                new_state.add(f"tool_succeeded:{tool_name}")

                new_steps = steps + [step]
                new_g = g + step.cost
                try:
                    h_new = await self._llm_estimate_remaining(
                        goal, new_state, new_steps, new_g,
                    )
                except Exception:
                    h_new = max(0.0, h0 - new_g)
                new_f = new_g + h_new

                if new_f < best_f:
                    best_f = new_f

                # Check for goal signal from LLM
                if cand.get("goal_reached"):
                    new_state.add("goal_signal")
                    return Plan(
                        run_id=run_id,
                        goal=goal,
                        steps=new_steps,
                        expected_steps=len(new_steps),
                        estimated_cost=new_g,
                        heuristic_remaining=h_new,
                        tool_chain=[s.tool for s in new_steps],
                        source="goap-astar",
                    )

                new_fp = new_state.fingerprint()
                if new_fp in visited:
                    continue
                counter += 1
                heapq.heappush(
                    frontier,
                    (new_f, counter, new_g, new_fp, new_steps),
                )

            # If the best path so far is already strictly better than the
            # smallest f in the frontier, we can stop and return it.
            if best_plan is None and frontier and best_f < frontier[0][0]:
                pass  # keep expanding — we haven't returned a plan yet

        if not frontier:
            return await self._llm_direct_plan(goal, run_id, h0)

        # Return the best (lowest f) plan we ever popped
        if best_plan is None:
            # pick the lowest-g path in the frontier as a fallback
            _, _, g_min, _, steps_min = min(frontier, key=lambda x: x[2])
            best_plan = Plan(
                run_id=run_id,
                goal=goal,
                steps=steps_min,
                expected_steps=len(steps_min),
                estimated_cost=g_min,
                heuristic_remaining=max(0.0, h0 - g_min),
                tool_chain=[s.tool for s in steps_min],
                source="goap-astar",
            )
        return best_plan

    # -- LLM helpers ----------------------------------------------------

    async def _llm_candidates(
        self,
        goal: str,
        state: WorldState,
        steps: List[PlanStep],
        constraints: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """Ask the LLM for the next 1-3 candidate tool calls."""
        tool_lines = "\n".join(
            f"- {t.name}: {t.description[:120]}"
            for t in self.tools.values()
        )
        step_summary = (
            "\n".join(f"{s.step_id}. {s.tool}({json.dumps(s.args)[:80]})" for s in steps)
            or "(no steps taken yet)"
        )
        constraint_text = (
            "\n".join(f"- {c}" for c in (constraints or [])) or "(none)"
        )
        fact_list = sorted(state.facts) or ["(empty)"]

        prompt = f"""You are an autonomous agent planner. Decide the next 1-3 MCP tool calls
that make progress toward the GOAL below. Choose from the AVAILABLE TOOLS.

GOAL: {goal}

CONSTRAINTS:
{constraint_text}

STEPS ALREADY TAKEN:
{step_summary}

CURRENT WORLD FACTS:
{fact_list}

AVAILABLE TOOLS (name: description):
{tool_lines}

Return a JSON array of 1 to {self.candidate_limit} candidate tool calls.
Each item must have: tool (string), args (object), rationale (short string),
cost (number 0.5-3.0, lower = cheaper), and optionally goal_reached (bool).
If you believe the goal is satisfied, return one step with goal_reached=true.

Reply with ONLY the JSON array, no markdown, no commentary."""

        raw = await self._llm_complete(prompt, max_tokens=700, temperature=0.4)
        return _safe_parse_json_array(raw)

    async def _llm_estimate_remaining(
        self,
        goal: str,
        state: WorldState,
        steps: List[PlanStep],
        g: float,
    ) -> float:
        """Ask the LLM for an estimated number of remaining steps (heuristic h)."""
        step_summary = (
            ", ".join(s.tool for s in steps) or "none"
        )
        prompt = f"""Estimate the remaining number of MCP tool calls needed to reach the GOAL.

GOAL: {goal}
STEPS TAKEN: {step_summary}
FACTS NOW TRUE: {', '.join(sorted(state.facts)) or '(none)'}

Reply with a single JSON object: {{"remaining": <float>}}"""

        raw = await self._llm_complete(prompt, max_tokens=120, temperature=0.1)
        try:
            obj = _safe_parse_json_object(raw)
            val = float(obj.get("remaining", 1.0))
        except Exception:
            val = 1.0
        return max(0.0, val)

    async def _llm_direct_plan(
        self,
        goal: str,
        run_id: str,
        h0: float,
        error: Optional[str] = None,
    ) -> Plan:
        """Fallback: ask the LLM for a single best plan in one shot."""
        if self.llm is None:
            return Plan(
                run_id=run_id, goal=goal, source="empty", tool_chain=[],
            )
        tool_lines = "\n".join(
            f"- {t.name}: {t.description[:100]}" for t in self.tools.values()
        )
        prompt = f"""Plan the best sequence of MCP tool calls to reach the GOAL.

GOAL: {goal}

AVAILABLE TOOLS:
{tool_lines}

Return a JSON array (1-5 items) of steps. Each step:
{{"tool": "<name>", "args": {{...}}, "rationale": "...", "cost": 1.0}}

Reply with ONLY the JSON array."""
        try:
            raw = await self._llm_complete(prompt, max_tokens=900, temperature=0.4)
            items = _safe_parse_json_array(raw)
        except Exception as e:
            items = []
            error = f"{error or ''} | {e}"

        steps: List[PlanStep] = []
        for i, item in enumerate(items[:6]):
            tool = item.get("tool", "")
            if tool not in self.tools:
                continue
            steps.append(PlanStep(
                step_id=i + 1,
                tool=tool,
                args=item.get("args", {}) or {},
                rationale=item.get("rationale", "")[:160],
                expected_effects=[f"tool_called:{tool}", f"result_available:{tool}"],
                cost=float(item.get("cost", 1.0)),
            ))
        return Plan(
            run_id=run_id,
            goal=goal,
            steps=steps,
            expected_steps=len(steps),
            estimated_cost=sum(s.cost for s in steps),
            heuristic_remaining=h0,
            tool_chain=[s.tool for s in steps],
            source="llm-direct",
        )

    async def _llm_complete(self, prompt: str, max_tokens: int, temperature: float) -> str:
        if self.llm is None:
            return "[]"
        resp = await self.llm.complete(
            prompt=prompt,
            system=(
                "You are a precise planning engine. "
                "Respond with valid JSON only, no commentary, no markdown fences."
            ),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.content or ""


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _safe_parse_json_array(text: str) -> List[Dict[str, Any]]:
    """Parse a JSON array from LLM output, robust to extra prose/fences."""
    if not text:
        return []
    text = text.strip()
    # strip code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    # try to find the first [...] block
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _safe_parse_json_object(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {}


# ---------------------------------------------------------------------------
# Convenience: build a ToolSpec list from a ToolRegistry
# ---------------------------------------------------------------------------

def specs_from_registry(registry) -> List[ToolSpec]:
    """Build ToolSpec objects from a graxia_tool.mcp ToolRegistry."""
    out: List[ToolSpec] = []
    for t in registry.list_all():
        out.append(ToolSpec(
            name=t.name,
            description=t.description or "",
            category=t.category,
            input_schema=t.input_schema or {},
        ))
    return out
