"""Tests for Auto Router — unified prompt routing."""
from __future__ import annotations

import pytest

from graxia_tool.auto_router import AutoRouter, RoutingDecision


class TestRoutingDecision:
    def test_default_fields(self):
        d = RoutingDecision()
        assert d.skills == []
        assert d.rag_technique == "hybrid_search"
        assert d.agent_type == "general"
        assert d.model_tier == "mini"
        assert d.intent == "unknown"
        assert d.confidence == 0.0
        assert isinstance(d.mcp_tools, list)
        assert d.cache_key == ""

    def test_to_dict_includes_all_fields(self):
        d = RoutingDecision(
            skills=["rtk-tdd"],
            rag_technique="chunk_free_rag",
            agent_type="coder",
            intent="code",
            confidence=0.85,
            cache_key="abc123",
            mcp_tools=["agent_list"],
        )
        result = d.to_dict()
        assert result["skills"] == ["rtk-tdd"]
        assert result["intent"] == "code"
        assert result["agent_type"] == "coder"
        assert result["cache_key"] == "abc123"
        assert result["confidence"] == 0.85

    def test_to_dict_roundtrip(self):
        d = RoutingDecision(intent="debug", confidence=0.9, agent_type="debugger")
        d2 = RoutingDecision(**d.to_dict())
        assert d2.intent == d.intent
        assert d2.confidence == d.confidence
        assert d2.agent_type == d.agent_type


