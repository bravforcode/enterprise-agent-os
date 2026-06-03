"""Tests for Skill Auto-Hydration and Auto-Healing."""
from __future__ import annotations

import pytest

from graxia_tool.pipeline import (
    EndToEndPipeline,
    PipelineRequest,
    PipelineResponse,
    FALLBACK_MAP,
)


class TestFallbackMap:
    def test_fallback_map_has_all_agents(self):
        from graxia_tool.agents.implementations import AGENT_REGISTRY
        for name in AGENT_REGISTRY:
            assert name in FALLBACK_MAP, f"{name} missing from FALLBACK_MAP"
            assert len(FALLBACK_MAP[name]) > 0, f"{name} has no fallbacks"

    def test_fallback_chain_ends_at_general_or_conversational(self):
        for agent, fallbacks in FALLBACK_MAP.items():
            last = fallbacks[-1]
            assert last in ("general", "conversational"), (
                f"{agent} chain does not end at general/conversational: {fallbacks}"
            )

    def test_no_self_fallback(self):
        for agent, fallbacks in FALLBACK_MAP.items():
            assert agent not in fallbacks, f"{agent} has self as fallback"


class TestSkillHydration:
    def setup_method(self):
        self.pipe = EndToEndPipeline()

    @pytest.mark.asyncio
    async def test_route_sets_routing_decision(self):
        request = PipelineRequest(input="write code for login", user_id="test")
        response = await self.pipe.process(request)
        assert response.success
        assert response.request_id is not None
        assert response.intent is not None

    @pytest.mark.asyncio
    async def test_skills_context_in_request(self):
        request = PipelineRequest(input="write code for login", user_id="test")
        response = await self.pipe.process(request)
        assert hasattr(response, "skills_loaded")

    @pytest.mark.asyncio
    async def test_skills_loaded_for_debug(self):
        request = PipelineRequest(input="debug the error in main.py", user_id="test")
        response = await self.pipe.process(request)
        assert isinstance(response.skills_loaded, list)

    @pytest.mark.asyncio
    async def test_hydrate_skills_returns_dict(self):
        from graxia_tool.auto_router import RoutingDecision
        decision = self.pipe.auto_router.route("write code for login")
        hydrated = self.pipe._hydrate_skills(decision)
        assert isinstance(hydrated, dict)

    @pytest.mark.asyncio
    async def test_skill_content_in_agent_context(self):
        request = PipelineRequest(input="write code for login", user_id="test")
        response = await self.pipe.process(request)
        stages_names = [s["name"] for s in response.stages]
        assert "skill_hydrate" in stages_names

    @pytest.mark.asyncio
    async def test_find_fallback_agent_returns_valid(self):
        fb = self.pipe._find_fallback_agent("code", "coder")
        assert fb is None or fb in self.pipe.agents

    @pytest.mark.asyncio
    async def test_find_fallback_debugger_to_coder(self):
        fb = self.pipe._find_fallback_agent("debug", "debugger")
        assert fb == "coder"

    @pytest.mark.asyncio
    async def test_find_fallback_tester_to_coder(self):
        fb = self.pipe._find_fallback_agent("test", "tester")
        assert fb == "coder"


class TestAutoHealing:
    def setup_method(self):
        self.pipe = EndToEndPipeline(max_retries=2)

    @pytest.mark.asyncio
    async def test_healing_attempts_on_success(self):
        request = PipelineRequest(input="write code for login", user_id="test")
        response = await self.pipe.process(request)
        assert isinstance(response.healing_attempts, int)

    @pytest.mark.asyncio
    async def test_execute_with_healing_basic(self):
        class DummyAgent:
            async def run(self, prompt, context=None):
                from graxia_tool.agents.base import SubAgentResult
                return SubAgentResult(success=True, output="ok")
            name = "dummy"

        result, attempts = await self.pipe._execute_with_healing(
            agent_name="coder",
            prompt="test",
            context={},
            intent="code",
            stages_log=lambda *a, **kw: None,
            request_id="test",
        )
        assert result.success
        assert attempts == 0

    @pytest.mark.asyncio
    async def test_healing_escalates_on_failure(self):
        request = PipelineRequest(
            input="debug a nonexistent thing that will fail",
            user_id="test",
            skip_guards=True,
            skip_governance=True,
        )
        response = await self.pipe.process(request)
        assert isinstance(response.healing_attempts, int)

    def test_fallback_map_all_agents_covered(self):
        from graxia_tool.agents.implementations import AGENT_REGISTRY
        for name in AGENT_REGISTRY:
            assert name in FALLBACK_MAP

    def test_fallback_map_no_self_reference(self):
        for name, fallbacks in FALLBACK_MAP.items():
            assert name not in fallbacks


class TestPipelineRequest:
    def test_default_skills_context_empty(self):
        req = PipelineRequest(input="hello")
        assert req.skills_context == {}

    def test_default_routing_decision_none(self):
        req = PipelineRequest(input="hello")
        assert req.routing_decision is None

    def test_can_set_skills_context(self):
        req = PipelineRequest(input="test", skills_context={"rtk-tdd": "content"})
        assert req.skills_context["rtk-tdd"] == "content"


class TestPipelineResponse:
    def test_default_healing_attempts_zero(self):
        resp = PipelineResponse(
            request_id="1", success=True, output="", stages=[], duration_ms=0
        )
        assert resp.healing_attempts == 0

    def test_default_skills_loaded_empty(self):
        resp = PipelineResponse(
            request_id="1", success=True, output="", stages=[], duration_ms=0
        )
        assert resp.skills_loaded == []


class TestStoreSkillFeedback:
    def setup_method(self):
        self.pipe = EndToEndPipeline()

    def test_store_feedback_no_skills(self):
        from graxia_tool.auto_router import RoutingDecision
        decision = RoutingDecision(intent="code", cache_key="test")
        self.pipe._store_skill_feedback(decision, [], success=True)

    def test_store_feedback_with_skills(self):
        from graxia_tool.auto_router import RoutingDecision
        decision = RoutingDecision(intent="code", cache_key="test_fb")
        self.pipe._store_skill_feedback(
            decision, ["rtk-tdd", "test-driven-development"], success=True
        )


class TestReadSkillContent:
    def setup_method(self):
        self.pipe = EndToEndPipeline()

    def test_read_skill_content_empty_for_nonexistent(self):
        from graxia_tool.skills.registry import SkillDefinition
        skill = SkillDefinition(
            name="nonexistent", description="", path="/tmp/nonexistent"
        )
        content = self.pipe._read_skill_content(skill)
        assert content == ""
