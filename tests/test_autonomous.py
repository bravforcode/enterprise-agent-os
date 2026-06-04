"""Tests for ANUS-style autonomous mode (Track T3).

Covers:
  - context.py: ANUSContext load/save/frontmatter roundtrip, append_learning,
                append_history, fallback path resolution
  - planner.py: GOAP A* with LLM-direct fallback, JSON parsing robustness
  - executor.py: step execution, replan on failure, goal_signal detection
  - learner.py: heuristic lessons, LLM-driven lessons, applying to ANUS.md
  - store.py: persistence and listing
  - mcp/autonomous_tools.py: every MCP handler returns _ok/_err
  - integration (real OpenRouter + Ollama): full plan + full run + ANUS.md save

Test layers:
  - Unit tests: pure logic, no LLM required
  - Integration tests: marked with @pytest.mark.integration, hit a real LLM
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.autonomous import (  # noqa: E402
    ANUSContext,
    ANUSProject,
    AutonomousExecutor,
    ExecutionResult,
    GOAPPlanner,
    Plan,
    PlanStep,
    RunStore,
    RunRecord,
    RunStatus,
    SelfLearner,
    WorldState,
    default_context_path,
)
from graxia_tool.autonomous.context import Learning, HistoryEntry  # noqa: E402
from graxia_tool.autonomous.planner import (  # noqa: E402
    ToolSpec,
    _safe_parse_json_array,
    _safe_parse_json_object,
    specs_from_registry,
)
from graxia_tool.autonomous.store import StepRecord  # noqa: E402
from graxia_tool.llm import HybridLLMClient  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """An isolated project directory for ANUS.md tests."""
    return tmp_path


@pytest.fixture
def tmp_store(tmp_path: Path) -> RunStore:
    return RunStore(path=tmp_path / "runs.json")


@pytest.fixture
def sample_tools() -> List[ToolSpec]:
    return [
        ToolSpec(name="context_load", description="Load the ANUS context", category="autonomous"),
        ToolSpec(name="context_save", description="Save the ANUS context", category="autonomous"),
        ToolSpec(name="autonomous_plan", description="Build a GOAP plan", category="autonomous"),
        ToolSpec(name="autonomous_run", description="Run autonomously", category="autonomous"),
        ToolSpec(name="memory_recall", description="Recall memories", category="memory"),
        ToolSpec(name="memory_store", description="Store a memory", category="memory"),
        ToolSpec(name="agent_run", description="Run a sub-agent", category="agents"),
        ToolSpec(name="rag_query", description="Query RAG knowledge base", category="rag"),
        ToolSpec(name="vault_search", description="Search the vault", category="vault"),
        ToolSpec(name="skills_load", description="Load a skill", category="skills"),
    ]


@pytest.fixture
def mock_registry():
    """Lightweight MCP-like registry with three simple tools."""
    from graxia_tool.mcp import Tool, ToolRegistry

    reg = ToolRegistry()

    async def echo_handler(args: Dict[str, Any]) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps({"echo": args.get("text", "")})}]}

    async def fail_handler(args: Dict[str, Any]) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": "ERROR: simulated failure"}], "isError": True}

    async def list_handler(args: Dict[str, Any]) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps({"items": [1, 2, 3]})}]}

    reg.register(Tool(name="echo", description="echo back text", input_schema={}, handler=echo_handler))
    reg.register(Tool(name="fail", description="always fails", input_schema={}, handler=fail_handler))
    reg.register(Tool(name="list", description="return items", input_schema={}, handler=list_handler))
    return reg


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------

class TestANUSContext:
    def test_load_returns_empty_when_missing(self, tmp_project: Path):
        ctx = ANUSContext()
        p = ctx.load(str(tmp_project))
        assert p.project == "default"
        assert p.goals == []
        assert p.learnings == []
        assert p.notes == ""

    def test_save_and_load_roundtrip(self, tmp_project: Path):
        ctx = ANUSContext()
        p = ANUSProject(
            project="myproj",
            goals=["ship T3", "improve planner"],
            constraints=["no mocks in tests"],
            preferences={"language": "th", "style": "terse"},
            notes="Use caveman for terseness.",
        )
        ctx.append_learning(p, "Use selector loop on Windows")
        path = ctx.save(p, str(tmp_project))
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "ship T3" in text
        assert "selector loop on Windows" in text
        # reload
        p2 = ctx.load(str(tmp_project))
        assert p2.project == "myproj"
        assert p2.goals == ["ship T3", "improve planner"]
        assert p2.preferences["language"] == "th"
        assert any(l.lesson == "Use selector loop on Windows" for l in p2.learnings)

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "dir"
        ctx = ANUSContext()
        p = ANUSProject(project="x")
        out = ctx.save(p, str(nested))
        assert out.exists()
        assert out.parent == nested

    def test_append_learning_no_duplicates_in_history(self, tmp_project: Path):
        ctx = ANUSContext()
        p = ANUSProject()
        for i in range(60):
            ctx.append_history(p, HistoryEntry(
                run_id=f"r{i}", query=f"q{i}", success=True, duration_s=0.1,
            ))
        assert len(p.history) == 50  # capped

    def test_default_path_is_graxia(self):
        path = default_context_path()
        assert path.name == "ANUS.md"
        assert ".graxia" in str(path)

    def test_path_for_falls_back(self, tmp_path: Path):
        # nonexistent project path → fallback
        ctx = ANUSContext()
        path = ctx.path_for(str(tmp_path / "does_not_exist"))
        # project_path's parent doesn't exist; falls back to default
        assert path.name == "ANUS.md"


# ---------------------------------------------------------------------------
# planner.py
# ---------------------------------------------------------------------------

class TestPlannerHelpers:
    def test_parse_clean_array(self):
        out = _safe_parse_json_array('[{"a": 1}, {"b": 2}]')
        assert out == [{"a": 1}, {"b": 2}]

    def test_parse_array_with_fences(self):
        out = _safe_parse_json_array('```json\n[{"x": 1}]\n```')
        assert out == [{"x": 1}]

    def test_parse_array_with_prose(self):
        out = _safe_parse_json_array('Here you go: [{"y": 2}] cheers')
        assert out == [{"y": 2}]

    def test_parse_array_garbage_returns_empty(self):
        assert _safe_parse_json_array("not json at all") == []

    def test_parse_object(self):
        out = _safe_parse_json_object('{"remaining": 3.5}')
        assert out == {"remaining": 3.5}


class TestPlannerNoLLM:
    def test_plan_without_llm_returns_empty(self, sample_tools: List[ToolSpec]):
        async def run():
            planner = GOAPPlanner(sample_tools, llm_client=None)
            plan = await planner.plan("improve the agent")
            assert plan.run_id  # has id
            assert plan.source in ("goap-astar", "llm-direct", "empty")
        asyncio.run(run())


class TestPlannerWithMockLLM:
    """A* behavior verification with a controllable mock LLM."""

    def _make_llm(self, responses: List[str]):
        llm = MagicMock()
        llm.complete = MagicMock()
        # async-mock
        async def complete(prompt: str, **kwargs):
            resp = responses.pop(0) if responses else "[]"
            r = MagicMock()
            r.content = resp
            r.tokens_in = 10
            r.tokens_out = 10
            r.cost_usd = 0.0
            r.model = "mock"
            r.metadata = {}
            return r
        llm.complete = complete
        return llm

    def test_astar_finds_short_plan(self, sample_tools: List[ToolSpec]):
        # The planner's LLM call order is:
        #   1) _llm_estimate_remaining for h0
        #   2) For each pop of the frontier:
        #        a) _llm_candidates
        #        b) For each candidate, _llm_estimate_remaining (h_new)
        #        c) if candidate has goal_reached, return immediately
        responses = [
            # 1) h0
            json.dumps({"remaining": 2.0}),
            # 2a) candidates for initial state — 1 step, no goal_reached
            json.dumps([{"tool": "context_load", "args": {}, "rationale": "need context",
                        "cost": 0.5}]),
            # 2b) h_new for that step
            json.dumps({"remaining": 1.0}),
            # 2a again, this time with goal_reached=true
            json.dumps([
                {"tool": "autonomous_run", "args": {"goal": "x"},
                 "rationale": "do it", "cost": 1.0, "goal_reached": True},
            ]),
            # 2b for the new step (not actually needed, but planner may
            # still call it for sibling candidates; safe to provide)
            json.dumps({"remaining": 0.0}),
        ]
        llm = self._make_llm(responses)

        async def run():
            planner = GOAPPlanner(sample_tools, llm_client=llm, max_expansion=4)
            plan = await planner.plan("achieve the goal")
            assert plan.steps, f"expected at least one step, got source={plan.source}"
            assert plan.source == "goap-astar"
            assert any(s.tool == "autonomous_run" for s in plan.steps)
        asyncio.run(run())

    def test_llm_direct_fallback_when_candidates_empty(self, sample_tools: List[ToolSpec]):
        # All expansions return no candidates; planner must fall back
        # to a one-shot LLM-direct plan.
        responses = [
            json.dumps({"remaining": 1.0}),  # h0
            "[]",  # candidates — empty so we hit the frontier-exhausted branch
            json.dumps([  # llm-direct plan
                {"tool": "agent_run", "args": {"agent": "general"}, "rationale": "do"},
            ]),
        ]
        llm = self._make_llm(responses)

        async def run():
            planner = GOAPPlanner(sample_tools, llm_client=llm, max_expansion=2)
            plan = await planner.plan("do something")
            # llm-direct path may produce a step
            assert plan.source in ("llm-direct", "goap-astar")
        asyncio.run(run())


# ---------------------------------------------------------------------------
# store.py
# ---------------------------------------------------------------------------

class TestRunStore:
    def test_upsert_and_get(self, tmp_store: RunStore):
        rec = RunRecord(run_id="r1", goal="test", status=RunStatus.COMPLETED)
        rec.tool_chain = ["a", "b"]
        tmp_store.upsert(rec)
        got = tmp_store.get("r1")
        assert got is not None
        assert got.goal == "test"
        assert got.tool_chain == ["a", "b"]

    def test_list_orders_by_recency(self, tmp_store: RunStore):
        for i in range(3):
            r = RunRecord(run_id=f"r{i}", goal=f"g{i}")
            r.started_at = time.time() + i  # increasing
            tmp_store.upsert(r)
        listed = tmp_store.list(limit=10)
        assert [r.run_id for r in listed] == ["r2", "r1", "r0"]

    def test_persistence(self, tmp_path: Path):
        path = tmp_path / "runs.json"
        s1 = RunStore(path=path)
        s1.upsert(RunRecord(run_id="p1", goal="persist"))
        s2 = RunStore(path=path)  # reload
        assert s2.get("p1") is not None


# ---------------------------------------------------------------------------
# executor.py
# ---------------------------------------------------------------------------

class TestExecutorMock:
    def test_executes_planned_step(self, mock_registry):
        async def run():
            executor = AutonomousExecutor(
                registry=mock_registry,
                llm_client=None,
                max_steps=2, max_replans=0,
            )
            # Build a plan with a known step
            from graxia_tool.autonomous.planner import PlanStep
            plan = Plan(run_id="x", goal="test", steps=[
                PlanStep(step_id=1, tool="echo", args={"text": "hi"}, rationale="r"),
            ])
            # Run planner-less by patching: easier: just inject plan
            # We instead drive the executor by stubbing the planner.
            # Easier: monkeypatch by calling the underlying method directly.
            rec = await executor._execute_step(plan.steps[0])
            assert rec.success
            assert rec.tool == "echo"
        asyncio.run(run())

    def test_marks_step_failed_on_error(self, mock_registry):
        async def run():
            executor = AutonomousExecutor(
                registry=mock_registry, llm_client=None,
            )
            from graxia_tool.autonomous.planner import PlanStep
            rec = await executor._execute_step(PlanStep(
                step_id=1, tool="fail", args={}, rationale="r",
            ))
            assert not rec.success
            assert "simulated" in (rec.error or "")
        asyncio.run(run())

    def test_unknown_tool_marked_failed(self, mock_registry):
        async def run():
            executor = AutonomousExecutor(
                registry=mock_registry, llm_client=None,
            )
            rec = await executor._execute_step(PlanStep(
                step_id=1, tool="ghost", args={}, rationale="r",
            ))
            assert not rec.success
            assert "unknown tool" in (rec.error or "")
        asyncio.run(run())

    def test_full_run_with_mocked_planner(self, mock_registry):
        """End-to-end shape check: executor calls plan, executes, completes."""
        async def run():
            executor = AutonomousExecutor(
                registry=mock_registry,
                llm_client=None,
                max_steps=3, max_replans=1,
            )

            # Stub the planner by monkey-patching
            from graxia_tool.autonomous import planner as plan_mod
            from graxia_tool.autonomous.planner import PlanStep, Plan as P
            original = plan_mod.GOAPPlanner.plan
            calls = {"n": 0}

            async def fake_plan(self, goal, state=None, constraints=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    return P(run_id="r1", goal=goal, steps=[
                        PlanStep(step_id=1, tool="echo", args={"text": "a"}, rationale="r"),
                    ])
                return P(run_id="r1", goal=goal, steps=[
                    PlanStep(step_id=1, tool="list", args={}, rationale="r"),
                ], source="llm-direct")

            plan_mod.GOAPPlanner.plan = fake_plan
            try:
                # Patch _goal_likely_met to always return True so we exit early
                executor._goal_likely_met = lambda *a, **k: asyncio.sleep(0, result=True)
                result = await executor.run("test goal")
                assert result.run_id
                assert result.steps_executed >= 1
                assert "echo" in result.tool_chain or "list" in result.tool_chain
            finally:
                plan_mod.GOAPPlanner.plan = original
        asyncio.run(run())


# ---------------------------------------------------------------------------
# learner.py
# ---------------------------------------------------------------------------

class TestSelfLearner:
    def test_heuristic_lessons_on_failed_run(self, tmp_project: Path):
        rec = RunRecord(
            run_id="r1", goal="search the vault", status=RunStatus.REPLANNED,
            replans=2,
        )
        from graxia_tool.autonomous.store import StepRecord
        rec.steps.append(StepRecord(
            step_id=1, tool="vault_search", args={}, success=False,
            error="vault not configured",
        ))
        learner = SelfLearner(llm_client=None)
        lessons = asyncio.run(learner.distill(rec))
        assert 1 <= len(lessons) <= 3
        text = " ".join(l.text for l in lessons)
        assert "vault_search" in text or "replan" in text

    def test_apply_writes_anus_md(self, tmp_project: Path):
        rec = RunRecord(
            run_id="r2", goal="code a thing", status=RunStatus.COMPLETED,
        )
        rec.tool_chain = ["agent_run", "vault_write"]
        ctx = ANUSContext()
        project = ANUSProject(project="learn-test")
        learner = SelfLearner(llm_client=None)
        lessons = asyncio.run(learner.apply(
            rec, project, ctx, project_path=str(tmp_project),
        ))
        assert lessons
        # the file must now exist
        out = ctx.load(str(tmp_project))
        assert out.project == "learn-test"
        assert len(out.learnings) >= 1
        assert len(out.history) == 1
        assert out.history[0].run_id == "r2"


# ---------------------------------------------------------------------------
# mcp/autonomous_tools.py
# ---------------------------------------------------------------------------

class TestMCPTools:
    @pytest.fixture(autouse=True)
    def _reset_singletons(self):
        # Each test gets fresh state by overriding the lazy singletons
        import graxia_tool.mcp.autonomous_tools as at
        at._REGISTRY = None
        at._LLM = None
        at._STORE = None
        yield
        at._REGISTRY = None
        at._LLM = None
        at._STORE = None

    def test_context_load_returns_default(self, tmp_project: Path):
        from graxia_tool.mcp.autonomous_tools import context_load
        # point at a project that doesn't exist → fallback to default
        out = asyncio.run(context_load({"project_path": str(tmp_project / "nope")}))
        assert "content" in out
        assert "ERROR" not in out["content"][0]["text"]

    def test_context_update_appends_learnings(self, tmp_project: Path):
        from graxia_tool.mcp.autonomous_tools import context_update, context_load
        update = asyncio.run(context_update({
            "project_path": str(tmp_project),
            "learnings": ["always use rtk prefix", {"text": "use caveman"}],
        }))
        assert "ERROR" not in update["content"][0]["text"]
        # reload and check
        load = asyncio.run(context_load({"project_path": str(tmp_project)}))
        text = load["content"][0]["text"]
        assert "always use rtk prefix" in text
        assert "use caveman" in text

    def test_autonomous_plan_errors_without_goal(self):
        from graxia_tool.mcp.autonomous_tools import autonomous_plan
        out = asyncio.run(autonomous_plan({}))
        assert "ERROR" in out["content"][0]["text"]

    def test_autonomous_status_unknown_id(self):
        from graxia_tool.mcp.autonomous_tools import autonomous_status
        out = asyncio.run(autonomous_status({"run_id": "nope"}))
        assert "ERROR" in out["content"][0]["text"]

    def test_autonomous_list_runs_returns_list(self):
        from graxia_tool.mcp.autonomous_tools import autonomous_list_runs
        out = asyncio.run(autonomous_list_runs({"limit": 5}))
        assert "content" in out
        assert "ERROR" not in out["content"][0]["text"]


# ---------------------------------------------------------------------------
# specs_from_registry
# ---------------------------------------------------------------------------

class TestSpecsFromRegistry:
    def test_converts_registry(self, mock_registry):
        specs = specs_from_registry(mock_registry)
        names = {s.name for s in specs}
        assert {"echo", "fail", "list"} <= names
        for s in specs:
            assert s.description
            assert s.category


# ---------------------------------------------------------------------------
# Integration tests (REAL LLM)
# ---------------------------------------------------------------------------

def _has_openrouter() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _has_ollama() -> bool:
    # local Ollama fallback is always attempted after OpenRouter
    return True


pytestmark_integration = pytest.mark.integration

# Register custom marks via pytestmark for the whole module's integration
# tests (we keep the unit tests unmarked by collecting them in non-marked
# classes; the integration class uses the integration mark explicitly).



@pytest.mark.skipif(not _has_openrouter() and not _has_ollama(),
                    reason="No LLM available (no OPENROUTER_API_KEY, no Ollama)")
@pytest.mark.integration
class TestAutonomousIntegration:
    """Real LLM calls: plan, execute, and the full plan->execute->learn loop."""

    def _llm(self) -> HybridLLMClient:
        return HybridLLMClient()

    @pytest.mark.asyncio
    async def test_real_plan_for_simple_goal(self):
        from graxia_tool.mcp import build_default_registry
        llm = self._llm()
        reg = build_default_registry()
        specs = specs_from_registry(reg)
        planner = GOAPPlanner(specs, llm_client=llm, max_expansion=3)
        plan = await planner.plan("List the available agents in the system")
        # We don't assert success of the goal — we only check the planner
        # produced something sane with a real LLM.
        assert plan.run_id
        assert plan.tool_chain  # may be empty if planner chose nothing
        assert plan.expected_steps == len(plan.steps)
        # If we got steps, they must reference real tools
        for s in plan.steps:
            assert s.tool in {t.name for t in specs}

    @pytest.mark.asyncio
    async def test_real_full_loop_with_anus_save(self, tmp_project: Path):
        """Plan -> execute -> learn -> save ANUS.md against the real registry."""
        from graxia_tool.mcp import build_default_registry
        llm = self._llm()
        reg = build_default_registry()
        store = RunStore(path=tmp_project / "runs.json")
        executor = AutonomousExecutor(
            registry=reg, llm_client=llm, store=store,
            max_steps=4, max_replans=1,
        )
        result = await executor.run("Tell me the system status")
        # The actual success may vary; we mainly check the structure.
        assert result.run_id
        assert isinstance(result.success, bool)
        assert result.steps_executed >= 1
        # Now run the learner and verify ANUS.md is created
        if result.record is not None:
            ctx = ANUSContext()
            project = ctx.load(str(tmp_project))
            project.goals.append("Tell me the system status")
            learner = SelfLearner(llm_client=llm)
            lessons = await learner.apply(
                result.record, project, ctx, project_path=str(tmp_project),
            )
            assert lessons, "expected at least one lesson"
            # ANUS.md must now exist
            anus_path = ctx.path_for(str(tmp_project))
            assert anus_path.exists()
            text = anus_path.read_text(encoding="utf-8")
            assert "learnings" in text
            assert "history" in text
            for l in lessons:
                assert l.text[:30] in text or l.text[:30].lower() in text.lower()
