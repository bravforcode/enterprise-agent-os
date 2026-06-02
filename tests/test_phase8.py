"""Enterprise Agent OS — Phase 8 Multi-Agent Pattern tests."""
import pytest
import asyncio
from datetime import datetime

from graxia_tool.agents.base import BaseSubAgent, SubAgentResult
from graxia_tool.multi_agent import (
    MultiAgentCoordinator,
    PatternType,
    SharedState,
    AgentMessage,
    MultiAgentResult,
    PipelineCoordinator,
    SupervisorCoordinator,
    ParallelCoordinator,
    HierarchicalCoordinator,
    DebateCoordinator,
    ConsensusCoordinator,
    MarketplaceCoordinator,
    create_coordinator,
)
from graxia_tool.multi_agent.builder import build_coordinator, list_available_agents


# --- Test fixtures ---
class StubAgent(BaseSubAgent):
    """Test agent that echoes or transforms input."""
    __test__ = False

    def __init__(self, name: str, response: str | None = None, transform: bool = False, fail: bool = False):
        super().__init__()
        self.name = name
        self.response = response
        self.transform = transform
        self.fail = fail

    async def execute(self, input_text: str, context: dict | None = None) -> SubAgentResult:
        if self.fail:
            return SubAgentResult(success=False, output=None, error="intentional fail", agent_name=self.name)
        if self.response is not None:
            return SubAgentResult(success=True, output=self.response, agent_name=self.name)
        if self.transform:
            return SubAgentResult(
                success=True,
                output=f"{self.name}:{input_text.upper()}",
                agent_name=self.name,
            )
        return SubAgentResult(success=True, output=f"echo from {self.name}: {input_text}", agent_name=self.name)


# --- Shared state tests ---
class TestSharedState:
    def test_basic_put_get(self):
        s = SharedState()
        s.put("k", "v")
        assert s.get("k") == "v"

    def test_set_output(self):
        s = SharedState()
        s.set_output("result", "final")
        assert s.get("result") == "final"

    def test_add_message(self):
        s = SharedState()
        msg = AgentMessage(sender="a", receiver="b", type=PatternType.PIPELINE, content="hi")
        s.add_message(msg)
        assert len(s.messages) == 1

    def test_snapshot(self):
        s = SharedState()
        s.put("k", "v")
        s.set_output("r", "f")
        snap = s.snapshot()
        assert snap["intermediate"]["k"] == "v"
        assert snap["outputs"]["r"] == "f"
        assert snap["message_count"] == 0


# --- Pipeline tests ---
class TestPipeline:
    @pytest.mark.asyncio
    async def test_basic_pipeline(self):
        agents = {
            "upper": StubAgent("upper", transform=True),
            "lower": StubAgent("lower", transform=True),
        }
        coord = PipelineCoordinator(stages=["upper", "lower"], agents=agents)
        result = await coord.coordinate("hello")
        assert result.success
        assert "UPPER" in str(result.output)
        assert len(result.agent_results) == 2
        assert result.pattern == PatternType.PIPELINE

    @pytest.mark.asyncio
    async def test_pipeline_failure_stops(self):
        agents = {
            "a": StubAgent("a", transform=True),
            "b": StubAgent("b", fail=True),
        }
        coord = PipelineCoordinator(stages=["a", "b"], agents=agents)
        result = await coord.coordinate("test")
        assert not result.success
        assert "b" in (result.error or "")
        # Both stages ran but only "b" failed
        assert len(result.agent_results) == 2
        assert result.agent_results[0].success is True
        assert result.agent_results[1].success is False

    @pytest.mark.asyncio
    async def test_pipeline_missing_agent(self):
        agents = {"a": StubAgent("a")}
        coord = PipelineCoordinator(stages=["a", "missing"], agents=agents)
        result = await coord.coordinate("test")
        # "missing" is silently skipped since _run_agent returns failed result
        # but since the agent "a" runs and returns success, missing is the only stage
        # Actually: stage "missing" will fail
        assert not result.success or "missing" in (result.error or "")


# --- Supervisor tests ---
class TestSupervisor:
    @pytest.mark.asyncio
    async def test_supervisor_no_llm_runs_all(self):
        agents = {
            "coder": StubAgent("coder", "code output"),
            "tester": StubAgent("tester", "test output"),
        }
        coord = SupervisorCoordinator(worker_names=["coder", "tester"], agents=agents)
        result = await coord.coordinate("write code")
        assert result.success
        assert "code output" in str(result.output)
        assert "test output" in str(result.output)
        assert result.metadata["plan"] == ["coder", "tester"]

    @pytest.mark.asyncio
    async def test_supervisor_with_llm(self):
        async def mock_llm(agent_name, prompt):
            if "supervisor" in agent_name.lower() or "synth" in agent_name.lower():
                return '["coder"]'
            return "llm output"

        agents = {"coder": StubAgent("coder", "llm output")}
        coord = SupervisorCoordinator(worker_names=["coder"], agents=agents, llm_call=mock_llm)
        result = await coord.coordinate("test")
        assert result.success
        assert result.metadata["plan"] == ["coder"]