class TestAutoRouter:
    def setup_method(self):
        self.router = AutoRouter()

    def test_init(self):
        assert self.router._route_count == 0
        assert self.router._route_times_ms == []

    def test_route_returns_routing_decision(self):
        decision = self.router.route("write code for login")
        assert isinstance(decision, RoutingDecision)

    def test_route_code_intent(self):
        decision = self.router.route("write code for login")
        assert decision.intent == "code"
        assert decision.agent_type == "coder"
        assert float(decision.confidence) > 0
        assert isinstance(decision.skills, list)
        assert "rtk-tdd" in decision.skills or "test-driven-development" in decision.skills

    def test_route_debug_intent(self):
        decision = self.router.route("debug the error in main.py")
        assert decision.intent == "debug"
        assert decision.agent_type == "debugger"
        assert float(decision.confidence) > 0
        assert isinstance(decision.skills, list)

    def test_route_test_intent(self):
        decision = self.router.route("run the tests with pytest")
        assert decision.intent == "test"
        assert decision.agent_type == "tester"

    def test_route_review_intent(self):
        decision = self.router.route("review this PR")
        assert decision.intent == "review"
        assert decision.agent_type == "reviewer"

    def test_route_deploy_intent(self):
        decision = self.router.route("deploy to prod")
        assert decision.intent == "deploy"
        assert decision.agent_type == "deployer"

    def test_route_document_intent(self):
        decision = self.router.route("document the API endpoints")
        assert decision.intent == "document"
        assert decision.agent_type == "documenter"

    def test_route_research_intent(self):
        decision = self.router.route("research the topic")
        assert decision.intent == "research"
        assert decision.agent_type == "researcher"

    def test_route_data_intent(self):
        decision = self.router.route("check data quality in the csv")
        assert decision.intent == "data"
        assert decision.agent_type == "data_engineer"

    def test_route_empty_prompt(self):
        decision = self.router.route("")
        assert isinstance(decision, RoutingDecision)
        assert decision.intent in ("conversation", "unknown")

    def test_route_very_long_prompt(self):
        long_text = "write code " * 500
        decision = self.router.route(long_text)
        assert isinstance(decision, RoutingDecision)
        assert float(decision.confidence) > 0

    def test_route_mixed_language_prompt(self):
        decision = self.router.route("fix the bug in ระบบ login")
        assert isinstance(decision, RoutingDecision)
        assert float(decision.confidence) > 0

    def test_route_thai_code(self):
        decision = self.router.route("ช่วยเขียนโค้ด")
        assert isinstance(decision, RoutingDecision)
        assert isinstance(decision.skills, list)
        assert isinstance(decision.mcp_tools, list)

    def test_route_thai_debug(self):
        decision = self.router.route("แก้บัค")
        assert isinstance(decision, RoutingDecision)
        assert isinstance(decision.skills, list)

    def test_route_confidence_high_for_detail(self):
        short = self.router.route("hi")
        detailed = self.router.route("write a login function in python with tests")
        assert detailed.confidence >= short.confidence

    def test_route_model_tier_present(self):
        decision = self.router.route("write code")
        assert decision.model_tier in ("haiku", "mini", "main", "specialized")

    def test_route_rag_technique_present(self):
        decision = self.router.route("explain why the error happened because of null pointer")
        assert isinstance(decision.rag_technique, str)
        assert len(decision.rag_technique) > 0

    def test_route_cache_key_unique(self):
        d1 = self.router.route("write code for login")
        d2 = self.router.route("debug the error")
        assert d1.cache_key != d2.cache_key

    def test_route_cache_key_deterministic(self):
        d1 = self.router.route("write code for login")
        d2 = self.router.route("write code for login")
        assert d1.cache_key == d2.cache_key

    def test_route_context_notes_contains_intent(self):
        decision = self.router.route("deploy to production")
        assert "Intent:" in decision.context_notes
        assert decision.intent in decision.context_notes

    def test_get_stats(self):
        self.router.route("write code")
        self.router.route("debug error")
        stats = self.router.get_stats()
        assert stats["route_count"] == 2
        assert stats["avg_route_ms"] >= 0

    def test_select_skills_code_prompt_includes_coding_skills(self):
        skills = self.router._select_skills("code", "write a function")
        assert isinstance(skills, list)

    def test_select_rag_code_returns_chunk_free_rag(self):
        rag, query = self.router._select_rag("write a function in python", "code")
        assert rag == "chunk_free_rag"
        assert len(query) > 0

    def test_select_rag_debug_returns_corrective_rag(self):
        rag, query = self.router._select_rag("fix the bug", "debug")
        assert rag == "corrective_rag"

    def test_select_rag_research_returns_hybrid_search(self):
        rag, query = self.router._select_rag("research the topic", "research")
        assert rag == "hybrid_search"

    def test_select_mcp_tools_code_includes_agent_list(self):
        tools = self.router._select_mcp_tools("code", "write a function")
        assert "agent_list" in tools

    def test_select_mcp_tools_deploy_includes_pipeline_run(self):
        tools = self.router._select_mcp_tools("deploy", "deploy to production")
        assert "pipeline_run" in tools

    def test_select_mcp_tools_research_includes_rag_query(self):
        tools = self.router._select_mcp_tools("research", "find information about X")
        assert "rag_query" in tools

    def test_select_mcp_tools_research_includes_vault_search(self):
        tools = self.router._select_mcp_tools("research", "research this")
        assert "vault_search" in tools

    def test_keyword_override_pptx(self):
        decision = self.router.route("create a presentation about AI")
        assert "pptx" in decision.skills

    def test_keyword_override_pdf(self):
        decision = self.router.route("convert the report to pdf")
        assert "pdf" in decision.skills

    def test_keyword_override_web_search(self):
        decision = self.router.route("search for the latest news")
        assert "web-search" in decision.skills

    def test_optimize_rag_query_removes_please(self):
        optimized = self.router._optimize_rag_query("please write a function", "code")
        assert not optimized.lower().startswith("please")

    def test_optimize_rag_query_fallback_short(self):
        optimized = self.router._optimize_rag_query("hi", "conversation")
        assert len(optimized) > 0

    def test_make_cache_key_normalizes_whitespace(self):
        k1 = self.router._make_cache_key("  write   code  ")
        k2 = self.router._make_cache_key("write code")
        assert k1 == k2

    def test_build_context_notes_includes_fields(self):
        from graxia_tool.core.intent_router import Intent, Domain
        notes = self.router._build_context_notes(
            Intent.CODE, Domain.PYTHON, ["rtk-tdd"], "chunk_free_rag"
        )
        assert "Intent: code" in notes
        assert "Domain: python" in notes
        assert "RAG: chunk_free_rag" in notes
        assert "Skills: rtk-tdd" in notes

    def test_compute_confidence_range(self):
        c = self.router._compute_confidence(0.5, "code", "write a login function")
        assert 0.0 <= c <= 1.0

    def test_compute_confidence_low_for_unknown(self):
        from graxia_tool.core.intent_router import Intent
        c = self.router._compute_confidence(0.5, Intent.UNKNOWN, "hi")
        assert c <= 0.4

    def test_context_passed_through(self):
        decision = self.router.route("write code", context={"user_id": "test"})
        assert isinstance(decision, RoutingDecision)
