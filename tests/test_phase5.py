"""Enterprise Agent OS — Phase 5 tests."""
import pytest
import asyncio
from agent_os.agents.base import BaseSubAgent, SubAgentResult
from agent_os.agents.implementations import (
    Coder, Debugger, Tester, Reviewer, Deployer,
    Documenter, Researcher, DataEngineer, Sysadmin,
    Conversational, General, Validator, Planner, Architect, SecurityAuditor,
    AGENT_REGISTRY, get_agent, list_agents,
)


class TestAgentRegistry:
    def test_all_agents_registered(self):
        assert len(AGENT_REGISTRY) == 15

    def test_expected_agents(self):
        expected = {
            "coder", "debugger", "tester", "reviewer", "deployer",
            "documenter", "researcher", "data_engineer", "sysadmin",
            "conversational", "general", "validator", "planner",
            "architect", "security_auditor",
        }
        actual = set(AGENT_REGISTRY.keys())
        assert actual == expected

    def test_get_agent(self):
        agent = get_agent("coder")
        assert isinstance(agent, Coder)
        assert agent.name == "coder"

    def test_get_unknown_agent(self):
        agent = get_agent("nonexistent")
        assert agent is None

    def test_list_agents(self):
        agents = list_agents()
        assert len(agents) == 15
        assert "coder" in agents


class TestSubAgentBase:
    def test_result_dataclass(self):
        result = SubAgentResult(success=True, output={"test": 1})
        assert result.success
        assert result.output == {"test": 1}
        assert result.error is None
        assert result.tokens_used == 0

    def test_result_with_error(self):
        result = SubAgentResult(success=False, output=None, error="Test error")
        assert not result.success
        assert result.error == "Test error"

    @pytest.mark.asyncio
    async def test_run_sets_timing(self):
        agent = General()
        result = await agent.run("test")
        # Duration is recorded even if 0 for very fast operations
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_run_handles_exception(self):
        class FailingAgent(BaseSubAgent):
            name = "failing"

            async def execute(self, query, context=None):
                raise ValueError("Test error")

        agent = FailingAgent()
        result = await agent.run("test")
        assert not result.success
        assert "Test error" in result.error


class TestIndividualAgents:
    @pytest.mark.asyncio
    async def test_coder_without_llm(self):
        agent = Coder()
        result = await agent.run("write a function")
        assert result.success
        assert "code" in result.output

    @pytest.mark.asyncio
    async def test_coder_with_llm(self):
        async def mock_llm(prompt):
            return "def hello():\n    return 'world'"

        agent = Coder(llm_func=mock_llm)
        result = await agent.run("write hello world")
        assert result.success
        assert "hello" in result.output["code"]
        assert result.tokens_used > 0

    @pytest.mark.asyncio
    async def test_debugger(self):
        agent = Debugger()
        result = await agent.run("fix the bug")
        assert result.success
        assert "diagnosis" in result.output

    @pytest.mark.asyncio
    async def test_tester(self):
        agent = Tester()
        result = await agent.run("test the function")
        assert result.success
        assert "tests" in result.output

    @pytest.mark.asyncio
    async def test_reviewer(self):
        agent = Reviewer()
        result = await agent.run("review the PR")
        assert result.success
        assert "review" in result.output

    @pytest.mark.asyncio
    async def test_deployer(self):
        agent = Deployer()
        result = await agent.run("deploy to staging")
        assert result.success
        # Without LLM, output has "plan" key; with LLM, "requires_approval"
        assert "plan" in result.output or "requires_approval" in result.output

    @pytest.mark.asyncio
    async def test_documenter(self):
        agent = Documenter()
        result = await agent.run("document the API")
        assert result.success
        assert "docs" in result.output

    @pytest.mark.asyncio
    async def test_researcher(self):
        agent = Researcher()
        result = await agent.run("research best practices")
        assert result.success
        assert "findings" in result.output

    @pytest.mark.asyncio
    async def test_data_engineer(self):
        agent = DataEngineer()
        result = await agent.run("build pipeline")
        assert result.success
        assert "pipeline" in result.output

    @pytest.mark.asyncio
    async def test_sysadmin(self):
        agent = Sysadmin()
        result = await agent.run("check disk space")
        assert result.success
        assert "commands" in result.output

    @pytest.mark.asyncio
    async def test_conversational(self):
        agent = Conversational()
        result = await agent.run("hello")
        assert result.success

    @pytest.mark.asyncio
    async def test_general(self):
        agent = General()
        result = await agent.run("do something")
        assert result.success

    @pytest.mark.asyncio
    async def test_validator(self):
        agent = Validator()
        # Valid output
        result = await agent.run("test", context={"output": "x" * 100})
        assert result.success
        assert result.output["valid"] is True
        # Empty output
        result = await agent.run("test", context={"output": ""})
        assert not result.output["valid"]

    @pytest.mark.asyncio
    async def test_planner(self):
        agent = Planner()
        result = await agent.run("plan the project")
        assert result.success
        assert "plan" in result.output

    @pytest.mark.asyncio
    async def test_architect(self):
        agent = Architect()
        result = await agent.run("design the system")
        assert result.success
        assert "design" in result.output

    @pytest.mark.asyncio
    async def test_security_auditor(self):
        agent = SecurityAuditor()
        result = await agent.run("audit the code")
        assert result.success
        assert "audit" in result.output


class TestAgentMetadata:
    def test_coder_required_skills(self):
        agent = Coder()
        assert "rtk-tdd" in agent.required_skills

    def test_coder_required_tools(self):
        agent = Coder()
        assert "file_read" in agent.required_tools
        assert "file_write" in agent.required_tools

    def test_deployer_max_tokens(self):
        agent = Deployer()
        assert agent.max_tokens >= 6000

    def test_agent_names_unique(self):
        names = [cls.name for cls in AGENT_REGISTRY.values()]
        assert len(names) == len(set(names))

    def test_all_have_descriptions(self):
        for cls in AGENT_REGISTRY.values():
            assert cls.description
            assert len(cls.description) > 5