# --- Parallel tests ---
class TestParallel:
    @pytest.mark.asyncio
    async def test_parallel_same_task(self):
        agents = {
            "a": StubAgent("a", "out-a"),
            "b": StubAgent("b", "out-b"),
            "c": StubAgent("c", "out-c"),
        }
        coord = ParallelCoordinator(branches=["a", "b", "c"], agents=agents)
        result = await coord.coordinate("task")
        assert result.success
        assert all(o in str(result.output) for o in ["out-a", "out-b", "out-c"])
        assert len(result.agent_results) == 3

    @pytest.mark.asyncio
    async def test_parallel_different_tasks(self):
        agents = {
            "a": StubAgent("a"),
            "b": StubAgent("b"),
        }
        branches = {"a": "task a", "b": "task b"}
        coord = ParallelCoordinator(branches=branches, agents=agents)
        result = await coord.coordinate("ignored")
        assert result.success
        assert "task a" in str(result.output)
        assert "task b" in str(result.output)

    @pytest.mark.asyncio
    async def test_parallel_with_aggregator(self):
        agents = {
            "a": StubAgent("a", "alpha"),
            "b": StubAgent("b", "beta"),
            "agg": StubAgent("agg", "final-aggregated"),
        }
        coord = ParallelCoordinator(
            branches=["a", "b"], aggregator="agg", agents=agents
        )
        result = await coord.coordinate("task")
        assert result.success
        assert result.output == "final-aggregated"
        assert len(result.agent_results) == 3


# --- Hierarchical tests ---
class TestHierarchical:
    @pytest.mark.asyncio
    async def test_hierarchical_simple(self):
        agents = {
            "root": StubAgent("root", "root output"),
            "child1": StubAgent("child1", "c1 output"),
            "child2": StubAgent("child2", "c2 output"),
        }
        tree = {"root": ["child1", "child2"]}
        coord = HierarchicalCoordinator(tree=tree, root="root", agents=agents)
        result = await coord.coordinate("task")
        assert result.success
        assert "c1 output" in str(result.output)
        assert "c2 output" in str(result.output)

    @pytest.mark.asyncio
    async def test_hierarchical_nested(self):
        agents = {
            "root": StubAgent("root"),
            "sub1": StubAgent("sub1"),
            "leaf1": StubAgent("leaf1", "L1 output"),
            "leaf2": StubAgent("leaf2", "L2 output"),
        }
        tree = {
            "root": ["sub1"],
            "sub1": ["leaf1", "leaf2"],
        }
        coord = HierarchicalCoordinator(tree=tree, root="root", agents=agents)
        result = await coord.coordinate("task")
        assert result.success
        assert "L1 output" in str(result.output)
        assert "L2 output" in str(result.output)


# --- Debate tests ---
class TestDebate:
    @pytest.mark.asyncio
    async def test_debate_no_llm(self):
        agents = {
            "alice": StubAgent("alice", "alice position"),
            "bob": StubAgent("bob", "bob position"),
            "judge": StubAgent("judge", "judge ruling"),
        }
        coord = DebateCoordinator(
            debaters=["alice", "bob"], judge="judge", rounds=1, agents=agents
        )
        result = await coord.coordinate("topic")
        assert result.success
        assert result.output == "judge ruling"
        assert "alice position" in result.metadata["positions"]["alice"]
        assert "bob position" in result.metadata["positions"]["bob"]

    @pytest.mark.asyncio
    async def test_debate_with_llm(self):
        async def mock_llm(agent_name, prompt):
            if "judge" in agent_name:
                return "llm judge ruling"
            return f"position from {agent_name}"

        agents = {
            "a": StubAgent("a"),
            "b": StubAgent("b"),
            "judge": StubAgent("judge", "llm judge ruling"),
        }
        coord = DebateCoordinator(
            debaters=["a", "b"], judge="judge", rounds=2, agents=agents, llm_call=mock_llm
        )
        result = await coord.coordinate("topic")
        assert result.success
        assert result.output == "llm judge ruling"


# --- Consensus tests ---
class TestConsensus:
    @pytest.mark.asyncio
    async def test_consensus_unanimous(self):
        agents = {
            "a": StubAgent("a", "agree"),
            "b": StubAgent("b", "agree"),
            "c": StubAgent("c", "agree"),
        }
        coord = ConsensusCoordinator(voters=["a", "b", "c"], agents=agents)
        result = await coord.coordinate("task")
        assert result.success
        assert result.output == "agree"
        assert result.metadata["agreement"] == 1.0

    @pytest.mark.asyncio
    async def test_consensus_majority(self):
        agents = {
            "a": StubAgent("a", "yes"),
            "b": StubAgent("b", "yes"),
            "c": StubAgent("c", "no"),
        }
        coord = ConsensusCoordinator(voters=["a", "b", "c"], agreement_threshold=0.5, agents=agents)
        result = await coord.coordinate("task")
        assert result.success
        assert result.output == "yes"
        assert result.metadata["agreement"] == 2 / 3

    @pytest.mark.asyncio
    async def test_consensus_no_majority(self):
        agents = {
            "a": StubAgent("a", "x"),
            "b": StubAgent("b", "y"),
            "c": StubAgent("c", "z"),
        }
        coord = ConsensusCoordinator(voters=["a", "b", "c"], agreement_threshold=0.9, agents=agents)
        result = await coord.coordinate("task")
        assert not result.success
        # Top output is whichever got picked by max
        assert result.output in ["x", "y", "z"]


