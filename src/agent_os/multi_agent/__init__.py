"""Multi-agent orchestration patterns.

SOTA 2026 patterns based on:
- Supervisor (Anthropic's research: 90.2% improvement)
- Pipeline (sequential stages)
- Parallel / Fan-out / Fan-in
- Hierarchical (multi-level supervisors)
- Debate (adversarial argumentation)
- Consensus (independent evaluation + vote)
- Marketplace (Contract-Net protocol)

Each pattern is a MultiAgentCoordinator that orchestrates 1+ sub-agents.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..agents.base import BaseSubAgent, SubAgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# Shared types
# ============================================================

class PatternType(str, Enum):
    PIPELINE = "pipeline"
    SUPERVISOR = "supervisor"
    HIERARCHICAL = "hierarchical"
    PARALLEL = "parallel"
    DEBATE = "debate"
    CONSENSUS = "consensus"
    MARKETPLACE = "marketplace"


class MessageType(str, Enum):
    TASK = "task"
    RESULT = "result"
    BROADCAST = "broadcast"
    BID = "bid"
    AWARD = "award"
    CRITIQUE = "critique"
    VOTE = "vote"


@dataclass
class AgentMessage:
    """Message passed between agents."""
    sender: str
    receiver: str  # "*" for broadcast
    type: MessageType
    content: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SharedState:
    """Shared memory for multi-agent coordination.

    Inspired by Blackboard Architecture (Arsanjani pattern catalog).
    All agents read/write to a common state object.
    """
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    intermediate: dict[str, Any] = field(default_factory=dict)
    messages: list[AgentMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def put(self, key: str, value: Any) -> None:
        """Write to intermediate state."""
        self.intermediate[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Read from any state section."""
        if key in self.outputs:
            return self.outputs[key]
        if key in self.intermediate:
            return self.intermediate[key]
        if key in self.inputs:
            return self.inputs[key]
        return default

    def set_output(self, key: str, value: Any) -> None:
        """Commit a value to outputs (final result)."""
        self.outputs[key] = value

    def add_message(self, msg: AgentMessage) -> None:
        """Log a message."""
        self.messages.append(msg)

    def snapshot(self) -> dict[str, Any]:
        """Return serializable snapshot."""
        return {
            "inputs": self.inputs,
            "outputs": self.outputs,
            "intermediate": self.intermediate,
            "message_count": len(self.messages),
        }


@dataclass
class MultiAgentResult:
    """Result of multi-agent run."""
    pattern: PatternType
    success: bool
    output: Any
    state: SharedState
    agent_results: list[SubAgentResult]
    duration_ms: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Base Coordinator
# ============================================================

