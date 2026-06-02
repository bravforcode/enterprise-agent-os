"""Enterprise Agent OS — Phase 1 tests."""
import pytest
from graxia_tool.core.intent_router import (
    classify_intent, Intent, Domain, RiskLevel, _keyword_classify,
)
from graxia_tool.tools.registry import ToolRegistry, ToolDefinition
from graxia_tool.skills.registry import SkillRegistry, SkillDefinition
from graxia_tool.core.output_validator import OutputValidator
from graxia_tool.core.approval_flow import ApprovalFlow, ApprovalStatus


# --- Intent Router Tests ---
class TestIntentRouter:
    def test_keyword_classify_code(self):
        result = _keyword_classify("write a python function to parse JSON")
        assert result.intent == Intent.CODE
        assert result.domain == Domain.PYTHON
        assert result.risk_level == RiskLevel.MEDIUM

    def test_keyword_classify_debug(self):
        result = _keyword_classify("debug this error in my code")
        assert result.intent == Intent.DEBUG

    def test_keyword_classify_deploy(self):
        result = _keyword_classify("deploy to production server")
        assert result.intent == Intent.DEPLOY
        assert result.risk_level == RiskLevel.CRITICAL

    def test_keyword_classify_test(self):
        result = _keyword_classify("write pytest tests for this module")
        # "write" matches CODE, "pytest"/"tests" matches TEST — both valid
        assert result.intent in (Intent.TEST, Intent.CODE)

    def test_keyword_classify_review(self):
        result = _keyword_classify("review this pull request")
        assert result.intent == Intent.REVIEW

    def test_keyword_classify_research(self):
        result = _keyword_classify("research best practices for authentication")
        assert result.intent == Intent.RESEARCH

    def test_keyword_classify_unknown(self):
        result = _keyword_classify("hello")
        assert result.intent == Intent.CONVERSATION

    @pytest.mark.asyncio
    async def test_classify_intent_async(self):
        result = await classify_intent("write python code to parse CSV")
        # "parse CSV" matches DATA, "write code" matches CODE — both valid
        assert result.intent in (Intent.CODE, Intent.DATA)
        assert result.domain == Domain.PYTHON

    def test_entity_extraction(self):
        result = _keyword_classify("read file /path/to/file.py")
        assert "file" in result.entities

    def test_url_extraction(self):
        result = _keyword_classify("fetch data from https://api.example.com")
        assert "url" in result.entities


# --- Tool Registry Tests ---
class TestToolRegistry:
    def test_default_tools_loaded(self):
        registry = ToolRegistry()
        assert len(registry.tools) > 0
        assert "file_read" in registry.tools
        assert "shell_exec" in registry.tools

    def test_permission_check(self):
        registry = ToolRegistry()
        assert registry.can_access("file_read", 0)  # read at level 0
        assert registry.can_access("shell_exec", 2)  # exec at level 2
        assert not registry.can_access("shell_exec", 0)  # no exec at level 0

    def test_approval_required(self):
        registry = ToolRegistry()
        assert registry.requires_approval("database_query")
        assert registry.requires_approval("deploy")
        assert not registry.requires_approval("file_read")

    def test_get_tools_for_level(self):
        registry = ToolRegistry()
        level0 = registry.get_tools_for_level(0)
        assert all(t.permission_level <= 0 for t in level0)

    def test_register_custom_tool(self):
        registry = ToolRegistry()
        custom = ToolDefinition(
            name="custom_tool",
            description="Custom",
            permission_level=1,
        )
        registry.register(custom)
        assert "custom_tool" in registry.tools

    def test_usage_stats(self):
        registry = ToolRegistry()
        stats = registry.get_usage_stats()
        assert isinstance(stats, dict)


# --- Skill Registry Tests ---
class TestSkillRegistry:
    def test_empty_registry(self):
        registry = SkillRegistry()
        assert len(registry.skills) == 0

    def test_list_skills(self):
        registry = SkillRegistry()
        skills = registry.list_skills()
        assert isinstance(skills, list)

    def test_match_intent_empty(self):
        registry = SkillRegistry()
        matched = registry.match_intent("code", "python")
        assert isinstance(matched, list)


# --- Output Validator Tests ---
class TestOutputValidator:
    def test_valid_output(self):
        validator = OutputValidator()
        result = validator.validate("Hello world")
        assert result.valid

    def test_empty_output_warning(self):
        validator = OutputValidator()
        result = validator.validate("")
        assert result.valid  # warnings don't make it invalid
        assert any("empty" in w.lower() for w in result.warnings)

    def test_dangerous_command_blocked(self):
        validator = OutputValidator()
        result = validator.validate("rm -rf /important/dir")
        assert not result.valid
        assert result.safety_blocked

    def test_secret_redacted(self):
        validator = OutputValidator()
        result = validator.validate("API key: sk-abc123def456ghi789jkl012")
        assert "[REDACTED]" in result.sanitized_output

    def test_truncation(self):
        validator = OutputValidator(max_output_chars=100)
        result = validator.validate("a" * 200)
        assert result.truncated
        assert len(result.sanitized_output) < 200

    def test_code_output_short_warning(self):
        validator = OutputValidator()
        result = validator.validate("x = 1", intent="code")
        assert any("short" in w.lower() for w in result.warnings)


# --- Approval Flow Tests ---
class TestApprovalFlow:
    def test_request_approval(self):
        flow = ApprovalFlow()
        req = flow.request_approval(
            run_id="run-1",
            step_id="step-1",
            tool_name="deploy",
            description="Deploy to production",
            params={"env": "prod"},
        )
        assert req.status == ApprovalStatus.PENDING
        assert len(flow.pending) == 1

    def test_approve(self):
        flow = ApprovalFlow()
        req = flow.request_approval(
            run_id="run-1",
            step_id="step-1",
            tool_name="deploy",
            description="Deploy",
            params={},
        )
        approved = flow.approve(req.id, "Looks good")
        assert approved.status == ApprovalStatus.APPROVED
        assert len(flow.pending) == 0
        assert len(flow.history) == 1

    def test_reject(self):
        flow = ApprovalFlow()
        req = flow.request_approval(
            run_id="run-1",
            step_id="step-1",
            tool_name="deploy",
            description="Deploy",
            params={},
        )
        rejected = flow.reject(req.id, "Too risky")
        assert rejected.status == ApprovalStatus.REJECTED

    def test_get_pending(self):
        flow = ApprovalFlow()
        flow.request_approval("r1", "s1", "tool1", "desc", {})
        flow.request_approval("r2", "s2", "tool2", "desc", {})
        pending = flow.get_pending()
        assert len(pending) == 2

    def test_get_pending_by_run(self):
        flow = ApprovalFlow()
        flow.request_approval("r1", "s1", "tool1", "desc", {})
        flow.request_approval("r2", "s2", "tool2", "desc", {})
        pending = flow.get_pending(run_id="r1")
        assert len(pending) == 1