# --- Marketplace tests ---
class TestMarketplace:
    @pytest.mark.asyncio
    async def test_marketplace_first_strategy(self):
        agents = {
            "a": StubAgent("a", "a wins"),
            "b": StubAgent("b", "b wins"),
        }
        coord = MarketplaceCoordinator(workers=["a", "b"], bid_strategy="first", agents=agents)
        result = await coord.coordinate("task")
        assert result.success
        assert result.output == "a wins"
        assert result.metadata["winner"] == "a"

    @pytest.mark.asyncio
    async def test_marketplace_highest_confidence(self):
        agents = {
            "a": StubAgent("a", "a out"),
            "b": StubAgent("b", "b out"),
        }
        coord = MarketplaceCoordinator(workers=["a", "b"], bid_strategy="highest_confidence", agents=agents)
        result = await coord.coordinate("task")
        # Both succeed with confidence 0.5, so first wins
        assert result.success
        assert result.metadata["winner"] == "a"


# --- Factory tests ---
class TestFactory:
    def test_create_pipeline(self):
        agents = {"a": StubAgent("a"), "b": StubAgent("b")}
        c = create_coordinator("pipeline", {"stages": ["a", "b"]}, agents=agents)
        assert isinstance(c, PipelineCoordinator)

    def test_create_supervisor(self):
        agents = {"a": StubAgent("a"), "b": StubAgent("b")}
        c = create_coordinator("supervisor", {"workers": ["a", "b"]}, agents=agents)
        assert isinstance(c, SupervisorCoordinator)

    def test_create_parallel(self):
        agents = {"a": StubAgent("a"), "b": StubAgent("b")}
        c = create_coordinator("parallel", {"branches": ["a", "b"]}, agents=agents)
        assert isinstance(c, ParallelCoordinator)

    def test_create_hierarchical(self):
        agents = {"root": StubAgent("root"), "a": StubAgent("a")}
        c = create_coordinator(
            "hierarchical",
            {"tree": {"root": ["a"]}, "root": "root"},
            agents=agents,
        )
        assert isinstance(c, HierarchicalCoordinator)

    def test_create_debate(self):
        agents = {"a": StubAgent("a"), "b": StubAgent("b"), "judge": StubAgent("judge")}
        c = create_coordinator(
            "debate", {"debaters": ["a", "b"], "judge": "judge"}, agents=agents
        )
        assert isinstance(c, DebateCoordinator)

    def test_create_consensus(self):
        agents = {"a": StubAgent("a"), "b": StubAgent("b")}
        c = create_coordinator("consensus", {"voters": ["a", "b"]}, agents=agents)
        assert isinstance(c, ConsensusCoordinator)

    def test_create_marketplace(self):
        agents = {"a": StubAgent("a"), "b": StubAgent("b")}
        c = create_coordinator("marketplace", {"workers": ["a", "b"]}, agents=agents)
        assert isinstance(c, MarketplaceCoordinator)

    def test_unknown_pattern_raises(self):
        with pytest.raises(ValueError):
            create_coordinator("invalid", {})


# --- Builder tests ---
class TestBuilder:
    def test_list_agents(self):
        agents = list_available_agents()
        assert len(agents) > 0
        assert "coder" in agents

    def test_build_with_registered_agents(self):
        coord = build_coordinator(
            pattern="pipeline",
            config={"stages": ["coder", "tester"]},
        )
        assert isinstance(coord, PipelineCoordinator)
        assert "coder" in coord.agents
        assert "tester" in coord.agents

    def test_build_supervisor(self):
        coord = build_coordinator(
            pattern="supervisor",
            config={"workers": ["coder", "reviewer"]},
        )
        assert isinstance(coord, SupervisorCoordinator)
        assert "coder" in coord.agents


# --- Integration test with sub-agents ---
class TestIntegration:
    @pytest.mark.asyncio
    async def test_real_coder_pipeline(self):
        from graxia_tool.agents.implementations import Coder, Reviewer
        agents = {
            "coder": Coder(),
            "reviewer": Reviewer(),
        }
        coord = PipelineCoordinator(stages=["coder", "reviewer"], agents=agents)
        result = await coord.coordinate("def add(a,b): return a+b")
        assert result.success
        assert len(result.agent_results) == 2