class MultiAgentCoordinator(ABC):
    """Abstract base for all multi-agent patterns.

    Each pattern subclasses this and implements `coordinate()`.
    """

    pattern: PatternType

    def __init__(
        self,
        agents: dict[str, BaseSubAgent] | None = None,
        llm_call: Callable[[str, str], Awaitable[str]] | None = None,
        max_iterations: int = 10,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.agents: dict[str, BaseSubAgent] = agents or {}
        self.llm_call = llm_call
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds

    def add_agent(self, name: str, agent: BaseSubAgent) -> None:
        """Register an agent."""
        self.agents[name] = agent

    def get_agent(self, name: str) -> BaseSubAgent:
        """Get agent by name."""
        if name not in self.agents:
            raise KeyError(f"Agent {name!r} not registered")
        return self.agents[name]

    @abstractmethod
    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        """Run the pattern. Must be implemented by subclass."""
        raise NotImplementedError

    async def _run_agent(
        self,
        agent_name: str,
        input_text: str,
        context: dict[str, Any] | None = None,
    ) -> SubAgentResult:
        """Run a single agent with timing."""
        if agent_name not in self.agents:
            return SubAgentResult(
                success=False,
                output=None,
                error=f"Agent {agent_name!r} not found",
                agent_name=agent_name,
            )
        agent = self.agents[agent_name]
        # Inject LLM call into agent if it has the slot
        if self.llm_call is not None and hasattr(agent, "llm_func"):
            agent.llm_func = self.llm_call
        return await agent.run(input_text, context=context)


# ============================================================
# 1. Pipeline — Sequential
# ============================================================

class PipelineCoordinator(MultiAgentCoordinator):
    """Sequential chain: A → B → C → ...

    Each stage's output becomes next stage's input.
    Use for: ETL, linear workflows, code review pipelines.
    """

    pattern = PatternType.PIPELINE

    def __init__(
        self,
        stages: list[str],  # ordered agent names
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.stages = stages

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []
        current_input = task

        try:
            for stage in self.stages:
                logger.info("pipeline.stage", stage=stage, input_len=len(current_input))
                result = await self._run_agent(stage, current_input, context=context)
                results.append(result)
                state.add_message(AgentMessage(
                    sender=stage,
                    receiver="next",
                    type=MessageType.RESULT,
                    content=result.output,
                ))
                if not result.success:
                    return MultiAgentResult(
                        pattern=self.pattern,
                        success=False,
                        output=None,
                        state=state,
                        agent_results=results,
                        duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                        error=f"Stage {stage!r} failed: {result.error}",
                    )
                current_input = str(result.output)
                state.put(f"{stage}_output", result.output)

            state.set_output("result", current_input)
            return MultiAgentResult(
                pattern=self.pattern,
                success=True,
                output=current_input,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# 2. Supervisor — Orchestrator + workers
# ============================================================

class SupervisorCoordinator(MultiAgentCoordinator):
    """Central orchestrator delegates to specialist workers.

    The supervisor (an LLM call) analyzes the task, decides which agents
    to invoke, and synthesizes results. The 2026 production default.
    """

    pattern = PatternType.SUPERVISOR

    def __init__(
        self,
        worker_names: list[str],
        supervisor_prompt_template: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.worker_names = worker_names
        self.supervisor_prompt_template = supervisor_prompt_template or (
            "You are a supervisor. Given the task and the available workers, "
            "decide which worker(s) to invoke.\n\n"
            "Task: {task}\n"
            "Workers: {workers}\n\n"
            "Respond with a JSON list of worker names to invoke in order, e.g. [\"coder\", \"tester\"]."
        )

    async def _plan(self, task: str) -> list[str]:
        """Decide which workers to invoke. Falls back to all if no LLM."""
        if self.llm_call is None:
            return self.worker_names
        prompt = self.supervisor_prompt_template.format(
            task=task, workers=self.worker_names
        )
        try:
            response = await self.llm_call("supervisor", prompt)
            import json
            import re
            match = re.search(r"\[.*?\]", response, re.DOTALL)
            if match:
                plan = json.loads(match.group(0))
                if isinstance(plan, list):
                    return [p for p in plan if p in self.worker_names]
        except Exception as e:
            logger.warning("supervisor.plan_failed", error=str(e))
        return self.worker_names

    async def _synthesize(
        self, task: str, worker_outputs: dict[str, Any]
    ) -> str:
        """Combine worker outputs. If no LLM, concatenate."""
        if self.llm_call is None:
            return "\n\n".join(
                f"[{name}]: {output}" for name, output in worker_outputs.items()
            )
        prompt = (
            f"Synthesize the following worker outputs into a final answer for the task.\n\n"
            f"Task: {task}\n\n"
            f"Outputs:\n" +
            "\n".join(f"- {name}: {out}" for name, out in worker_outputs.items())
        )
        return await self.llm_call("synthesizer", prompt)

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []
        worker_outputs: dict[str, Any] = {}

        try:
            plan = await self._plan(task)
            state.put("plan", plan)
            logger.info("supervisor.plan", plan=plan)

            for worker in plan:
                result = await self._run_agent(worker, task, context=context)
                results.append(result)
                state.add_message(AgentMessage(
                    sender="supervisor",
                    receiver=worker,
                    type=MessageType.TASK,
                    content=task,
                ))
                state.add_message(AgentMessage(
                    sender=worker,
                    receiver="supervisor",
                    type=MessageType.RESULT,
                    content=result.output,
                ))
                if result.success:
                    worker_outputs[worker] = result.output
                    state.put(f"{worker}_output", result.output)

            final = await self._synthesize(task, worker_outputs)
            state.set_output("result", final)
            return MultiAgentResult(
                pattern=self.pattern,
                success=True,
                output=final,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                metadata={"plan": plan},
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# 3. Parallel — Fan-out / Fan-in
# ============================================================

class ParallelCoordinator(MultiAgentCoordinator):
    """Run multiple agents concurrently, then aggregate.

    Use for: independent research, multi-perspective analysis.
    ~3-10x latency reduction vs sequential when tasks are independent.
    """

    pattern = PatternType.PARALLEL

    def __init__(
        self,
        branches: list[str] | dict[str, str],
        aggregator: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # branches can be list (same task) or dict (different task per branch)
        self.branches = branches
        self.aggregator = aggregator  # agent name to aggregate, or None

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []

        try:
            if isinstance(self.branches, list):
                # Same task to all
                coros = [
                    self._run_agent(name, task, context=context)
                    for name in self.branches
                ]
                branch_results = await asyncio.gather(*coros, return_exceptions=False)
            else:
                # Different task per branch
                coros = [
                    self._run_agent(name, sub_task, context=context)
                    for name, sub_task in self.branches.items()
                ]
                branch_results = await asyncio.gather(*coros, return_exceptions=False)

            for i, r in enumerate(branch_results):
                results.append(r)
                if isinstance(self.branches, list):
                    name = self.branches[i]
                else:
                    name = list(self.branches.keys())[i]
                state.add_message(AgentMessage(
                    sender=name,
                    receiver="aggregator",
                    type=MessageType.RESULT,
                    content=r.output,
                ))
                state.put(f"{name}_output", r.output)

            # Aggregate
            if self.aggregator and self.aggregator in self.agents:
                agg_input = "\n\n".join(
                    f"[{name}]: {r.output}" for name, r in zip(
                        self.branches if isinstance(self.branches, list) else self.branches.keys(),
                        branch_results,
                    )
                )
                agg_result = await self._run_agent(
                    self.aggregator, agg_input, context=context
                )
                results.append(agg_result)
                final = agg_result.output
            else:
                # Default: concatenate successful outputs
                final = "\n\n".join(
                    f"[{name}]: {r.output}" for name, r in zip(
                        self.branches if isinstance(self.branches, list) else self.branches.keys(),
                        branch_results,
                    )
                )

            state.set_output("result", final)
            return MultiAgentResult(
                pattern=self.pattern,
                success=True,
                output=final,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# 4. Hierarchical — Multi-level supervisors
# ============================================================

class HierarchicalCoordinator(MultiAgentCoordinator):
    """Tree of supervisors. Top delegates to sub-supervisors.

    Use for: large projects with distinct domains (research, engineering, QA).
    Each layer operates at its own level of abstraction.
    """

    pattern = PatternType.HIERARCHICAL

    def __init__(
        self,
        tree: dict[str, list[str]],  # supervisor_name -> [worker_names]
        root: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.tree = tree
        self.root = root

    async def _run_subtree(
        self,
        supervisor: str,
        task: str,
        context: dict[str, Any] | None,
        state: SharedState,
        results: list[SubAgentResult],
    ) -> Any:
        """Recursively run a supervisor's subtree."""
        if supervisor not in self.agents:
            # If supervisor is not a registered agent, treat as just a routing label
            if supervisor in self.tree:
                children = self.tree[supervisor]
            else:
                return f"[unavailable: {supervisor}]"
        else:
            children = self.tree.get(supervisor, [])

        if not children:
            # Leaf — run as agent
            result = await self._run_agent(supervisor, task, context=context)
            results.append(result)
            return result.output

        # Internal — coordinate children
        outputs = []
        for child in children:
            if child in self.tree:
                out = await self._run_subtree(child, task, context, state, results)
            else:
                result = await self._run_agent(child, task, context=context)
                results.append(result)
                out = result.output
            outputs.append(f"[{child}]: {out}")
        return "\n\n".join(outputs)

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []

        try:
            final = await self._run_subtree(self.root, task, context, state, results)
            state.set_output("result", final)
            return MultiAgentResult(
                pattern=self.pattern,
                success=True,
                output=final,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# 5. Debate — Adversarial argumentation
# ============================================================

class DebateCoordinator(MultiAgentCoordinator):
    """Two+ agents argue opposing positions; judge arbitrates.

    Each round, agents see other agents' reasoning and refine.
    Higher cost (~2.5x single-agent) but better factuality.
    Use for: high-stakes decisions, complex reasoning.
    """

    pattern = PatternType.DEBATE

    def __init__(
        self,
        debaters: list[str],
        judge: str,
        rounds: int = 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.debaters = debaters
        self.judge = judge
        self.rounds = rounds

    async def _get_position(
        self,
        debater: str,
        task: str,
        other_positions: list[tuple[str, str]],
        round_num: int,
    ) -> str:
        """Get debater's position, optionally informed by others."""
        if round_num == 0 or not other_positions:
            return await self._get_initial_position(debater, task)
        # Refine based on other positions
        prompt = (
            f"Topic: {task}\n\n"
            f"Other positions:\n" +
            "\n".join(f"- {name}: {pos}" for name, pos in other_positions) +
            f"\n\nRefine your position considering the above. You are {debater}."
        )
        if self.llm_call:
            return await self.llm_call(debater, prompt)
        return f"[{debater} round {round_num + 1}] Refined position based on feedback."

    async def _get_initial_position(self, debater: str, task: str) -> str:
        if self.llm_call:
            return await self.llm_call(debater, f"State your position on: {task}")
        # Use registered agent as fallback
        if debater in self.agents:
            result = await self._run_agent(debater, f"State your position on: {task}")
            return str(result.output) if result.output else f"[{debater}] position"
        return f"[{debater}] Initial position on: {task}"

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []
        positions: dict[str, str] = {}

        try:
            for round_num in range(self.rounds):
                logger.info("debate.round", round=round_num + 1)
                other = [(n, p) for n, p in positions.items()]
                for debater in self.debaters:
                    pos = await self._get_position(
                        debater, task, other, round_num
                    )
                    positions[debater] = pos
                    state.add_message(AgentMessage(
                        sender=debater,
                        receiver="all",
                        type=MessageType.BROADCAST,
                        content=pos,
                        metadata={"round": round_num + 1},
                    ))

            # Judge synthesizes
            debate_summary = "\n\n".join(
                f"[{name}]: {pos}" for name, pos in positions.items()
            )
            judge_result = await self._run_agent(self.judge, debate_summary, context=context)
            results.append(judge_result)
            state.set_output("result", judge_result.output)
            state.put("positions", positions)

            return MultiAgentResult(
                pattern=self.pattern,
                success=judge_result.success,
                output=judge_result.output,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                metadata={"rounds": self.rounds, "positions": positions},
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# 6. Consensus — Independent evaluation + vote
# ============================================================

class ConsensusCoordinator(MultiAgentCoordinator):
    """Multiple agents independently answer; vote or agree.

    Use for: high-stakes outputs where disagreement is unacceptable.
    Cheaper than debate (no back-and-forth).
    """

    pattern = PatternType.CONSENSUS

    def __init__(
        self,
        voters: list[str],
        agreement_threshold: float = 0.5,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.voters = voters
        self.agreement_threshold = agreement_threshold

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []

        try:
            # Fan out: all voters answer independently
            coros = [self._run_agent(v, task, context=context) for v in self.voters]
            voter_results = await asyncio.gather(*coros)
            results.extend(voter_results)

            outputs = [r.output for r in voter_results if r.success]
            votes: dict[str, int] = {}
            for out in outputs:
                out_str = str(out)
                votes[out_str] = votes.get(out_str, 0) + 1

            # Find majority
            if not votes:
                return MultiAgentResult(
                    pattern=self.pattern,
                    success=False,
                    output=None,
                    state=state,
                    agent_results=results,
                    duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                    error="All voters failed",
                )

            top_output, top_count = max(votes.items(), key=lambda x: x[1])
            agreement = top_count / len(outputs)
            success = agreement >= self.agreement_threshold

            state.put("votes", votes)
            state.put("agreement", agreement)
            state.set_output("result", top_output)

            return MultiAgentResult(
                pattern=self.pattern,
                success=success,
                output=top_output,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                metadata={"agreement": agreement, "votes": votes},
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# 7. Marketplace — Contract-Net protocol
# ============================================================

class MarketplaceCoordinator(MultiAgentCoordinator):
    """Contract-Net: agents bid on tasks, best bid wins.

    1. Manager announces task
    2. Workers bid with cost/quality/confidence
    3. Manager awards to winner
    4. Winner executes

    Use for: dynamic task allocation, cost optimization.
    """

    pattern = PatternType.MARKETPLACE

    def __init__(
        self,
        workers: list[str],
        bid_strategy: str = "first",  # "first", "lowest_cost", "highest_confidence"
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.workers = workers
        self.bid_strategy = bid_strategy

    async def _collect_bids(
        self,
        task: str,
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Collect bids from all workers."""
        bids = []
        for worker in self.workers:
            # In a real impl, workers would return cost/quality/confidence
            # Here we simulate with a single round-trip
            result = await self._run_agent(worker, f"BID: {task}", context=context)
            bid = {
                "worker": worker,
                "cost": 1.0,  # placeholder
                "confidence": 0.5 if result.success else 0.0,
                "response": result.output,
            }
            bids.append(bid)
        return bids

    def _select_winner(self, bids: list[dict[str, Any]]) -> dict[str, Any]:
        """Select best bid per strategy."""
        if not bids:
            raise ValueError("No bids received")
        if self.bid_strategy == "first":
            return bids[0]
        if self.bid_strategy == "lowest_cost":
            return min(bids, key=lambda b: b["cost"])
        if self.bid_strategy == "highest_confidence":
            return max(bids, key=lambda b: b["confidence"])
        return bids[0]

    async def coordinate(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> MultiAgentResult:
        start = datetime.utcnow()
        state = SharedState(inputs={"task": task}, metadata={"context": context or {}})
        results: list[SubAgentResult] = []

        try:
            bids = await self._collect_bids(task, context)
            state.put("bids", bids)
            state.add_message(AgentMessage(
                sender="manager",
                receiver="*",
                type=MessageType.BROADCAST,
                content=f"Task announced: {task}",
            ))
            for bid in bids:
                state.add_message(AgentMessage(
                    sender=bid["worker"],
                    receiver="manager",
                    type=MessageType.BID,
                    content=bid,
                ))

            winner = self._select_winner(bids)
            state.put("winner", winner)
            state.add_message(AgentMessage(
                sender="manager",
                receiver=winner["worker"],
                type=MessageType.AWARD,
                content=task,
            ))

            # Winner executes
            execution = await self._run_agent(winner["worker"], task, context=context)
            results.append(execution)
            state.set_output("result", execution.output)

            return MultiAgentResult(
                pattern=self.pattern,
                success=execution.success,
                output=execution.output,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                metadata={"winner": winner["worker"], "bids_count": len(bids)},
            )
        except Exception as e:
            return MultiAgentResult(
                pattern=self.pattern,
                success=False,
                output=None,
                state=state,
                agent_results=results,
                duration_ms=(datetime.utcnow() - start).total_seconds() * 1000,
                error=str(e),
            )


# ============================================================
# Factory
# ============================================================

def create_coordinator(
    pattern: PatternType | str,
    config: dict[str, Any],
    agents: dict[str, BaseSubAgent] | None = None,
    **kwargs: Any,
) -> MultiAgentCoordinator:
    """Factory for coordinators.

    Args:
        pattern: One of PatternType values
        config: Pattern-specific config:
            - pipeline: {"stages": ["agent1", "agent2"]}
            - supervisor: {"workers": ["a", "b", "c"]}
            - parallel: {"branches": ["a", "b"]} or {"branches": {"a": "task1", "b": "task2"}}
            - hierarchical: {"tree": {"root": ["child1", "child2"]}, "root": "root"}
            - debate: {"debaters": ["a", "b"], "judge": "judge", "rounds": 2}
            - consensus: {"voters": ["a", "b", "c"], "threshold": 0.5}
            - marketplace: {"workers": ["a", "b"], "strategy": "first"}
        agents: Dict of registered agents
    """
    if isinstance(pattern, str):
        pattern = PatternType(pattern)

    if pattern == PatternType.PIPELINE:
        return PipelineCoordinator(stages=config["stages"], agents=agents, **kwargs)
    if pattern == PatternType.SUPERVISOR:
        return SupervisorCoordinator(worker_names=config["workers"], agents=agents, **kwargs)
    if pattern == PatternType.PARALLEL:
        return ParallelCoordinator(
            branches=config["branches"],
            aggregator=config.get("aggregator"),
            agents=agents,
            **kwargs,
        )
    if pattern == PatternType.HIERARCHICAL:
        return HierarchicalCoordinator(
            tree=config["tree"],
            root=config["root"],
            agents=agents,
            **kwargs,
        )
    if pattern == PatternType.DEBATE:
        return DebateCoordinator(
            debaters=config["debaters"],
            judge=config["judge"],
            rounds=config.get("rounds", 2),
            agents=agents,
            **kwargs,
        )
    if pattern == PatternType.CONSENSUS:
        return ConsensusCoordinator(
            voters=config["voters"],
            agreement_threshold=config.get("threshold", 0.5),
            agents=agents,
            **kwargs,
        )
    if pattern == PatternType.MARKETPLACE:
        return MarketplaceCoordinator(
            workers=config["workers"],
            bid_strategy=config.get("strategy", "first"),
            agents=agents,
            **kwargs,
        )
    raise ValueError(f"Unknown pattern: {pattern}")
